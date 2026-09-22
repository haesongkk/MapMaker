"""Compatibility entry points using the same pixel-depth renderer as the GLB checks."""

from pathlib import Path
import numpy as np
import trimesh
from PIL import Image
from .common import read_json
from .raster import render_scene


def render_silhouette(mesh, matrix, k, height, width):
    scene = trimesh.Scene()
    scene.add_geometry(mesh, transform=matrix)
    _, _, owners, _ = render_scene(scene, k, width, height)
    return (owners >= 0).astype(np.uint8) * 255


def validate_scene(workdir: Path):
    from .assembly import validate

    metadata = read_json(workdir / "scene.json")
    scene = trimesh.load(workdir / "scene.glb", force="scene")
    objects = metadata["objects"]
    camera = metadata["camera"]
    masks = {
        o["id"]: np.asarray(Image.open(o["anchor_mask"]).convert("L")) > 127
        for o in objects
    }
    owned = np.zeros((camera["height"], camera["width"]), bool)
    visible = {}
    for obj in sorted(objects, key=lambda o: masks[o["id"]].sum()):
        mask = masks[obj["id"]]
        visible[obj["id"]] = mask & ~owned
        owned |= mask
    validate(
        workdir,
        scene,
        objects,
        masks,
        visible,
        np.asarray(camera["K"]),
        camera,
        "scene",
    )
    return read_json(workdir / "validation.json")
