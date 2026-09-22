"""Contact sheets of every generated candidate, including rejected and nested parts."""

import argparse
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageOps
from mapmaker.common import read_json

p = argparse.ArgumentParser()
p.add_argument("workdir", type=Path)
work = p.parse_args().workdir
objects = read_json(work / "objects.json")
audits = {a["id"]: a for a in read_json(work / "scene.json")["mesh_audit"]}
rows = []
for obj in objects:
    obj_id = obj["id"]
    root = work / "mesh_inspection"
    if not (root / f"{obj_id}_generated_source.png").exists():
        continue
    rgba = Image.open(obj["views"][0]["path"]).convert("RGBA")
    front = Image.new("RGBA", rgba.size, (65, 65, 65, 255))
    front.alpha_composite(rgba)
    panels = [front.convert("RGB")]
    for suffix in ("source", "yaw_12"):
        im = Image.open(root / f"{obj_id}_generated_{suffix}.png").convert("RGB")
        owner = np.load(root / f"{obj_id}_generated_{suffix}_owners.npy")
        y, x = np.where(owner >= 0)
        panels.append(
            im.crop(
                (
                    max(0, x.min() - 5),
                    max(0, y.min() - 5),
                    min(im.width, x.max() + 6),
                    min(im.height, y.max() + 6),
                )
            )
            if len(x)
            else im
        )
    row = Image.new("RGB", (900, 245), (32, 36, 44))
    draw = ImageDraw.Draw(row)
    draw.text(
        (6, 5),
        f"{obj_id}: {audits.get(obj_id, {}).get('decision', 'pending')}",
        fill="white",
    )
    for i, (im, title) in enumerate(
        zip(panels, ["Source crop", "Generated source", "Generated +12 degrees"])
    ):
        draw.text((i * 300 + 6, 25), title, fill="white")
        im = ImageOps.contain(im, (294, 195))
        row.paste(im, (i * 300 + (300 - im.width) // 2, 47))
    rows.append(row)
for start in range(0, len(rows), 4):
    group = rows[start : start + 4]
    sheet = Image.new("RGB", (900, 245 * len(group)))
    for i, row in enumerate(group):
        sheet.paste(row, (0, 245 * i))
    sheet.save(
        work / "mesh_inspection" / f"all_candidates_{start // 4:02d}.jpg", quality=77
    )
