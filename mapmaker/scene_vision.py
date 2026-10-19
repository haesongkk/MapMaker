"""RAM++ -> existing SAM3 text prompts -> original-resolution instance masks."""

from pathlib import Path
import gc, hashlib, os, re, sys, time
import numpy as np
from PIL import Image, ImageDraw
from .scene_run import ROOT, SAM3_CHECKPOINT, write, read, sha, status
from .object_candidates import candidates
from .runtime_paths import RAM_CHECKPOINT
from .mask_selection import select_masks, rejection_reason, MAX_RECONSTRUCTION_OBJECTS
from .analysis_regions import analysis_boxes, rank_candidates


def save_mask_candidates(run, raw, distinct_count):
    candidate_dir = run / 'masks/candidates'
    candidate_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for rec, mask in raw:
        rec['geometry_key'] = hashlib.sha256(np.packbits(mask).tobytes()).hexdigest()
        asset = f"masks/candidates/{rec['geometry_key']}.png"
        Image.fromarray(mask.astype('uint8') * 255).save(run / asset)
        records.append(dict(rec, mask=asset, mask_sha256=sha(run / asset)))
    # Keep the manifest inside the existing transferable masks namespace.
    asset = 'masks/candidates.json'
    write(run / asset, records)
    return dict(asset=asset, count=len(records), distinct_eligible_count=distinct_count,
        reconstruction_limit=MAX_RECONSTRUCTION_OBJECTS,
        limitation='Unselected masks are retained for evidence review; retention does not authorize reconstruction')


def ram_tags(
    images: list[Path], checkpoint: Path, device: str = "cuda", threshold_scale: float = 1.0
) -> dict[str, list[str]]:
    if not checkpoint.is_file():
        raise FileNotFoundError(f"RAM++ checkpoint missing: {checkpoint}")
    import torch
    from ram import get_transform, inference_ram
    from ram.models import ram_plus

    if not 0 < threshold_scale <= 1:
        raise ValueError("threshold_scale must be in (0, 1]")
    model = ram_plus(pretrained=str(checkpoint), image_size=384, vit="swin_l")
    model.class_threshold = model.class_threshold * threshold_scale
    model = model.eval().to(device)
    transform = get_transform(image_size=384)
    found = {}
    with torch.inference_mode():
        for path in images:
            result = inference_ram(
                transform(Image.open(path).convert("RGB")).unsqueeze(0).to(device),
                model,
            )
            found[str(path)] = sorted(
                {tag.strip().lower() for tag in result[0].split("|") if tag.strip()}
            )
    return found


def run_scene(run):
    from .execution_modes import requested
    selected = requested(read(Path(run) / 'scene_metadata.json'))
    if selected is not None and selected.initial:
        from .initial_vision import run_scene as initial
        return initial(run)
    import torch

    run = Path(run)
    meta = read(run / "scene_metadata.json")
    image_path = run / meta["input_image"]
    meta["implementation_sha256"] = {
        name: sha(ROOT / "mapmaker" / name)
        for name in (
            "object_candidates.py",
            "scene_vision.py",
            "mask_selection.py",
            "mask_geometry.py",
            "scene_contacts.py",
            "scene_source_guard.py",
            "scene_pose_refinement.py",
            "scene_overlap_refinement.py",
            "scene_overlap.py",
            "scene_pose_search.py",
            "scene_support_guard.py",
            "scene_collision.py",
            "scene_structure.py",
            "scene_orientation.py",
            "scene_vanishing.py",
            "scene_projection.py",
            "scene_composite_review.py",
            "analysis_regions.py",
            "segmentation_regions.py",
            "point_proposals.py",
            "mask_corroboration.py",
            "scene_geometry.py",
            "scene_reconstruct.py",
            "reconstruction_review.py",
            "reconstruction_evidence.py",
            "scene_assembly.py",
            "scene_placement.py",
            "scene_pipeline.py",
        )
    }
    start = time.monotonic()
    status(run, "analyzing", "Analyzing image with RAM++...")
    views = [image_path]
    regions = []
    source = Image.open(image_path).convert("RGB")
    for index, box in enumerate(analysis_boxes(*source.size)):
        path = run / "input" / f"analysis_region_{index}.png"
        source.crop(box).save(path)
        views.append(path)
        regions.append({"image": str(path.relative_to(run)), "box": box})
    tags_by_view = ram_tags(
        views, RAM_CHECKPOINT, threshold_scale=0.75
    )
    tags = sorted({tag for values in tags_by_view.values() for tag in values})
    prompts, rejected = candidates(tags)
    # Prioritize labels corroborated across views; this is not an image-specific list.
    from .object_candidates import ALIASES

    prompts, votes, overflow = rank_candidates(prompts, tags_by_view, str(image_path), ALIASES)
    assert not overflow  # Rank execution order, never discard localized evidence by vote count.
    extraction = {
        "model": "RAM++",
        "threshold_scale": 0.75,
        "code": "mapmaker.scene_vision.ram_tags",
        "raw_tags": tags,
        "tags_by_view": {
            str(Path(k).relative_to(run)): v for k, v in tags_by_view.items()
        },
        "regions": regions,
        "candidate_votes": votes,
        "candidate_policy": "all eligible detector tags segmented; localized tags scheduled first; no vote-count cutoff",
        "candidates": prompts,
        "rejected": rejected,
        "checkpoint": str(RAM_CHECKPOINT),
        "checkpoint_resolved": str(
            RAM_CHECKPOINT.resolve()
        ),
    }
    write(run / "object_candidates.json", extraction)
    meta["object_extraction"] = extraction
    meta["timing"]["object_extraction_seconds"] = time.monotonic() - start
    write(run / "scene_metadata.json", meta)
    gc.collect()
    torch.cuda.empty_cache()
    start = time.monotonic()
    status(run, "segmenting", "Loading SAM3 and segmenting objects...")
    from sam3.model_builder import build_sam3_image_model
    from sam3.model.sam3_image_processor import Sam3Processor

    processor = Sam3Processor(
        build_sam3_image_model(checkpoint_path=str(SAM3_CHECKPOINT), load_from_HF=False,
                              enable_inst_interactivity=True)
    )
    from .point_proposals import scan_small_instances, validate_interactive_weights
    interactive_weights = validate_interactive_weights(processor.model, SAM3_CHECKPOINT)
    image = Image.open(image_path).convert("RGB")
    raw = []
    detections = []
    torch.manual_seed(42)
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
        state = processor.set_image(image)
        for pi, prompt in enumerate(prompts):
            status(
                run,
                "segmenting",
                f"Segmenting candidates {pi + 1}/{len(prompts)}...",
                current=pi + 1,
                total=len(prompts),
            )
            processor.reset_all_prompts(state)
            out = processor.set_text_prompt(state=state, prompt=prompt)
            masks = (
                out["masks"]
                .cpu()
                .numpy()
                .reshape(-1, image.height, image.width)
                .astype(bool)
            )
            scores = out["scores"].float().cpu().tolist()
            for i, (mask, score) in enumerate(zip(masks, scores)):
                rec = {
                    "name": prompt,
                    "candidate_index": i,
                    "confidence": score,
                    "area": int(mask.sum()),
                }
                detections.append(rec)
                reason = rejection_reason(rec, image.width * image.height)
                if reason:
                    rec['rejected_reason'] = reason
                # Keep weak, nonempty observations for cross-view review. Selection
                # remains a separate decision and preserves the model score.
                if rec['confidence'] >= .6 and rec['area'] >= max(64, image.width * image.height * .0005):
                    raw.append((rec, mask))
        point_masks, point_report = scan_small_instances(processor.model, state, image.size,
            progress=lambda current, total: status(run, 'segmenting',
                f'Segmenting small regions {current}/{total}...', current=current, total=total))
        raw.extend(point_masks)
        detections.extend(rec for rec, _ in point_masks)
        extraction['point_segmentation'] = dict(point_report, weights=interactive_weights)
        if os.environ.get('MAPMAKER_MULTISCALE_POINTS', '0') == '1':
            from .multiscale_points import scan_point_crops
            zoom_masks, zoom_report = scan_point_crops(processor, image,
                progress=lambda view, views, current, total: status(run, 'segmenting',
                    f'Segmenting zoomed small regions {view+1}/{views}: {current}/{total}...'))
            raw.extend(zoom_masks)
            detections.extend(rec for rec, _ in zoom_masks)
            extraction['multiscale_point_segmentation'] = zoom_report
    from .segmentation_regions import crop_queries, restore_crop_mask
    queries = crop_queries(prompts, regions, extraction['tags_by_view'], ALIASES,
                           [(rec, mask) for rec, mask in raw
                            if rejection_reason(rec, image.width * image.height) is None],
                           image.width * image.height)
    total = sum(len(query['prompts']) for query in queries)
    current = 0
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
        for query in queries:
            box = query['box']
            crop = image.crop(box)
            state = processor.set_image(crop)
            for prompt in query['prompts']:
                current += 1
                status(run, 'segmenting', f'Segmenting localized candidates {current}/{total}...',
                       current=current, total=total)
                processor.reset_all_prompts(state)
                out = processor.set_text_prompt(state=state, prompt=prompt)
                masks = out['masks'].cpu().numpy().reshape(-1, crop.height, crop.width).astype(bool)
                scores = out['scores'].float().cpu().tolist()
                for index, (mask, score) in enumerate(zip(masks, scores)):
                    restored = restore_crop_mask(mask, box, image.size)
                    rec = dict(name=prompt, candidate_index=index, confidence=score,
                               source_crop=list(box), area=int(mask.sum()))
                    detections.append(rec)
                    reason = ('truncated crop mask' if restored is None else
                              rejection_reason(rec, image.width * image.height))
                    if reason:
                        rec['rejected_reason'] = reason
                    if (restored is not None and rec['confidence'] >= .6
                            and rec['area'] >= max(64, image.width * image.height * .0005)):
                        raw.append((rec, restored))
    extraction['localized_segmentation'] = dict(views=len(queries), prompts=total,
        policy='detector-localized prompts without sufficient mask evidence inside that crop; reject crop-truncated fragments')
    write(run / 'object_candidates.json', extraction)
    finish_segmentation(run, image, raw, detections, meta, start, torch.__version__)


def finish_segmentation(run, image, raw, detections, meta, start, torch_version):
    from .mask_corroboration import corroborate
    cross_view_evidence = corroborate(raw, image.width * image.height)
    selected = []
    counts = {}
    objects = []
    overlay = np.asarray(image).copy()
    colors = np.array(
        [
            [255, 70, 70],
            [50, 200, 100],
            [60, 130, 255],
            [230, 180, 40],
            [185, 70, 230],
            [40, 210, 210],
        ]
    )
    eligible = select_masks(raw, image.width * image.height, limit=None, cross_view_small=True)
    # Keep the original observations in the budgeted pass too: deduplication
    # would otherwise remove the second view needed to substantiate agreement.
    chosen = select_masks(raw, image.width * image.height, limit=MAX_RECONSTRUCTION_OBJECTS,
                          cross_view_small=True)
    # Preserve valid masks beyond the reconstruction budget so later geometry
    # review/replay does not require repeating GPU segmentation.
    meta['segmentation_candidates'] = save_mask_candidates(run, raw, len(eligible))
    for rec, mask in chosen:
        slug = re.sub("[^a-z0-9]+", "_", rec["name"]).strip("_") or "object"
        n = counts.get(slug, 0)
        counts[slug] = n + 1
        oid = f"{slug}_{n:02d}"
        rel = f"masks/{oid}.png"
        Image.fromarray(mask.astype("uint8") * 255).save(run / rel)
        yy, xx = np.where(mask)
        obj = {
            "id": oid,
            "name": rec["name"],
            "mask": rel,
            "mask_sha256": sha(run / rel),
            "mask_area": rec["area"],
            "confidence": rec["confidence"],
            "confidence_kind": rec.get('confidence_kind', 'detector_mask_and_presence_score'),
            "proposal_method": rec.get('proposal_method', 'detector_text_prompt'),
            "selection_evidence": rec.get('selection_evidence', {'route': 'single_view_confidence'}),
            "bbox": [
                int(xx.min()),
                int(yy.min()),
                int(xx.max() + 1),
                int(yy.max() + 1),
            ],
            "status": "masked",
        }
        rec["selected_object_id"] = oid
        objects.append(obj)
        selected.append(mask)
        overlay[mask] = (
            0.55 * overlay[mask] + 0.45 * colors[(len(objects) - 1) % len(colors)]
        ).astype("uint8")
    preview = Image.fromarray(overlay)
    draw = ImageDraw.Draw(preview)
    for obj in objects:
        draw.text(
            tuple(obj["bbox"][:2]),
            obj["id"],
            fill="white",
            stroke_width=1,
            stroke_fill="black",
        )
    preview.save(run / "previews/masks.png")
    write(
        run / "logs/segmentation.json",
        {
            "checkpoint": str(SAM3_CHECKPOINT),
            "processor_confidence_threshold": 0.5,
            "selection_confidence_threshold": 0.6,
            "min_area_fraction": 0.0005,
            "min_area_pixels": 64,
            "small_area_fraction": 0.003,
            "small_confidence_threshold": 0.8,
            "reserved_small_slots": 3,
            "duplicate_iou": 0.8,
            "contained_fraction": 0.9,
            "containment_policy": "label-free similar-size masks only; small containment remains ambiguous",
            "max_objects": MAX_RECONSTRUCTION_OBJECTS,
            "retained_candidate_masks": meta['segmentation_candidates']['count'],
            "cross_view_evidence": cross_view_evidence,
            "cross_view_selection_enabled": True,
            "mask_resolution": list(image.size),
            "detections": detections,
        },
    )
    meta["objects"] = objects
    meta["timing"]["segmentation_seconds"] = time.monotonic() - start
    meta["pipeline"]["vision_torch"] = torch_version
    write(run / "scene_metadata.json", meta)
    if not objects:
        raise RuntimeError(
            "SAM3 found no eligible instance masks for the RAM++ candidates"
        )
    status(
        run, "segmented", f"Generated {len(objects)} instance masks", total=len(objects)
    )


if __name__ == "__main__":
    run_scene(Path(sys.argv[1]).resolve())
