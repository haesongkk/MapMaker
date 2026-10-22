"""Default RAM++ tags -> all default SAM3 masks -> baseline reconstruction."""

from pathlib import Path
import gc, sys, time
import numpy as np
from PIL import Image, ImageDraw
from .scene_run import ROOT, SAM3_CHECKPOINT, write, read, sha, status
from .runtime_paths import RAM_CHECKPOINT


def ram_tags(images, checkpoint):
    """Preserve the default model's English output, including order and repeats."""
    import torch
    from ram import get_transform, inference_ram
    from ram.models import ram_plus
    model = ram_plus(pretrained=str(checkpoint), image_size=384, vit="swin_l")
    model = model.eval().to("cuda")
    transform = get_transform(image_size=384)
    found = {}
    with torch.inference_mode():
        for path in images:
            result = inference_ram(
                transform(Image.open(path).convert("RGB")).unsqueeze(0).to("cuda"), model
            )
            found[str(path)] = [tag.strip() for tag in result[0].split("|") if tag.strip()]
    return found


def run_scene(run):
    import torch

    run = Path(run)
    meta = read(run / "scene_metadata.json")
    image_path = run / meta["input_image"]
    meta["implementation_sha256"] = {
        name: sha(ROOT / "mapmaker" / name)
        for name in (
            "initial_vision.py",
            "initial_reconstruct.py",
            "scene_assembly.py",
            "scene_placement.py",
            "scene_pipeline.py",
        )
    }
    start = time.monotonic()
    status(run, "analyzing", "Reading baseline image tags...")
    views = [image_path]
    regions = []
    tagger = meta.get('execution', {}).get('tagger', 'ram++')
    if tagger == 'qwen2.5-vl-7b':
        from .qwen_tags import MODEL, REVISION, parse_tags
        evidence = read(run / 'logs/qwen_response.json')
        if (evidence['input_sha256'] != sha(image_path) or
                evidence['model'] != MODEL or evidence['revision'] != REVISION):
            raise ValueError('Qwen tag provenance does not match this run')
        prompts = parse_tags(evidence['raw_response'])
        if prompts != evidence['tags']:
            raise ValueError('Qwen tags differ from its raw response')
        tags_by_view = {str(image_path): prompts}
    elif tagger == 'ram++':
        tags_by_view = ram_tags(views, RAM_CHECKPOINT)
    else:
        raise ValueError(f'Unknown baseline tagger: {tagger}')
    prompts = tags_by_view[str(image_path)]
    extraction = {
        "model": "RAM++",
        "threshold_policy": "model_default",
        "code": "mapmaker.initial_vision.ram_tags",
        "raw_tags": prompts,
        "tags_by_view": {
            str(Path(k).relative_to(run)): v for k, v in tags_by_view.items()
        },
        "regions": regions,
        "candidates": prompts,
        "rejected": [],
        "policy": "default_model_outputs_unfiltered_v1",
        "checkpoint": str(RAM_CHECKPOINT),
        "checkpoint_resolved": str(
            RAM_CHECKPOINT.resolve()
        ),
    }
    if tagger == 'qwen2.5-vl-7b':
        for key in ('checkpoint', 'checkpoint_resolved', 'threshold_policy'):
            extraction.pop(key)
        extraction.update(model=MODEL, revision=REVISION, code='mapmaker.qwen_tags',
            prompt=evidence['prompt'], raw_response=evidence['raw_response'],
            generation=evidence['generation'], evidence='logs/qwen_response.json')
        meta['pipeline']['object_extraction_model'] = MODEL
    write(run / "object_candidates.json", extraction)
    meta["object_extraction"] = extraction
    meta["timing"]["object_extraction_seconds"] = time.monotonic() - start
    write(run / "scene_metadata.json", meta)
    if not prompts:
        raise RuntimeError("Tag model returned no text prompts")
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
                    "prompt_index": pi,
                    "confidence": score,
                    "area": int(mask.sum()),
                }
                detections.append(rec)
                raw.append((rec, mask))
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
    for rec, mask in raw:
        oid = f"prompt_{rec['prompt_index']:04d}_mask_{rec['candidate_index']:04d}"
        rel = f"masks/{oid}.png"
        Image.fromarray(mask.astype("uint8") * 255).save(run / rel)
        yy, xx = np.where(mask)
        obj = {
            "id": oid,
            "name": rec["name"],
            "prompt_index": rec["prompt_index"],
            "candidate_index": rec["candidate_index"],
            "mask": rel,
            "mask_sha256": sha(run / rel),
            "mask_area": rec["area"],
            "confidence": rec["confidence"],
            "bbox": [
                int(xx.min()) if xx.size else 0,
                int(yy.min()) if yy.size else 0,
                int(xx.max() + 1) if xx.size else 0,
                int(yy.max() + 1) if yy.size else 0,
            ],
            "status": "masked",
        }
        rec["selected_object_id"] = oid
        objects.append(obj)
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
            "processor_threshold_policy": "model_default",
            "selection_policy": "all_returned_masks",
            "prompt_count": len(prompts),
            "returned_mask_count": len(objects),
            "mask_resolution": list(image.size),
            "detections": detections,
        },
    )
    meta.setdefault("execution", {})["baseline_policy"] = "default_model_outputs_unfiltered_v1"
    meta["objects"] = objects
    meta["timing"]["segmentation_seconds"] = time.monotonic() - start
    meta["pipeline"]["vision_torch"] = torch.__version__
    write(run / "scene_metadata.json", meta)
    if not objects:
        raise RuntimeError(
            "SAM3 returned no masks for the RAM++ prompts"
        )
    status(
        run, "segmented", f"Generated {len(objects)} instance masks", total=len(objects)
    )


if __name__ == "__main__":
    run_scene(Path(sys.argv[1]).resolve())
