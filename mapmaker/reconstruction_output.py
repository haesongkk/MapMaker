"""Shared assembly, official preview and provenance for both inference modes."""
import os, sys, time, traceback
from .scene_run import read, write, sha, status
from .runtime_paths import SAM3D_CHECKPOINT, DINO_PROVENANCE

def export_inference(run, meta, successful, outputs, *, maximum_retries=None, baseline=False):
    import torch
    if not successful:
        raise RuntimeError("No objects reconstructed; inspect logs/reconstruction.log")
    start = time.monotonic()
    status(run, "assembling", "Assembling scene with original SAM3D poses...")
    if baseline:
        from .baseline_assembly import assemble_streamed
        meta['assembly'] = assemble_streamed(run, successful)
        meta['timing']['assembly_seconds'] = time.monotonic() - start
        meta['preview_method'] = 'saved GLB web viewer; no Gaussian aggregation'
    else:
        from inference import make_scene, ready_gaussian_for_video_rendering, render_video
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
    if maximum_retries is not None:
        meta["pipeline"].update(reconstruction_candidate_seeds=[42,43],
            reconstruction_seed_policy=f"base 42; at most {maximum_retries} scene-wide alternatives 43; selected seed recorded per object")
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
