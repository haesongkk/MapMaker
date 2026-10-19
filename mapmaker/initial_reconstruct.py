"""Official SAM3D reconstruction; optional resident worker avoids repeated model loads."""

from pathlib import Path
import contextlib, gc, json, sys, time, traceback
from .scene_run import ROOT, SAM3D_REPO, write, read, sha, status
from .runtime_paths import SAM3D_CHECKPOINT, DINO_PROVENANCE

def run_scene(run):
    import numpy as np
    from PIL import Image

    run = Path(run)
    meta = read(run / "scene_metadata.json")
    start = time.monotonic()
    status(run, "loading", "Preparing SAM3D model...")
    import torch
    from .reconstruction_runtime import prepare
    MODEL, load_image = prepare()
    meta["timing"]["reconstruction_model_ready_seconds"] = time.monotonic() - start
    image = load_image(str(run / meta["input_image"]))
    outputs = []
    successful = []
    start = time.monotonic()
    for index, obj in enumerate(meta["objects"]):
        status(
            run,
            "reconstructing",
            f"Reconstructing objects {index + 1}/{len(meta['objects'])}...",
            current=index + 1,
            total=len(meta["objects"]),
            object_id=obj["id"],
        )
        t = time.monotonic()
        try:
            mask = np.asarray(Image.open(run / obj["mask"])) > 0
            assert sha(run / obj["mask"]) == obj["mask_sha256"]
            result = MODEL(image, mask, seed=42)
            if result.get("glb") is None:
                raise RuntimeError("SAM3D returned no mesh")
            obj["asset"] = f"objects/{obj['id']}.glb"
            result["glb"].export(str(run / obj["asset"]))
            obj["pose"] = {
                k: result[k].detach().cpu().tolist()
                for k in ("rotation", "translation", "scale")
            }
            write(run / "objects" / f"{obj['id']}.pose.json", obj["pose"])
            obj["status"] = "generated"
            obj["asset_sha256"] = sha(run / obj["asset"])
            successful.append(obj)
            outputs.append(
                {k: result[k] for k in ("gaussian", "rotation", "translation", "scale")}
            )
            del result
        except Exception as exc:
            obj["status"] = "failed"
            obj["error"] = str(exc)
            meta["errors"].append(
                {"stage": "reconstruction", "object": obj["id"], "error": str(exc)}
            )
            traceback.print_exc()
        obj["reconstruction_seconds"] = time.monotonic() - t
        write(run / "scene_metadata.json", meta)
        gc.collect()
        torch.cuda.empty_cache()
    meta["timing"]["object_reconstruction_seconds"] = time.monotonic() - start
    from .reconstruction_output import export_inference
    export_inference(run, meta, successful, outputs)
    del outputs, image
    gc.collect()
    torch.cuda.empty_cache()

