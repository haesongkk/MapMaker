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
    write_json(work / "analysis/camera.json", {"K": k.tolist(), "width": 32, "height": 32})
    mask = np.zeros((32, 32), dtype=np.uint8)
    mask[8:24, 8:24] = 255
    (work / "object_views/obj_0000_cube").mkdir(parents=True)
    Image.fromarray(mask).save(work / "object_views/obj_0000_cube/anchor_mask.png")
    (work / "meshes").mkdir()
    trimesh.creation.box().export(work / "meshes/obj_0000_cube.glb")
    write_json(work / "objects.json", [{"id": "obj_0000_cube", "label": "cube",
                                      "anchor_mask": str(work / "object_views/obj_0000_cube/anchor_mask.png")}])
    target = Pipeline(source, work).scene()
    assert target.exists()
    scene = trimesh.load(target, force="scene")
    assert len(scene.geometry) == 2
    background = make_depth_mesh(image, points, np.ones_like(depth, dtype=bool), mask > 0)
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
    for direction in ("clockwise", "counterclockwise"):
        mask_dir = work / "masks" / direction / "cube" / "1"
        mask_dir.mkdir(parents=True)
        mask = np.zeros((32, 32), dtype=np.uint8)
        mask[8:24, 8:24] = 255
        for frame_index in range(13):
            Image.fromarray(mask).save(mask_dir / f"{frame_index:04d}.png")
        (work / "videos").mkdir(exist_ok=True)
        writer = cv2.VideoWriter(str(work / "videos" / f"{direction}.mp4"),
                                 cv2.VideoWriter_fourcc(*"mp4v"), 5, (32, 32))
        for _ in range(13):
            writer.write(cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
        writer.release()
        poses = np.repeat(np.eye(4)[None], 13, axis=0)
        np.save(work / "videos" / f"{direction}_w2c.npy", poses)
    objects = Pipeline(source, work).select_views()
    assert len(objects) == 1
    assert objects[0]["views"][0]["role"] == "front"
    assert len(objects[0]["observations"]) == 2
