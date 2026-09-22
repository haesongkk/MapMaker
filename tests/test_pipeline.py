from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from mapmaker.common import image_to_points, write_json
from mapmaker.geometry import make_depth_mesh
from mapmaker.pipeline import Pipeline


def test_depth_mesh_and_scene(tmp_path: Path):
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    image[:] = [150, 150, 150]
    source = tmp_path / "source.png"
    Image.fromarray(image).save(source)
    work = tmp_path / "work"
    work.mkdir()
    (work / "analysis").mkdir()
    Image.fromarray(image).save(work / "input.png")
    k = np.array([[30, 0, 16], [0, 30, 16], [0, 0, 1]], dtype=float)
    depth = np.ones((32, 32), dtype=float) * 2
    points = image_to_points(depth, k)
    np.save(work / "analysis/depth.npy", depth)
    np.save(work / "analysis/points.npy", points)
    np.save(work / "analysis/valid.npy", np.ones_like(depth, dtype=bool))
    write_json(
        work / "analysis/camera.json", {"K": k.tolist(), "width": 32, "height": 32}
    )
    mask = np.zeros((32, 32), dtype=np.uint8)
    mask[8:24, 8:24] = 255
    (work / "object_views/obj_0000_cube").mkdir(parents=True)
    Image.fromarray(mask).save(work / "object_views/obj_0000_cube/anchor_mask.png")
    (work / "meshes").mkdir()
    trimesh.creation.box().export(work / "meshes/obj_0000_cube.glb")
    write_json(
        work / "objects.json",
        [
            {
                "id": "obj_0000_cube",
                "label": "cube",
                "anchor_mask": str(work / "object_views/obj_0000_cube/anchor_mask.png"),
            }
        ],
    )
    target = Pipeline(source, work).scene()
    assert target.exists()
    assert (work / "scene_comparison.png").exists()
    scene = trimesh.load(target, force="scene")
    assert len(scene.geometry) == 2
    background = make_depth_mesh(
        image, points, np.ones_like(depth, dtype=bool), mask > 0
    )
    assert len(background.faces) > 0


def test_view_selection_merges_two_directions(tmp_path: Path):
    import cv2

    source = tmp_path / "source.png"
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    image[8:24, 8:24] = [255, 0, 0]
    Image.fromarray(image).save(source)
    work = tmp_path / "work"
    work.mkdir()
    Image.fromarray(image).save(work / "input.png")
    for direction in ("left", "right"):
        mask_dir = work / "masks" / direction / "cube" / "1"
        mask_dir.mkdir(parents=True)
        mask = np.zeros((32, 32), dtype=np.uint8)
        mask[8:24, 8:24] = 255
        for frame_index in range(13):
            Image.fromarray(mask).save(mask_dir / f"{frame_index:04d}.png")
        (work / "videos").mkdir(exist_ok=True)
        writer = cv2.VideoWriter(
            str(work / "videos" / f"{direction}.mp4"),
            cv2.VideoWriter_fourcc(*"mp4v"),
            5,
            (32, 32),
        )
        for _ in range(13):
            writer.write(cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
        writer.release()
        poses = np.repeat(np.eye(4)[None], 13, axis=0)
        np.save(work / "videos" / f"{direction}_w2c.npy", poses)
    objects = Pipeline(source, work).select_views()
    assert len(objects) == 1
    assert objects[0]["views"][0]["role"] == "front"
    assert len(objects[0]["observations"]) == 2
    assert all(view["role"] != "left" for view in objects[0]["views"])


def test_views_clear_stale_artifacts_when_camera_settings_change(tmp_path: Path):
    from unittest.mock import patch

    source = tmp_path / "source.png"
    Image.fromarray(np.zeros((16, 16, 3), dtype=np.uint8)).save(source)
    work = tmp_path / "work"
    work.mkdir()
    Image.open(source).save(work / "input.png")
    for folder in ("videos", "frames", "masks", "object_views", "meshes"):
        path = work / folder
        path.mkdir()
        (path / "stale.txt").write_text("old")
    write_json(work / "objects.json", [{"old": True}])

    def fake_gen(image, video_dir, repo, checkpoints, python, distance, angle):
        assert not (work / "masks/stale.txt").exists()
        assert not (work / "objects.json").exists()
        for side in ("left", "right"):
            (video_dir / f"{side}.mp4").touch()
            np.save(video_dir / f"{side}_w2c.npy", np.eye(4)[None])
            np.save(video_dir / f"{side}_K.npy", np.eye(3)[None])

    with (
        patch("mapmaker.pipeline.run_gen3c", fake_gen),
        patch("mapmaker.pipeline.extract_frames"),
    ):
        Pipeline(source, work).views(
            tmp_path, tmp_path, "python", distance=0.8, angle=90
        )
    assert not any(
        (work / name / "stale.txt").exists()
        for name in ("videos", "frames", "masks", "object_views", "meshes")
    )
    assert (work / "frames/manifest.json").exists()


def test_mesh_batch_uses_only_approved_roles(tmp_path: Path):
    from unittest.mock import patch

    source = tmp_path / "source.png"
    Image.fromarray(np.zeros((16, 16, 3), dtype=np.uint8)).save(source)
    work = tmp_path / "work"
    work.mkdir()
    write_json(
        work / "objects.json",
        [
            {
                "id": "obj_0000_couch",
                "views": [
                    {"role": "front", "path": "front.png"},
                    {"role": "oblique", "path": "side.png"},
                ],
            }
        ],
    )
    calls = []
    with patch(
        "mapmaker.pipeline._run_worker", lambda python, args: calls.append(args)
    ):
        Pipeline(source, work).meshes("python")
    jobs = __import__("json").loads((work / "hunyuan_jobs.json").read_text())
    assert jobs[0]["views"] == {"front": "front.png"}
    assert calls[0][0] == "hunyuan-batch"


def test_original_content_hash_invalidates_all_downstream(tmp_path):
    import os
    from unittest.mock import patch
    from mapmaker.common import read_json

    source = tmp_path / "source.png"
    Image.fromarray(np.full((20, 20, 3), 100, np.uint8)).save(source)
    work = tmp_path / "work"
    pipeline = Pipeline(source, work)
    calls = []

    def fake_analyze(image, analysis):
        calls.append(1)
        k = np.array([[20.0, 0, 10], [0, 20.0, 10], [0, 0, 1]])
        np.save(analysis / "points.npy", image_to_points(np.full((20, 20), 2.0), k))
        np.save(analysis / "valid.npy", np.ones((20, 20), bool))
        write_json(
            analysis / "camera.json", {"width": 20, "height": 20, "K": k.tolist()}
        )

    with patch("mapmaker.pipeline.analyze", fake_analyze):
        pipeline.original()
        (work / "videos").mkdir()
        (work / "videos/stale.mp4").touch()
        pipeline.original()
        assert len(calls) == 1 and (work / "videos/stale.mp4").exists()
        previous = source.stat()
        Image.fromarray(np.full((20, 20, 3), 180, np.uint8)).save(source)
        os.utime(source, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        pipeline.original()
    assert len(calls) == 2
    assert not (work / "videos/stale.mp4").exists()
    assert read_json(work / "run_manifest.json")["source_sha256"]


def test_source_anchor_does_not_inherit_generated_frame_mask_or_side_approval(tmp_path):
    source = tmp_path / "source.png"
    image = np.full((32, 32, 3), 100, np.uint8)
    Image.fromarray(image).save(source)
    pipeline = Pipeline(source, tmp_path / "work")
    work = pipeline.workdir
    direct = np.zeros((32, 32), bool)
    direct[6:26, 5:22] = True
    shifted = np.roll(direct, 5, axis=1)
    direct_path = work / "direct.png"
    old_path = work / "generated_frame_zero.png"
    Image.fromarray(direct.astype(np.uint8) * 255).save(direct_path)
    Image.fromarray(shifted.astype(np.uint8) * 255).save(old_path)
    write_json(
        work / "masks/original.json",
        {"couch": [{"path": str(direct_path), "score": 0.99}]},
    )
    tracked = [
        {
            "id": "old_track",
            "label": "couch",
            "anchor_mask": str(old_path),
            "views": [{"role": "left", "direction": "left", "path": "unverified.png"}],
            "observations": [],
        }
    ]
    objects = pipeline._source_anchors(tracked, image)
    assert len(objects) == 1
    assert np.array_equal(
        np.asarray(Image.open(objects[0]["anchor_mask"])) > 127, direct
    )
    assert [view["role"] for view in objects[0]["views"]] == ["front", "oblique"]


def test_segment_uses_source_and_records_unapproved_video_skip(tmp_path):
    from unittest.mock import patch
    from mapmaker.common import read_json

    source = tmp_path / "source.png"
    Image.fromarray(np.zeros((16, 16, 3), np.uint8)).save(source)
    pipeline = Pipeline(source, tmp_path / "work")
    work = pipeline.workdir
    write_json(work / "candidates.json", {"labels": ["couch"]})
    calls = []
    with patch(
        "mapmaker.pipeline._run_worker", lambda python, args: calls.append(args)
    ):
        pipeline.segment("python")
    assert len(calls) == 1 and calls[0][0] == "sam-image"
    assert (
        read_json(work / "masks/left.json")["reason"]
        == "no_visually_verified_side_observations"
    )
