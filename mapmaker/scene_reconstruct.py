"""Official SAM3D reconstruction; optional resident worker avoids repeated model loads."""

from pathlib import Path
import contextlib, gc, json, os, shutil, sys, time, traceback
from .scene_run import ROOT, SAM3D_REPO, write, read, sha, status
from .runtime_paths import SAM3D_CHECKPOINT, DINO_PROVENANCE

MODEL = None


def finish_scene(run, *, inference_checkpoint=False, store=None):
    """Persist inference in the reconstruction process BEFORE its heavy checks."""
    if inference_checkpoint:
        import tempfile
        from .scene_transfer import ArtifactStore, pack_run
        store = store or ArtifactStore()
        status(run, 'exporting', 'Saving inference before geometry checks...')
        with tempfile.TemporaryDirectory(prefix='.inference-', dir=run.parent) as tmp:
            archive = Path(tmp) / 'inference.zip'
            pack_run(run, archive)
            store.upload_inference_checkpoint(run.name, archive, read(run / 'scene_metadata.json'))
    from .scene_placement import finalize_scene
    status(run, 'exporting', 'Checking geometry and observed room surfaces...')
    finalize_scene(run, render=False)


def run_scene(run, *, inference_checkpoint=False):
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
    # Compute one full-image pointmap for both object layout and room geometry.
    # This adapter targets the pinned SAM3D revision recorded below.
    rgba = MODEL.merge_mask_to_rgba(image, np.ones(image.shape[:2], dtype=bool))
    with torch.no_grad(), MODEL._pipeline.device:
        pointmap_data = MODEL._pipeline.compute_pointmap(rgba)
    shared_pointmap = pointmap_data['pointmap'].permute(1, 2, 0).contiguous()
    np.savez_compressed(run / 'input/pointmap.npz', points=shared_pointmap.detach().cpu().float().numpy())
    meta['pointmap'] = dict(asset='input/pointmap.npz', sha256=sha(run/'input/pointmap.npz'),
        frame='sam3d_pytorch3d_camera', source='SAM3D full-image compute_pointmap',
        shared_with_object_layout=True, metric_scale_verified=False)
    from .mask_geometry import refine_selected
    refine_selected(run, meta, shared_pointmap.detach().cpu().float().numpy(), image)
    write(run / 'scene_metadata.json', meta)
    outputs = []
    successful = []
    from .reconstruction_review import reconstruct_with_review
    from .reconstruction_evidence import assess, candidate_faces
    from .scene_assembly import object_matrix
    points_cpu = shared_pointmap.detach().cpu().float().numpy()
    visible_depth_review = os.environ.get('MAPMAKER_VISIBLE_DEPTH_REVIEW') == '1'
    # The experimental visible-depth policy measures every baseline first.
    # A hash merely breaks evidence ties; it must not consume the retry budget.
    retry_budget = {'remaining': 0 if visible_depth_review else 1}
    maximum_retries = 2 if visible_depth_review else 1
    meta['reconstruction_review'] = dict(maximum_extra_inferences=maximum_retries,
        seeds=[42,43], uses_object_names=False,
        order='descending_visible_depth_error_then_mask_sha256' if visible_depth_review else 'mask_sha256',
        visible_depth=visible_depth_review,
        limitation='Visible evidence selection only; unseen shape and scene interactions require final validation')
    start = time.monotonic()
    for index, obj in enumerate(sorted(meta["objects"], key=lambda o: o.get('mask_sha256', ''))):
        if obj['status'] in ('duplicate', 'structural'):
            continue
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
            def pose_of(candidate):
                return {k: candidate[k].detach().cpu().tolist()
                        for k in ('rotation','translation','scale')}
            def measure(candidate, target_mask=None):
                target_mask = mask if target_mask is None else target_mask
                matrix = object_matrix(pose_of(candidate))
                faces = candidate_faces(candidate['glb'], matrix)
                resized = np.asarray(Image.fromarray(target_mask).resize(
                    points_cpu.shape[:2][::-1], Image.Resampling.NEAREST)) > 0
                return assess(faces, points_cpu, resized, visible_depth=visible_depth_review)
            def preserve(candidate, seed):
                relative = f"objects/candidates/{obj['id']}/seed_{seed}.glb"
                path = run/relative
                path.parent.mkdir(parents=True, exist_ok=True)
                if seed == 42 and visible_depth_review and obj.get('status') == 'generated':
                    shutil.copyfile(run/obj['asset'], path)
                else:
                    candidate['glb'].export(str(path))
                pose_path = path.with_suffix('.pose.json')
                write(pose_path, pose_of(candidate))
                return dict(asset=relative, sha256=sha(path),
                    pose=pose_path.relative_to(run).as_posix(), pose_sha256=sha(pose_path))
            result, obj['reconstruction_review'] = reconstruct_with_review(
                lambda seed, source_image=image, source_points=shared_pointmap:
                    MODEL(source_image, mask, seed=seed, pointmap=source_points),
                measure, preserve, retry_budget)
            obj["asset"] = f"objects/{obj['id']}.glb"
            review = obj['reconstruction_review']
            selected_artifact = review.get('alternative_artifact' if review['selected_seed']==43 else 'original_artifact')
            if selected_artifact:
                shutil.copyfile(run/selected_artifact['asset'], run/obj['asset'])
            else:
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
        meta['reconstruction_review']['extra_inferences_used'] = 0 if visible_depth_review else 1-retry_budget['remaining']
        write(run / "scene_metadata.json", meta)
        gc.collect()
        torch.cuda.empty_cache()
    if visible_depth_review and successful:
        from .reconstruction_deferred import review_ranked_scene
        from .reconstruction_context import SavedContactContext
        review_ranked_scene(run, meta, successful, outputs,
            lambda obj, target_mask, seed: MODEL(image, target_mask, seed=seed, pointmap=shared_pointmap),
            measure, pose_of, context_guard=SavedContactContext(run,successful,pose_of),
            progress=lambda obj, total: status(run, 'reconstructing',
                'Reviewing geometry-ranked reconstruction alternatives...', object_id=obj['id'], total=total))
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
        reconstruction_candidate_seeds=[42,43],
        reconstruction_seed_policy=f'base 42; at most {maximum_retries} scene-wide alternatives 43; selected seed recorded per object',
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
    del outputs, combined, image, shared_pointmap, pointmap_data
    gc.collect()
    torch.cuda.empty_cache()
    # The pinned SAM3D environment includes scipy/rtree. Finalize here so an
    # application-only release does not depend on upgrading the controller venv.
    # The controller's later finalize call verifies the hash and is idempotent.
    finish_scene(run, inference_checkpoint=inference_checkpoint)


def serve():
    for line in sys.stdin:
        request = json.loads(line)
        run = Path(request["run"]).resolve()
        with (
            (run / "logs/reconstruction.log").open("a", buffering=1) as log,
            contextlib.redirect_stdout(log),
            contextlib.redirect_stderr(log),
        ):
            try:
                run_scene(run, inference_checkpoint=request.get('inference_checkpoint') is True)
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
