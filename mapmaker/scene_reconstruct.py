"""Official SAM3D reconstruction; optional resident worker avoids repeated model loads."""

from pathlib import Path
import contextlib, gc, json, sys, time, traceback
from .scene_run import ROOT, SAM3D_REPO, write, read, sha, status
from .runtime_paths import SAM3D_CHECKPOINT, DINO_PROVENANCE

MODEL = None


def run_scene(run):
    global MODEL
    import numpy as np
    from PIL import Image

    run = Path(run)
    meta = read(run / "scene_metadata.json")
    start = time.monotonic()
    status(run, "loading", "Preparing SAM3D model...")
    sys.path.insert(0, str(SAM3D_REPO / "notebook"))
    from inference import (
        Inference,
        load_image,
        make_scene,
        ready_gaussian_for_video_rendering,
        render_video,
    )
    import torch
    from loguru import logger

    torch.cuda.reset_peak_memory_stats()

    logger.remove()
    logger.add(sys.stderr)
    if MODEL is None:
        MODEL = Inference(
            str(SAM3D_CHECKPOINT), compile=False
        )
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
    if not successful:
        raise RuntimeError("No objects reconstructed; inspect logs/reconstruction.log")
    start = time.monotonic()
    status(run, "assembling", "Assembling scene with original SAM3D poses...")
    from .scene_assembly import assemble

    meta["assembly"] = assemble(run, successful)
    combined = make_scene(*outputs)
    combined.save_ply(str(run / "previews/scene_posed.ply"))
    meta["timing"]["assembly_seconds"] = time.monotonic() - start
    status(run, "exporting", "Exporting GLB and rendering preview...")
    try:
        import imageio.v2 as imageio

        display = ready_gaussian_for_video_rendering(combined)
        frames = render_video(display, r=2, fov=60, resolution=512, num_frames=12)[
            "color"
        ]
        for i in (0, 3, 6, 9):
            imageio.imwrite(run / "previews" / f"combined_view_{i:02d}.png", frames[i])
        imageio.imwrite(run / "previews/combined_preview.png", frames[0])
        meta["preview_method"] = (
            "official make_scene + ready_gaussian_for_video_rendering + render_video; display normalization only"
        )
        del display, frames
    except Exception as exc:
        meta["errors"].append({"stage": "gaussian_preview", "error": str(exc)})
        traceback.print_exc()
    meta["scene_asset"] = "scene.glb"
    meta["pipeline"].update(
        reconstruction_torch=torch.__version__,
        seed=42,
        compile=False,
        sam3d_source_revision="f91db411c50efee93d8db7aeb323885650f6f722",
        pipeline_sha256=sha(SAM3D_CHECKPOINT),
        dino=read(DINO_PROVENANCE),
    )
    write(run / "scene_metadata.json", meta)
    write(run / "logs/sam3d_gpu.json", {
        "gpu": torch.cuda.get_device_name(),
        "torch": torch.__version__, "cuda": torch.version.cuda,
        "python": sys.version,
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        "model_ready_seconds": meta["timing"]["reconstruction_model_ready_seconds"],
        "attention_environment": {k: __import__("os").environ.get(k)
                                  for k in ("ATTN_BACKEND", "SPCONV_ALGO")},
        "sdpa_enabled": {"flash": torch.backends.cuda.flash_sdp_enabled(),
                         "memory_efficient": torch.backends.cuda.mem_efficient_sdp_enabled(),
                         "math": torch.backends.cuda.math_sdp_enabled()},
        "note": "Enabled backends are recorded; actual dispatch must be checked against worker logs.",
    })
    del outputs, combined, image
    gc.collect()
    torch.cuda.empty_cache()


def serve():
    for line in sys.stdin:
        run = Path(json.loads(line)["run"]).resolve()
        with (
            (run / "logs/reconstruction.log").open("a", buffering=1) as log,
            contextlib.redirect_stdout(log),
            contextlib.redirect_stderr(log),
        ):
            try:
                run_scene(run)
                result = {"ok": True}
            except Exception as exc:
                traceback.print_exc()
                result = {"ok": False, "error": str(exc)}
        write(run / "logs/reconstruction_result.json", result)


if __name__ == "__main__":
    if sys.argv[1:] == ["--serve"]:
        serve()
    else:
        run_scene(Path(sys.argv[1]).resolve())
