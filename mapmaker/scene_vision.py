"""RAM++ -> existing SAM3 text prompts -> original-resolution instance masks."""

from pathlib import Path
import gc, re, sys, time
import numpy as np
from PIL import Image, ImageDraw
from .scene_run import ROOT, SAM3_CHECKPOINT, write, read, sha, status
from .object_candidates import candidates
from .runtime_paths import RAM_CHECKPOINT


def run_scene(run):
    from .models import ram_tags
    import torch

    run = Path(run)
    meta = read(run / "scene_metadata.json")
    image_path = run / meta["input_image"]
    meta["implementation_sha256"] = {
        name: sha(ROOT / "mapmaker" / name)
        for name in (
            "models.py",
            "object_candidates.py",
            "scene_vision.py",
            "scene_reconstruct.py",
            "scene_assembly.py",
            "scene_pipeline.py",
        )
    }
    start = time.monotonic()
    status(run, "analyzing", "Analyzing image with RAM++...")
    views = [image_path]
    regions = []
    source = Image.open(image_path).convert("RGB")
    if max(source.size) > 768:
        for index, (x, y) in enumerate(
            ((0, 0), (0.4, 0), (0, 0.4), (0.4, 0.4), (0.2, 0.2))
        ):
            box = (
                int(x * source.width),
                int(y * source.height),
                min(source.width, int((x + 0.6) * source.width)),
                min(source.height, int((y + 0.6) * source.height)),
            )
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

    votes = {
        name: sum(
            any(ALIASES.get(t, t) == name for t in values)
            for values in tags_by_view.values()
        )
        for name in prompts
    }
    ranked = sorted(prompts, key=lambda name: (-votes[name], name))
    rejected.extend(
        {"tag": name, "reason": "candidate budget 40"} for name in ranked[40:]
    )
    prompts = ranked[:40]
    extraction = {
        "model": "RAM++",
        "threshold_scale": 0.75,
        "code": "mapmaker.models.ram_tags",
        "raw_tags": tags,
        "tags_by_view": {
            str(Path(k).relative_to(run)): v for k, v in tags_by_view.items()
        },
        "regions": regions,
        "candidate_votes": votes,
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
    if not prompts:
        raise RuntimeError("RAM++ found no eligible independent object candidates")
    gc.collect()
    torch.cuda.empty_cache()
    start = time.monotonic()
    status(run, "segmenting", "Loading SAM3 and segmenting objects...")
    from sam3.model_builder import build_sam3_image_model
    from sam3.model.sam3_image_processor import Sam3Processor

    processor = Sam3Processor(
        build_sam3_image_model(checkpoint_path=str(SAM3_CHECKPOINT), load_from_HF=False)
    )
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
                if score < 0.6:
                    rec["rejected_reason"] = "mask confidence < 0.6"
                elif rec["area"] < image.width * image.height * 0.003:
                    rec["rejected_reason"] = "area < 0.003 of image"
                else:
                    raw.append((rec, mask))
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
    for rec, mask in sorted(
        raw,
        key=lambda x: (
            -x[0]["area"],
            -x[0]["confidence"],
            x[0]["name"],
            x[0]["candidate_index"],
        ),
    ):
        if any(
            (mask & m).sum() / max(1, (mask | m).sum()) > 0.8
            or (mask & m).sum() / max(1, mask.sum()) > 0.9
            for m in selected
        ):
            rec["rejected_reason"] = (
                "duplicate IoU > 0.8 or > 0.9 contained in a larger mask"
            )
            continue
        if len(objects) >= 12:
            rec["rejected_reason"] = "major-object limit 12"
            continue
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
            "min_area_fraction": 0.003,
            "duplicate_iou": 0.8,
            "contained_fraction": 0.9,
            "max_objects": 12,
            "mask_resolution": list(image.size),
            "detections": detections,
        },
    )
    meta["objects"] = objects
    meta["timing"]["segmentation_seconds"] = time.monotonic() - start
    meta["pipeline"]["vision_torch"] = torch.__version__
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
