from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .common import camera_matrix, image_to_points, write_json


def analyze(image_path: Path, output: Path, model_id: str = "Ruicheng/moge-2-vitl-normal") -> None:
    import torch
    from moge.model.v2 import MoGeModel

    image = np.asarray(Image.open(image_path).convert("RGB"))
    tensor = torch.from_numpy(image.copy()).permute(2, 0, 1).float().cuda() / 255
    model = MoGeModel.from_pretrained(model_id).cuda().eval()
    with torch.inference_mode():
        result = model.infer(tensor)
    depth = result["depth"].float().cpu().numpy()
    normalized_k = result["intrinsics"].float().cpu().numpy()
    valid = result["mask"].cpu().numpy().astype(bool)
    normals = result.get("normal")
    k = camera_matrix(normalized_k, image.shape[1], image.shape[0])
    points = image_to_points(depth, k)
    output.mkdir(parents=True, exist_ok=True)
    np.save(output / "depth.npy", depth)
    np.save(output / "points.npy", points)
    np.save(output / "valid.npy", valid)
    if normals is not None:
        np.save(output / "normals.npy", normals.float().cpu().numpy())
    write_json(output / "camera.json", {"width": image.shape[1], "height": image.shape[0],
                                        "K": k.tolist(), "world_to_camera": np.eye(4).tolist(),
                                        "coordinate_system": "opencv_x_right_y_down_z_forward",
                                        "depth_units": "model_estimated_meters", "model": model_id})
    # The preview is visual only. Numeric depth remains in depth.npy.
    finite = depth[valid & np.isfinite(depth)]
    if len(finite):
        lo, hi = np.quantile(finite, [0.02, 0.98])
        preview = np.uint8(np.clip((depth - lo) / max(hi-lo, 1e-5), 0, 1) * 255)
        cv2.imwrite(str(output / "depth_preview.png"), preview)


def run_gen3c(image_path: Path, output: Path, repo: Path, checkpoint_dir: Path,
              python: str = sys.executable, distance: float = 1.0, angle: float = 90.0) -> None:
    image_path = image_path.resolve()
    output = output.resolve()
    repo = repo.resolve()
    checkpoint_dir = checkpoint_dir.resolve()
    python = os.path.abspath(python)
    output.mkdir(parents=True, exist_ok=True)
    if not (checkpoint_dir / "Gen3C-Cosmos-7B/model.pt").is_file():
        raise FileNotFoundError(f"GEN3C model checkpoint missing under: {checkpoint_dir}")
    script = repo / "cosmos_predict1/diffusion/inference/gen3c_single_image.py"
    if not script.exists():
        raise FileNotFoundError(f"GEN3C checkout missing: {script}")
    from .gen3c_patch import patch
    patch(repo)
    for direction in ("left", "right"):
        video_file = output / f"{direction}.mp4"
        pose_file = output / f"{direction}_w2c.npy"
        if not video_file.exists():
            args = [python, str(script), "--checkpoint_dir", str(checkpoint_dir),
                    "--input_image_path", str(image_path), "--video_save_folder", str(output),
                    "--video_save_name", direction, "--trajectory", "side_" + direction,
                    "--camera_rotation", "center_facing", "--movement_distance", str(distance),
                    "--side_angle_deg", str(angle), "--camera_poses_output", str(pose_file),
                    "--num_video_frames", "121", "--guidance", "1", "--foreground_masking"]
            env = os.environ.copy()
            env["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
            env["PYTHONPATH"] = str(repo) + os.pathsep + env.get("PYTHONPATH", "")
            subprocess.run(args, cwd=repo, env=env, check=True)
        if not (output / f"{direction}.mp4").exists():
            raise RuntimeError(f"GEN3C did not produce {direction}.mp4")
        if not pose_file.exists():
            raise RuntimeError(f"GEN3C did not export {pose_file}")
        capture = cv2.VideoCapture(str(video_file))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        capture.release()
        if frame_count != len(np.load(pose_file)):
            raise RuntimeError(f"GEN3C frame/pose count mismatch for {direction}: {frame_count}")
        intrinsics_file = output / f"{direction}_K.npy"
        if not intrinsics_file.exists():
            intrinsics_script = Path(__file__).with_name("gen3c_intrinsics.py")
            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo) + os.pathsep + env.get("PYTHONPATH", "")
            subprocess.run([python, str(intrinsics_script), "--image", str(image_path),
                            "--video", str(video_file), "--frames", "121",
                            "--output", str(intrinsics_file)], cwd=repo, env=env, check=True)


def extract_frames(video: Path, output: Path, every: int = 12) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot read video: {video}")
    selected = []
    index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if index % every == 0:
            path = output / f"{index:04d}.png"
            cv2.imwrite(str(path), frame)
            selected.append(path)
        index += 1
    capture.release()
    if not selected:
        raise RuntimeError(f"Video contains no frames: {video}")
    return selected


def ram_tags(images: list[Path], checkpoint: Path, device: str = "cuda") -> dict[str, list[str]]:
    if not checkpoint.is_file():
        raise FileNotFoundError(f"RAM++ checkpoint missing: {checkpoint}")
    import torch
    from ram import get_transform, inference_ram
    from ram.models import ram_plus

    model = ram_plus(pretrained=str(checkpoint), image_size=384, vit="swin_l")
    model = model.eval().to(device)
    transform = get_transform(image_size=384)
    found = {}
    with torch.inference_mode():
        for path in images:
            result = inference_ram(transform(Image.open(path).convert("RGB")).unsqueeze(0).to(device), model)
            found[str(path)] = sorted({tag.strip().lower() for tag in result[0].split("|") if tag.strip()})
    return found


def sam_video(video: Path, labels: list[str], output: Path) -> dict:
    from sam3.model_builder import build_sam3_video_predictor

    output.mkdir(parents=True, exist_ok=True)
    predictor = build_sam3_video_predictor()
    results = {}
    for label in labels:
        # One session per concept preserves its instance IDs and label association.
        session = predictor.handle_request(request={"type": "start_session", "resource_path": str(video)})
        session_id = session["session_id"]
        label_dir = output / label.replace("/", "_")
        try:
            response = predictor.handle_request(request={"type": "add_prompt", "session_id": session_id,
                                                         "frame_index": 0, "text": label})
            summary = _store_sam_response(response, label_dir)
            for response in predictor.handle_stream_request(
                    request={"type": "propagate_in_video", "session_id": session_id}):
                frame_summary = _store_sam_response(response, label_dir)
                for obj_id, frames in frame_summary.items():
                    summary.setdefault(obj_id, []).extend(frames)
            results[label] = {key: sorted(set(value)) for key, value in summary.items()}
        finally:
            predictor.handle_request(request={"type": "close_session", "session_id": session_id})
    return results


def _store_sam_response(response: dict, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    summary = {}
    item = response.get("outputs", response)
    frame = int(response.get("frame_index", 0))
    masks = item.get("out_binary_masks", [])
    ids = item.get("out_obj_ids", range(len(masks)))
    for obj_id, mask in zip(ids, masks):
        if hasattr(mask, "detach"):
            mask = mask.detach().cpu().numpy()
        mask = np.squeeze(np.asarray(mask)).astype(bool)
        if mask.ndim != 2:
            continue
        target = output / str(int(obj_id))
        target.mkdir(exist_ok=True)
        Image.fromarray(np.uint8(mask)*255).save(target / f"{frame:04d}.png")
        summary.setdefault(str(int(obj_id)), []).append(frame)
    return summary


def hunyuan_mesh(views: dict[str, Path], output: Path, seed: int = 12345) -> None:
    import torch
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
    from hy3dgen.texgen import Hunyuan3DPaintPipeline

    images = {key: Image.open(path).convert("RGBA") for key, path in views.items()}
    if len(images) > 1:
        shape = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            "tencent/Hunyuan3D-2mv", subfolder="hunyuan3d-dit-v2-mv", variant="fp16")
        mesh = shape(image=images, num_inference_steps=50, octree_resolution=380,
                     generator=torch.manual_seed(seed), output_type="trimesh")[0]
    else:
        shape = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            "tencent/Hunyuan3D-2", subfolder="hunyuan3d-dit-v2-0", variant="fp16")
        mesh = shape(image=images["front"], num_inference_steps=50,
                     generator=torch.manual_seed(seed), output_type="trimesh")[0]
    output.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(output.with_suffix(".shape.glb"))
    if len(mesh.faces) > 40000:
        mesh = mesh.simplify_quadric_decimation(face_count=40000)
    import gc
    del shape
    gc.collect()
    torch.cuda.empty_cache()
    paint = Hunyuan3DPaintPipeline.from_pretrained("tencent/Hunyuan3D-2")
    mesh = paint(mesh, image=images["front"])
    mesh.export(output)


def hunyuan_meshes(jobs: list[dict], seed: int = 12345) -> None:
    """Generate several front-view meshes while loading each Hunyuan model once."""
    import gc
    import torch
    import trimesh
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
    from hy3dgen.texgen import Hunyuan3DPaintPipeline

    pending = [(Path(job["views"]["front"]), Path(job["output"]))
               for job in jobs if not Path(job["output"]).exists()]
    if not pending:
        return
    missing_shapes = [(front, output) for front, output in pending
                      if not output.with_suffix(".shape.glb").exists()]
    if missing_shapes:
        shape = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            "tencent/Hunyuan3D-2", subfolder="hunyuan3d-dit-v2-0", variant="fp16")
        for front, output in missing_shapes:
            mesh = shape(image=Image.open(front).convert("RGBA"), num_inference_steps=50,
                         generator=torch.manual_seed(seed), output_type="trimesh")[0]
            output.parent.mkdir(parents=True, exist_ok=True)
            mesh.export(output.with_suffix(".shape.glb"))
            del mesh
        del shape
        gc.collect()
        torch.cuda.empty_cache()
    paint = Hunyuan3DPaintPipeline.from_pretrained("tencent/Hunyuan3D-2")
    for front, output in pending:
        if output.exists():
            continue
        mesh = trimesh.load(output.with_suffix(".shape.glb"), force="mesh")
        if len(mesh.faces) > 40000:
            mesh = mesh.simplify_quadric_decimation(face_count=40000)
        mesh = paint(mesh, image=Image.open(front).convert("RGBA"))
        mesh.export(output)
        del mesh
        gc.collect()
        torch.cuda.empty_cache()
