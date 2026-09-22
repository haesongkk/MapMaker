"""Save per-object source/shifted GLB previews, contact sheets and source mask crops."""

import argparse
from pathlib import Path
import shutil
import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageOps
from mapmaker.common import read_json
from mapmaker.raster import render_scene

p = argparse.ArgumentParser()
p.add_argument("workdir", type=Path)
args = p.parse_args()
work = args.workdir
metadata = read_json(work / "scene.json")
camera = metadata["camera"]
k = np.array(camera["K"]) * 0.5
k[2, 2] = 1
width, height = round(camera["width"] * 0.5), round(camera["height"] * 0.5)
folder = work / "object_review"
shutil.rmtree(folder, ignore_errors=True)
folder.mkdir(exist_ok=True)
source = Image.open(work / "input.png").convert("RGB")
flip = np.diag([1.0, -1.0, -1.0, 1.0])
rows = []
for obj in metadata["objects"]:
    obj_id = obj["id"]
    mask = np.asarray(Image.open(obj["anchor_mask"])) > 127
    yy, xx = np.where(mask)
    box = (int(xx.min()), int(yy.min()), int(xx.max() + 1), int(yy.max() + 1))
    reference = source.crop(box)
    scene = trimesh.Scene()
    mesh = trimesh.load(obj["mesh"], force="scene").to_geometry()
    scene.add_geometry(mesh, transform=np.array(obj["source_transform"]))
    panels = [reference]
    for angle in (0, 12):
        rad = np.deg2rad(angle)
        rot = np.array(
            [[np.cos(rad), 0, -np.sin(rad)], [0, 1, 0], [np.sin(rad), 0, np.cos(rad)]]
        )
        view = np.eye(4)
        view[:3, :3] = rot
        view[:3, 3] = np.array([0, 0, 3]) - rot @ np.array([0, 0, 3])
        rgb, _, owners, _ = render_scene(scene, k, width, height, view)
        im = Image.fromarray(rgb)
        im.save(folder / f"{obj_id}_{angle}.png")
        y, x = np.where(owners >= 0)
        panels.append(
            im.crop(
                (
                    max(0, x.min() - 5),
                    max(0, y.min() - 5),
                    min(width, x.max() + 6),
                    min(height, y.max() + 6),
                )
            )
            if len(x)
            else im
        )
    raw_path = work / "mesh_inspection" / f"{obj_id}_generated_source.png"
    if raw_path.exists():
        im = Image.open(raw_path).convert("RGB")
        owners = np.load(raw_path.with_name(f"{obj_id}_generated_source_owners.npy"))
        y, x = np.where(owners >= 0)
        raw = (
            im.crop(
                (
                    max(0, x.min() - 5),
                    max(0, y.min() - 5),
                    min(width, x.max() + 6),
                    min(height, y.max() + 6),
                )
            )
            if len(x)
            else im
        )
    else:
        raw = Image.new("RGB", (200, 140), (32, 36, 44))
        ImageDraw.Draw(raw).text((10, 60), "Observed structure", fill="white")
    panels.insert(1, raw)
    row = Image.new("RGB", (1000, 230), (32, 36, 44))
    draw = ImageDraw.Draw(row)
    draw.text((8, 4), f"{obj_id}: {obj['representation']}", fill="white")
    for index, (panel, title) in enumerate(
        zip(
            panels,
            [
                "Source crop",
                "Generated candidate",
                "Accepted source",
                "Accepted +12 deg",
            ],
        )
    ):
        draw.text((250 * index + 8, 24), title, fill="white")
        panel = ImageOps.contain(panel, (246, 180))
        row.paste(
            panel,
            (250 * index + (250 - panel.width) // 2, 46 + (180 - panel.height) // 2),
        )
    row.save(folder / f"{obj_id}_review.jpg", quality=88)
    rows.append(row)
for start in range(0, len(rows), 4):
    subset = rows[start : start + 4]
    sheet = Image.new("RGB", (1000, 230 * len(subset)))
    for i, row in enumerate(subset):
        sheet.paste(row, (0, 230 * i))
    sheet.save(folder / f"contact_{start // 4:02d}.jpg", quality=82)
