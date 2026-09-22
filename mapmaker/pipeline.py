from __future__ import annotations

import shutil
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .common import normalize_image, read_json, write_json
from .geometry import fit_plane
from .models import (
    analyze,
    extract_frames,
    hunyuan_mesh,
    ram_tags,
    run_gen3c,
    sam_video,
)


STOP_WORDS = {
    "room",
    "home",
    "indoor",
    "outdoor",
    "floor",
    "wall",
    "ceiling",
    "sky",
    "gray",
    "green",
    "brown",
    "white",
    "black",
    "red",
    "blue",
    "wood",
    "metal",
    "sitting",
    "standing",
    "lay",
    "photo",
    "picture",
    "image",
    "apartment",
    "living room",
    "furniture",
    "modern",
    "slide",
    "glass door",
    "carpet",
    "window",
    "flat",
}
SYNONYMS = {"sofa": "couch", "settee": "couch", "seat": "chair", "desk": "table"}


class Pipeline:
    def __init__(self, source: Path, workdir: Path):
        self.source = Path(source).resolve()
        self.workdir = Path(workdir).resolve()
        self.workdir.mkdir(parents=True, exist_ok=True)
        if not self.source.is_file():
            raise FileNotFoundError(self.source)

    def _invalidate(self):
        for name in (
            "analysis",
            "videos",
            "frames",
            "masks",
            "object_views",
            "source_objects",
            "meshes",
            "accepted_meshes",
            "sofa_scene_accepted_meshes",
            "mesh_inspection",
            "object_review",
            "standalone_check",
        ):
            shutil.rmtree(self.workdir / name, ignore_errors=True)
        for pattern in (
            "scene*",
            "sofa_scene*",
            "validation*",
            "objects.json",
            "candidate*.json",
            "labels.json",
            "hunyuan_jobs.json",
            "mesh_review.json",
        ):
            for path in self.workdir.glob(pattern):
                if path.is_file():
                    path.unlink()

    def original(self, force: bool = False, moge_python: str | None = None) -> None:
        image = self.workdir / "input.png"
        analysis = self.workdir / "analysis"
        input_meta = analysis / "input.json"
        import hashlib

        source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        source_changed = (
            not input_meta.exists()
            or read_json(input_meta).get("source_sha256") != source_hash
            or read_json(input_meta).get("source") != str(self.source)
            or read_json(input_meta).get("source_mtime_ns")
            != self.source.stat().st_mtime_ns
        )
        if force or source_changed or not (analysis / "camera.json").exists():
            self._invalidate()
            import uuid

            write_json(
                self.workdir / "run_manifest.json",
                {
                    "run_id": str(uuid.uuid4()),
                    "source": str(self.source),
                    "source_sha256": source_hash,
                    "artifact_policy": "fresh_analysis_and_all_downstream_artifacts",
                },
            )
            metadata = normalize_image(self.source, image)
            metadata["source_sha256"] = source_hash
            write_json(analysis / "input.json", metadata)
            if moge_python:
                import os
                import subprocess

                env = os.environ.copy()
                project_root = str(Path(__file__).resolve().parent.parent)
                env["PYTHONPATH"] = (
                    project_root + os.pathsep + env.get("PYTHONPATH", "")
                )
                subprocess.run(
                    [
                        moge_python,
                        "-m",
                        "mapmaker.moge_worker",
                        str(image),
                        str(analysis),
                    ],
                    env=env,
                    check=True,
                )
            else:
                analyze(image, analysis)
            pts = np.load(analysis / "points.npy")
            valid = np.load(analysis / "valid.npy")
            h = valid.shape[0]
            lower = valid.copy()
            lower[: h // 2] = False
            plane = fit_plane(pts[lower][:: max(1, lower.sum() // 20000)])
            write_json(analysis / "planes.json", {"ground_candidate": plane})

    def views(
        self,
        gen3c_repo: Path,
        checkpoints: Path,
        python: str,
        force: bool = False,
        distance: float = 1.0,
        angle: float = 90.0,
    ) -> None:
        if not 0 < angle <= 90 or distance <= 0:
            raise ValueError("GEN3C requires 0 < angle <= 90 and distance > 0")
        video_dir = self.workdir / "videos"
        config = {
            "distance": distance,
            "angle": angle,
            "frames": 121,
            "trajectory_version": 2,
            "source": str(self.source),
            "source_mtime_ns": self.source.stat().st_mtime_ns,
        }
        config_path = video_dir / "config.json"
        changed = force or not config_path.exists() or read_json(config_path) != config
        if changed:
            for name in (
                "videos",
                "frames",
                "masks",
                "object_views",
                "source_objects",
                "meshes",
                "accepted_meshes",
                "sofa_scene_accepted_meshes",
                "mesh_inspection",
                "object_review",
                "standalone_check",
            ):
                shutil.rmtree(self.workdir / name, ignore_errors=True)
            for name in (
                "objects.json",
                "candidates.json",
                "candidate_tags.json",
                "candidate_frames.json",
                "scene.glb",
                "scene.json",
                "validation.json",
                "validation_render.png",
                "validation_overlay.png",
                "scene_comparison.png",
                "scene_glb_source.png",
                "scene_glb_yaw_12.png",
            ):
                (self.workdir / name).unlink(missing_ok=True)
            for pattern in ("scene*", "sofa_scene*", "validation*"):
                for path in self.workdir.glob(pattern):
                    if path.is_file():
                        path.unlink()
            video_dir.mkdir(parents=True, exist_ok=True)
        run_gen3c(
            self.workdir / "input.png",
            video_dir,
            gen3c_repo,
            checkpoints,
            python,
            distance,
            angle,
        )
        for direction in ("left", "right"):
            extract_frames(
                video_dir / f"{direction}.mp4",
                self.workdir / "frames" / direction,
                every=12,
            )
        # Keep source frame at index 0; generated frames are distinct observations.
        target = self.workdir / "frames/original/0000.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes((self.workdir / "input.png").read_bytes())
        pose_files = {
            direction: str(video_dir / f"{direction}_w2c.npy")
            for direction in ("left", "right")
        }
        intrinsics_files = {
            direction: str(video_dir / f"{direction}_K.npy")
            for direction in ("left", "right")
        }
        if not all(
            Path(path).exists()
            for path in [*pose_files.values(), *intrinsics_files.values()]
        ):
            raise RuntimeError("GEN3C camera matrices export is missing")
        write_json(config_path, config)
        write_json(
            self.workdir / "frames/manifest.json",
            {
                "original": str(target),
                "directions": ["left", "right"],
                "frame_interval": 12,
                "world_to_camera": pose_files,
                "intrinsics": intrinsics_files,
            },
        )

    def candidates(
        self, ram_checkpoint: Path, vision_python: str | None = None
    ) -> list[str]:
        images = [self.workdir / "input.png"]
        for direction in ("left", "right"):
            frames = sorted((self.workdir / "frames" / direction).glob("*.png"))
            images.extend(frames[1::3])
        if vision_python:
            image_list = self.workdir / "candidate_frames.json"
            tags_file = self.workdir / "candidate_tags.json"
            write_json(image_list, [str(path) for path in images])
            _run_worker(
                vision_python,
                [
                    "ram",
                    "--images",
                    str(image_list),
                    "--checkpoint",
                    str(ram_checkpoint),
                    "--output",
                    str(tags_file),
                ],
            )
            tags = read_json(tags_file)
        else:
            tags = ram_tags(images, ram_checkpoint)
        names = sorted(
            {
                SYNONYMS.get(tag, tag)
                for frame_tags in tags.values()
                for tag in frame_tags
                if tag not in STOP_WORDS and len(tag) > 2
            }
        )
        write_json(
            self.workdir / "candidates.json", {"tags_by_frame": tags, "labels": names}
        )
        return names

    def segment(self, vision_python: str | None = None) -> None:
        labels = read_json(self.workdir / "candidates.json")["labels"]
        shutil.rmtree(self.workdir / "masks", ignore_errors=True)
        labels_file = self.workdir / "labels.json"
        write_json(labels_file, labels)
        if vision_python:
            _run_worker(
                vision_python,
                [
                    "sam-image",
                    "--image",
                    str(self.workdir / "input.png"),
                    "--labels",
                    str(labels_file),
                    "--output",
                    str(self.workdir / "masks/original"),
                    "--summary",
                    str(self.workdir / "masks/original.json"),
                ],
            )
        else:
            from .models import sam_image

            write_json(
                self.workdir / "masks/original.json",
                sam_image(
                    self.workdir / "input.png", labels, self.workdir / "masks/original"
                ),
            )
        # Unverified generated views cannot constrain object reconstruction. Segment
        # the source always; propagate videos only when there is a visual approval.
        quality_path = self.workdir / "videos/visual_validation.json"
        quality = read_json(quality_path) if quality_path.exists() else {}
        for direction in ("left", "right"):
            if not quality.get(direction, {}).get("approved_objects"):
                write_json(
                    self.workdir / "masks" / f"{direction}.json",
                    {
                        "status": "not_used",
                        "reason": "no_visually_verified_side_observations",
                    },
                )
                continue
            video = self.workdir / "videos" / f"{direction}.mp4"
            mask_dir = self.workdir / "masks" / direction
            summary = self.workdir / "masks" / f"{direction}.json"
            if vision_python:
                labels_file = self.workdir / "labels.json"
                write_json(labels_file, labels)
                _run_worker(
                    vision_python,
                    [
                        "sam",
                        "--video",
                        str(video),
                        "--labels",
                        str(labels_file),
                        "--output",
                        str(mask_dir),
                        "--summary",
                        str(summary),
                    ],
                )
            else:
                write_json(summary, sam_video(video, labels, mask_dir))

    def select_views(self) -> list[dict]:
        for name in (
            "source_objects",
            "object_views",
            "meshes",
            "accepted_meshes",
            "sofa_scene_accepted_meshes",
            "mesh_inspection",
            "object_review",
            "standalone_check",
        ):
            shutil.rmtree(self.workdir / name, ignore_errors=True)
        objects = []
        source = np.asarray(Image.open(self.workdir / "input.png").convert("RGB"))
        tags_file = self.workdir / "candidate_tags.json"
        original_tags = (
            set(read_json(tags_file).get(str(self.workdir / "input.png"), []))
            if tags_file.exists()
            else set()
        )
        quality_file = self.workdir / "videos/visual_validation.json"
        quality = read_json(quality_file) if quality_file.exists() else {}
        for direction in ("left", "right"):
            root = self.workdir / "masks" / direction
            video = cv2.VideoCapture(str(self.workdir / "videos" / f"{direction}.mp4"))
            poses = np.load(self.workdir / "videos" / f"{direction}_w2c.npy")
            if not video.isOpened():
                raise RuntimeError(f"Cannot read {direction} video")
            label_dirs = sorted(
                root.iterdir() if root.exists() else [],
                key=lambda path: (path.name not in original_tags, path.name),
            )
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
                    anchor = cv2.resize(
                        anchor.astype(np.uint8),
                        (source.shape[1], source.shape[0]),
                        interpolation=cv2.INTER_NEAREST,
                    ).astype(bool)
                    if anchor.sum() < 100 or anchor.mean() > 0.8:
                        continue
                    # The two trajectories start from the same source. Merge matching instances.
                    match = None
                    for existing in objects:
                        other = (
                            np.asarray(Image.open(existing["anchor_mask"]).convert("L"))
                            > 127
                        )
                        intersection = np.logical_and(anchor, other).sum()
                        union = np.logical_or(anchor, other).sum()
                        threshold = (
                            0.55 if existing["label"] == label_dir.name else 0.75
                        )
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
                        Image.fromarray(anchor.astype(np.uint8) * 255).save(anchor_path)
                        match = {
                            "id": obj_id,
                            "label": label_dir.name,
                            "anchor_mask": str(anchor_path),
                            "views": [],
                            "observations": [],
                        }
                        objects.append(match)
                    view_dir = self.workdir / "object_views" / match["id"]
                    if not match["views"]:
                        front = _crop_rgba(source, anchor)
                        front_path = view_dir / "front.png"
                        Image.fromarray(front).save(front_path)
                        match["views"].append(
                            {
                                "role": "front",
                                "path": str(front_path),
                                "direction": "original",
                                "frame": 0,
                            }
                        )
                    scored = []
                    for mask_path in masks:
                        index = int(mask_path.stem)
                        if index < 12 or index >= len(poses):
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
                            mask = cv2.resize(
                                mask.astype(np.uint8),
                                (frame.shape[1], frame.shape[0]),
                                interpolation=cv2.INTER_NEAREST,
                            ).astype(bool)
                        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
                        sharpness = float(cv2.Laplacian(gray, cv2.CV_32F).var())
                        anchor_area = float(anchor.sum()) * mask.size / anchor.size
                        visible_ratio = min(
                            float(mask.sum()) / max(anchor_area, 1.0), 1.0
                        )
                        score = visible_ratio * np.log1p(sharpness)
                        scored.append(
                            (
                                score,
                                index,
                                mask,
                                mask_path,
                                frame,
                                sharpness,
                                visible_ratio,
                            )
                        )
                    # Prefer the most advanced clear observation near the endpoint.
                    eligible = [
                        item
                        for item in scored
                        if item[1] >= int(0.8 * (len(poses) - 1))
                    ]
                    selected = (
                        [max(eligible, key=lambda item: (item[1], item[0]))]
                        if eligible
                        else []
                    )
                    for (
                        score,
                        index,
                        mask,
                        mask_path,
                        frame,
                        sharpness,
                        visible_ratio,
                    ) in selected:
                        path = view_dir / f"{direction}_{index:04d}.png"
                        Image.fromarray(_crop_rgba(frame, mask)).save(path)
                        # Hunyuan 2mv expects canonical sides. Admit only a near-side camera.
                        forward = poses[index, 2, :3]
                        angle = float(
                            np.degrees(
                                np.arccos(np.clip(forward @ poses[0, 2, :3], -1, 1))
                            )
                        )
                        side = direction
                        role = (
                            side
                            if angle >= 80
                            and match["id"]
                            in quality.get(direction, {}).get("approved_objects", [])
                            else "oblique"
                        )
                        match["views"].append(
                            {
                                "role": role,
                                "path": str(path),
                                "direction": direction,
                                "frame": index,
                                "camera_angle_deg": angle,
                                "sharpness": sharpness,
                                "visible_ratio": visible_ratio,
                                "selection_score": score,
                            }
                        )
                        match["observations"].append(
                            {
                                "direction": direction,
                                "frame": index,
                                "mask": str(mask_path),
                            }
                        )
            video.release()
        if (self.workdir / "masks/original.json").exists():
            objects = self._source_anchors(objects, source)
        write_json(self.workdir / "objects.json", objects)
        return objects

    def _source_anchors(self, tracked, source):
        anchors = []
        summary = read_json(self.workdir / "masks/original.json")
        candidates = [
            (label, entry) for label, entries in summary.items() for entry in entries
        ]
        # Precise source concepts win over overlapping synonyms.
        tags_path = self.workdir / "candidate_tags.json"
        source_tags = (
            read_json(tags_path).get(str(self.workdir / "input.png"), [])
            if tags_path.exists()
            else []
        )
        preferred = {SYNONYMS.get(tag, tag) for tag in source_tags}
        candidates.sort(key=lambda item: (item[0] not in preferred, -item[1]["score"]))
        for label, entry in candidates:
            mask = np.asarray(Image.open(entry["path"]).convert("L")) > 127
            if mask.sum() < 100 or mask.mean() > 0.8:
                continue
            if any(
                np.logical_and(mask, other).sum()
                / max(np.logical_or(mask, other).sum(), 1)
                > 0.7
                for _, other in anchors
            ):
                continue
            best, best_iou = None, 0.0
            for obj in tracked:
                if obj["label"] != label:
                    continue
                other = np.asarray(Image.open(obj["anchor_mask"]).convert("L")) > 127
                iou = np.logical_and(mask, other).sum() / max(
                    np.logical_or(mask, other).sum(), 1
                )
                if iou > best_iou:
                    best, best_iou = obj, iou
            obj_id = f"obj_{len(anchors):04d}_{_safe(label)}"
            folder = self.workdir / "source_objects" / obj_id
            folder.mkdir(parents=True, exist_ok=True)
            anchor_path = folder / "anchor_mask.png"
            Image.fromarray(mask.astype(np.uint8) * 255).save(anchor_path)
            front = folder / "front.png"
            Image.fromarray(_crop_rgba(source, mask)).save(front)
            obj = {
                "id": obj_id,
                "label": label,
                "anchor_mask": str(anchor_path),
                "anchor_origin": "source_image_sam3",
                "confidence": entry["score"],
                "views": [
                    {
                        "role": "front",
                        "path": str(front),
                        "direction": "original",
                        "frame": 0,
                    }
                ],
                "observations": [],
            }
            if best is not None and best_iou > 0.3:
                # New source IDs must not inherit approvals attached to old track IDs.
                obj["views"].extend(
                    {**view, "role": "oblique"}
                    for view in best["views"]
                    if view["direction"] != "original"
                )
                obj["observations"] = best["observations"]
            anchors.append((obj, mask))
        return [obj for obj, _ in anchors]

    def meshes(self, hunyuan_python: str | None = None) -> None:
        objects = read_json(self.workdir / "objects.json")
        jobs = []
        from .reconstruction import is_structure

        for obj in objects:
            if is_structure(obj.get("label", "")):
                continue
            target = self.workdir / "meshes" / f"{obj['id']}.glb"
            if target.exists():
                continue
            views = {
                view["role"]: str(view["path"])
                for view in obj["views"]
                if view["role"] in ("front", "left", "back", "right")
            }
            jobs.append({"views": views, "output": str(target)})
        if (
            hunyuan_python
            and jobs
            and all(set(job["views"]) == {"front"} for job in jobs)
        ):
            jobs_file = self.workdir / "hunyuan_jobs.json"
            write_json(jobs_file, jobs)
            _run_worker(hunyuan_python, ["hunyuan-batch", "--jobs", str(jobs_file)])
        else:
            for job in jobs:
                target = Path(job["output"])
                views = {key: Path(path) for key, path in job["views"].items()}
                if hunyuan_python:
                    views_file = (
                        self.workdir
                        / "object_views"
                        / target.stem
                        / "hunyuan_views.json"
                    )
                    write_json(views_file, job["views"])
                    _run_worker(
                        hunyuan_python,
                        [
                            "hunyuan",
                            "--views",
                            str(views_file),
                            "--output",
                            str(target),
                        ],
                    )
                else:
                    hunyuan_mesh(views, target)

    def scene(self, only_sofa: bool = False) -> Path:
        from .assembly import assemble

        return assemble(
            self.workdir,
            labels={"couch", "sofa"} if only_sofa else None,
            prefix="sofa_scene" if only_sofa else "scene",
        )


def _safe(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_")[:64]


def _crop_rgba(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    ys, xs = np.where(mask)
    if not len(xs):
        raise ValueError("Empty object mask")
    margin = max(8, int(max(xs.max() - xs.min(), ys.max() - ys.min()) * 0.08))
    x0, x1 = max(0, xs.min() - margin), min(image.shape[1], xs.max() + margin + 1)
    y0, y1 = max(0, ys.min() - margin), min(image.shape[0], ys.max() + margin + 1)
    return np.dstack((image, mask.astype(np.uint8) * 255))[y0:y1, x0:x1]


def _run_worker(python: str, args: list[str]) -> None:
    import os
    import subprocess

    env = os.environ.copy()
    project_root = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run([python, "-m", "mapmaker.model_worker", *args], env=env, check=True)
