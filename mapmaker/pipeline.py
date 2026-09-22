from __future__ import annotations

import json
import re
from pathlib import Path

import cv2
import numpy as np
import trimesh
from PIL import Image

from .common import normalize_image, read_json, write_json
from .geometry import fit_plane, initial_transform, make_depth_mesh, refine_transform_to_mask
from .models import analyze, extract_frames, hunyuan_mesh, ram_tags, run_gen3c, sam_video


STOP_WORDS = {"room", "home", "indoor", "outdoor", "floor", "wall", "ceiling", "sky",
              "gray", "green", "brown", "white", "black", "red", "blue", "wood", "metal",
              "sitting", "standing", "lay", "photo", "picture", "image",
              "apartment", "living room", "furniture", "modern", "slide", "glass door",
              "carpet", "window", "flat"}
SYNONYMS = {"sofa": "couch", "settee": "couch", "seat": "chair", "desk": "table"}


class Pipeline:
    def __init__(self, source: Path, workdir: Path):
        self.source = Path(source).resolve()
        self.workdir = Path(workdir).resolve()
        self.workdir.mkdir(parents=True, exist_ok=True)
        if not self.source.is_file():
            raise FileNotFoundError(self.source)

    def original(self, force: bool = False, moge_python: str | None = None) -> None:
        image = self.workdir / "input.png"
        analysis = self.workdir / "analysis"
        if force or not (analysis / "camera.json").exists():
            metadata = normalize_image(self.source, image)
            write_json(analysis / "input.json", metadata)
            if moge_python:
                import os
                import subprocess
                env = os.environ.copy()
                project_root = str(Path(__file__).resolve().parent.parent)
                env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
                subprocess.run([moge_python, "-m", "mapmaker.moge_worker",
                                str(image), str(analysis)], env=env, check=True)
            else:
                analyze(image, analysis)
            pts = np.load(analysis / "points.npy")
            valid = np.load(analysis / "valid.npy")
            h = valid.shape[0]
            lower = valid.copy()
            lower[:h//2] = False
            plane = fit_plane(pts[lower][::max(1, lower.sum()//20000)])
            write_json(analysis / "planes.json", {"ground_candidate": plane})

    def views(self, gen3c_repo: Path, checkpoints: Path, python: str, force: bool = False,
              distance: float = 0.15) -> None:
        video_dir = self.workdir / "videos"
        if force:
            for direction in ("clockwise", "counterclockwise"):
                for suffix in (".mp4", "_w2c.npy", "_K.npy"):
                    (video_dir / f"{direction}{suffix}").unlink(missing_ok=True)
        run_gen3c(self.workdir / "input.png", video_dir, gen3c_repo, checkpoints, python, distance)
        for direction in ("clockwise", "counterclockwise"):
            extract_frames(video_dir / f"{direction}.mp4", self.workdir / "frames" / direction)
        # Keep source frame at index 0; generated frames are distinct observations.
        target = self.workdir / "frames/original/0000.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes((self.workdir / "input.png").read_bytes())
        pose_files = {direction: str(video_dir / f"{direction}_w2c.npy")
                      for direction in ("clockwise", "counterclockwise")}
        intrinsics_files = {direction: str(video_dir / f"{direction}_K.npy")
                            for direction in ("clockwise", "counterclockwise")}
        if not all(Path(path).exists() for path in [*pose_files.values(), *intrinsics_files.values()]):
            raise RuntimeError("GEN3C camera matrices export is missing")
        write_json(self.workdir / "frames/manifest.json", {
            "original": str(target), "directions": ["clockwise", "counterclockwise"],
            "frame_interval": 12, "world_to_camera": pose_files,
            "intrinsics": intrinsics_files})

    def candidates(self, ram_checkpoint: Path, vision_python: str | None = None) -> list[str]:
        images = [self.workdir / "input.png"]
        for direction in ("clockwise", "counterclockwise"):
            frames = sorted((self.workdir / "frames" / direction).glob("*.png"))
            images.extend(frames[1::3])
        if vision_python:
            image_list = self.workdir / "candidate_frames.json"
            tags_file = self.workdir / "candidate_tags.json"
            write_json(image_list, [str(path) for path in images])
            _run_worker(vision_python, ["ram", "--images", str(image_list),
                                        "--checkpoint", str(ram_checkpoint),
                                        "--output", str(tags_file)])
            tags = read_json(tags_file)
        else:
            tags = ram_tags(images, ram_checkpoint)
        names = sorted({SYNONYMS.get(tag, tag) for frame_tags in tags.values() for tag in frame_tags
                        if tag not in STOP_WORDS and len(tag) > 2})
        write_json(self.workdir / "candidates.json", {"tags_by_frame": tags, "labels": names})
        return names

    def segment(self, vision_python: str | None = None) -> None:
        labels = read_json(self.workdir / "candidates.json")["labels"]
        # Run each generated direction independently. The original is segmented on both first frames.
        for direction in ("clockwise", "counterclockwise"):
            video = self.workdir / "videos" / f"{direction}.mp4"
            mask_dir = self.workdir / "masks" / direction
            summary = self.workdir / "masks" / f"{direction}.json"
            if vision_python:
                labels_file = self.workdir / "labels.json"
                write_json(labels_file, labels)
                _run_worker(vision_python, ["sam", "--video", str(video),
                                            "--labels", str(labels_file),
                                            "--output", str(mask_dir), "--summary", str(summary)])
            else:
                write_json(summary, sam_video(video, labels, mask_dir))

    def select_views(self) -> list[dict]:
        objects = []
        source = np.asarray(Image.open(self.workdir / "input.png").convert("RGB"))
        tags_file = self.workdir / "candidate_tags.json"
        original_tags = set(read_json(tags_file).get(str(self.workdir / "input.png"), [])) if tags_file.exists() else set()
        for direction in ("clockwise", "counterclockwise"):
            root = self.workdir / "masks" / direction
            video = cv2.VideoCapture(str(self.workdir / "videos" / f"{direction}.mp4"))
            poses = np.load(self.workdir / "videos" / f"{direction}_w2c.npy")
            if not video.isOpened():
                raise RuntimeError(f"Cannot read {direction} video")
            label_dirs = sorted(root.iterdir() if root.exists() else [],
                                key=lambda path: (path.name not in original_tags, path.name))
            for label_dir in label_dirs:
                if not label_dir.is_dir():
                    continue
                for instance in sorted(label_dir.iterdir()):
                    if not instance.is_dir():
                        continue
                    masks = sorted(instance.glob("*.png"))
                    initial = instance / "0000.png"
                    if len(masks) < 12 or not initial.exists():
                        continue  # Only objects visible in the original image are anchored.
                    anchor = np.asarray(Image.open(initial).convert("L")) > 127
                    anchor = cv2.resize(anchor.astype(np.uint8), (source.shape[1], source.shape[0]),
                                        interpolation=cv2.INTER_NEAREST).astype(bool)
                    if anchor.sum() < 100 or anchor.mean() > 0.8:
                        continue
                    # The two trajectories start from the same source. Merge matching instances.
                    match = None
                    for existing in objects:
                        other = np.asarray(Image.open(existing["anchor_mask"]).convert("L")) > 127
                        intersection = np.logical_and(anchor, other).sum()
                        union = np.logical_or(anchor, other).sum()
                        threshold = 0.55 if existing["label"] == label_dir.name else 0.75
                        if union and intersection / union > threshold:
                            match = existing
                            if label_dir.name != existing["label"]:
                                aliases = existing.setdefault("aliases", [])
                                if label_dir.name not in aliases:
                                    aliases.append(label_dir.name)
                            break
                    if match is None:
                        obj_id = f"obj_{len(objects):04d}_{_safe(label_dir.name)}"
                        view_dir = self.workdir / "object_views" / obj_id
                        view_dir.mkdir(parents=True, exist_ok=True)
                        anchor_path = view_dir / "anchor_mask.png"
                        Image.fromarray(anchor.astype(np.uint8)*255).save(anchor_path)
                        match = {"id": obj_id, "label": label_dir.name, "anchor_mask": str(anchor_path),
                                 "views": [], "observations": []}
                        objects.append(match)
                    view_dir = self.workdir / "object_views" / match["id"]
                    if not match["views"]:
                        front = _crop_rgba(source, anchor)
                        front_path = view_dir / "front.png"
                        Image.fromarray(front).save(front_path)
                        match["views"].append({"role": "front", "path": str(front_path),
                                               "direction": "original", "frame": 0})
                    scored = []
                    for mask_path in masks:
                        index = int(mask_path.stem)
                        if index < 12 or index > 72:
                            continue
                        mask = np.asarray(Image.open(mask_path).convert("L")) > 127
                        if mask.sum() < 100 or mask.mean() > 0.8:
                            continue
                        video.set(cv2.CAP_PROP_POS_FRAMES, index)
                        ok, frame = video.read()
                        if not ok:
                            continue
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        if frame.shape[:2] != mask.shape:
                            mask = cv2.resize(mask.astype(np.uint8), (frame.shape[1], frame.shape[0]),
                                              interpolation=cv2.INTER_NEAREST).astype(bool)
                        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
                        sharpness = float(cv2.Laplacian(gray, cv2.CV_32F).var())
                        anchor_area = float(anchor.sum()) * mask.size / anchor.size
                        visible_ratio = min(float(mask.sum()) / max(anchor_area, 1.0), 1.0)
                        score = visible_ratio * np.log1p(sharpness)
                        scored.append((score, index, mask, mask_path, frame, sharpness, visible_ratio))
                    # Pick a clear view from each half of the orbit to preserve angular spread.
                    selected = []
                    for lower, upper in ((12, 42), (43, 72)):
                        bucket = [item for item in scored if lower <= item[1] <= upper]
                        if bucket:
                            selected.append(max(bucket, key=lambda item: item[0]))
                    for score, index, mask, mask_path, frame, sharpness, visible_ratio in selected:
                        path = view_dir / f"{direction}_{index:04d}.png"
                        Image.fromarray(_crop_rgba(frame, mask)).save(path)
                        # Hunyuan 2mv expects canonical sides. Admit only a near-side camera.
                        forward = poses[index, 2, :3]
                        angle = float(np.degrees(np.arccos(np.clip(forward @ poses[0, 2, :3], -1, 1))))
                        side = "left" if direction == "clockwise" else "right"
                        role = side if 65 <= angle <= 115 else "oblique"
                        match["views"].append({"role": role, "path": str(path),
                                               "direction": direction, "frame": index,
                                               "camera_angle_deg": angle, "sharpness": sharpness,
                                               "visible_ratio": visible_ratio, "selection_score": score})
                        match["observations"].append({"direction": direction, "frame": index,
                                                      "mask": str(mask_path)})
            video.release()
        write_json(self.workdir / "objects.json", objects)
        return objects

    def meshes(self, hunyuan_python: str | None = None) -> None:
        objects = read_json(self.workdir / "objects.json")
        for obj in objects:
            target = self.workdir / "meshes" / f"{obj['id']}.glb"
            if target.exists():
                continue
            # GEN3C's short orbit produces oblique views, not canonical 90-degree sides.
            # Pass only geometrically valid canonical views to the 2mv model.
            views = {view["role"]: Path(view["path"]) for view in obj["views"]
                     if view["role"] in ("front", "left", "back", "right")}
            if hunyuan_python:
                views_file = self.workdir / "object_views" / obj["id"] / "hunyuan_views.json"
                write_json(views_file, {key: str(path) for key, path in views.items()})
                _run_worker(hunyuan_python, ["hunyuan", "--views", str(views_file),
                                             "--output", str(target)])
            else:
                hunyuan_mesh(views, target)

    def scene(self) -> Path:
        analysis = self.workdir / "analysis"
        rgb = np.asarray(Image.open(self.workdir / "input.png").convert("RGB"))
        points = np.load(analysis / "points.npy")
        valid = np.load(analysis / "valid.npy")
        objects = read_json(self.workdir / "objects.json")
        intrinsics = np.asarray(read_json(analysis / "camera.json")["K"], dtype=float)
        scene = trimesh.Scene()
        gltf_from_opencv = np.diag([1.0, -1.0, -1.0, 1.0])
        exclusion = np.zeros(valid.shape, dtype=bool)
        placed = []
        for obj in objects:
            mesh_path = self.workdir / "meshes" / f"{obj['id']}.glb"
            if not mesh_path.exists():
                continue
            mask = np.asarray(Image.open(obj["anchor_mask"]).convert("L")) > 127
            if mask.shape != valid.shape:
                mask = cv2.resize(mask.astype(np.uint8), (valid.shape[1], valid.shape[0]),
                                  interpolation=cv2.INTER_NEAREST).astype(bool)
            mesh_scene = trimesh.load(mesh_path, force="scene")
            joined = mesh_scene.to_geometry()
            if not isinstance(joined, trimesh.Trimesh):
                continue
            try:
                transform = initial_transform(joined, points, mask & valid)
                transform, placement_iou, fit_method = refine_transform_to_mask(
                    joined, points, mask, intrinsics, transform)
            except ValueError:
                continue
            gltf_transform = gltf_from_opencv @ transform
            scene.add_geometry(joined, node_name=obj["id"], transform=gltf_transform)
            exclusion |= mask
            placed.append({"id": obj["id"], "label": obj["label"],
                           "mesh": str(mesh_path), "anchor_mask": obj["anchor_mask"],
                           "transform": gltf_transform.tolist(),
                           "source_transform": transform.tolist(),
                           "placement_iou": placement_iou, "fit_method": fit_method})
        background = make_depth_mesh(rgb, points, valid, exclusion)
        scene.add_geometry(background, node_name="observed_background",
                           transform=gltf_from_opencv)
        target = self.workdir / "scene.glb"
        scene.export(target)
        write_json(self.workdir / "scene.json", {"camera": read_json(analysis / "camera.json"),
                                                  "objects": placed, "background": "observed_depth_mesh",
                                                  "gltf_from_opencv": gltf_from_opencv.tolist()})
        from .validation import validate_scene
        validate_scene(self.workdir)
        return target


def _safe(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_")[:64]


def _crop_rgba(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    ys, xs = np.where(mask)
    if not len(xs):
        raise ValueError("Empty object mask")
    margin = max(8, int(max(xs.max()-xs.min(), ys.max()-ys.min()) * 0.08))
    x0, x1 = max(0, xs.min()-margin), min(image.shape[1], xs.max()+margin+1)
    y0, y1 = max(0, ys.min()-margin), min(image.shape[0], ys.max()+margin+1)
    return np.dstack((image, mask.astype(np.uint8)*255))[y0:y1, x0:x1]


def _run_worker(python: str, args: list[str]) -> None:
    import os
    import subprocess
    env = os.environ.copy()
    project_root = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run([python, "-m", "mapmaker.model_worker", *args], env=env, check=True)
