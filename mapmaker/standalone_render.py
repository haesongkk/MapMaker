"""Render GLB geometry/materials only. No input photograph is read here."""

from pathlib import Path
import numpy as np
import trimesh
from PIL import Image
from .common import read_json, write_json
from .raster import render_scene


def render_glb(
    workdir: Path,
    yaw_degrees: float = 0,
    scale: float = 0.5,
    scene_path: Path | None = None,
    prefix: str = "scene_glb",
) -> Path:
    scene = trimesh.load(scene_path or workdir / "scene.glb", force="scene")
    camera = scene.metadata.get("source_camera")
    if camera is None:  # Compatibility with old GLBs that have no embedded calibration.
        camera = read_json(workdir / "analysis/camera.json")
    width, height = round(camera["width"] * scale), round(camera["height"] * scale)
    k = np.asarray(camera["K"], dtype=float).copy()
    k[0] *= width / camera["width"]
    k[1] *= height / camera["height"]
    gltf_to_cv = np.diag([1.0, -1.0, -1.0, 1.0])
    yaw = np.deg2rad(yaw_degrees)
    rotation = np.array(
        [[np.cos(yaw), 0, -np.sin(yaw)], [0, 1, 0], [np.sin(yaw), 0, np.cos(yaw)]]
    )
    view = np.eye(4)
    view[:3, :3] = rotation
    pivot = np.array([0.0, 0.0, 3.0])
    view[:3, 3] = pivot - rotation @ pivot
    pixels, depth, owners, names = render_scene(
        scene, k, width, height, view @ gltf_to_cv
    )
    suffix = "source" if yaw_degrees == 0 else f"yaw_{yaw_degrees:g}"
    path = workdir / f"{prefix}_{suffix}.png"
    Image.fromarray(pixels).save(path)
    np.save(workdir / f"{prefix}_{suffix}_depth.npy", depth)
    np.save(workdir / f"{prefix}_{suffix}_owners.npy", owners)
    write_json(
        workdir / f"{prefix}_{suffix}.json",
        {
            "renderer": "perspective_correct_pixel_z_buffer",
            "nodes": names,
            "uncovered_pixels": int((owners < 0).sum()),
            "pixels": int(owners.size),
            "world_to_camera": (view @ gltf_to_cv).tolist(),
            "K": k.tolist(),
        },
    )
    return path
