"""Compare old/new GLB visible masks against the same newly inferred source masks."""

import argparse
from pathlib import Path
import cv2
import numpy as np
import trimesh
from PIL import Image, ImageDraw
from scipy.optimize import linear_sum_assignment
from mapmaker.common import read_json, write_json
from mapmaker.raster import render_scene

p = argparse.ArgumentParser()
p.add_argument("before", type=Path)
p.add_argument("after", type=Path)
args = p.parse_args()
old, new = args.before, args.after
current = read_json(new / "scene.json")
previous = read_json(old / "scene.json")
camera = current["camera"]
w, h = 640, round(camera["height"] * 640 / camera["width"])
k = np.array(camera["K"])
k[0] *= w / camera["width"]
k[1] *= h / camera["height"]
flip = np.diag([1.0, -1.0, -1.0, 1.0])
old_rgb, _, old_owner, old_names = render_scene(
    trimesh.load(old / "scene.glb", force="scene"), k, w, h, flip
)
new_rgb, _, new_owner, new_names = render_scene(
    trimesh.load(new / "scene.glb", force="scene"), k, w, h, flip
)
objects = current["objects"]
masks = {
    o["id"]: cv2.resize(
        np.asarray(Image.open(o["anchor_mask"]).convert("L")),
        (w, h),
        interpolation=cv2.INTER_NEAREST,
    )
    > 127
    for o in objects
}
occupied = np.zeros((h, w), bool)
visible = {}
for obj in sorted(objects, key=lambda o: masks[o["id"]].sum()):
    mask = masks[obj["id"]]
    visible[obj["id"]] = mask & ~occupied
    occupied |= mask


def iou(a, b):
    return float((a & b).sum() / max((a | b).sum(), 1))


def label(s):
    return s.replace("_", " ").replace("shelve", "shelf")


def old_prediction(candidate, target):
    predicted = old_owner == old_names.index(candidate["id"])
    # Compare the same physical sofa even though the old scene kept cushions as
    # separate overlapping objects and the new scene integrates them.
    if target.get("integrated_parts"):
        for part in previous["objects"]:
            if (
                part["label"] not in {"pillow", "cushion"}
                or part["id"] not in old_names
            ):
                continue
            region = old_owner == old_names.index(part["id"])
            if (region & visible[target["id"]]).sum() / max(region.sum(), 1) >= 0.5:
                predicted |= region
    return predicted


rows = {
    o["id"]: {
        "id": o["id"],
        "label": o["label"],
        "after_visible_iou": iou(
            new_owner == new_names.index(o["id"]), visible[o["id"]]
        ),
    }
    for o in objects
}
for category in sorted({label(o["label"]) for o in objects}):
    targets = [o for o in objects if label(o["label"]) == category]
    candidates = [
        o
        for o in previous["objects"]
        if label(o["label"]) == category and o["id"] in old_names
    ]
    if not candidates:
        continue
    scores = np.array(
        [
            [iou(old_prediction(c, t), visible[t["id"]]) for c in candidates]
            for t in targets
        ]
    )
    ri, ci = linear_sum_assignment(-scores)
    for r, c in zip(ri, ci):
        rows[targets[r]["id"]].update(
            before_id=candidates[c]["id"], before_visible_iou=float(scores[r, c])
        )
matched = [r for r in rows.values() if "before_visible_iou" in r]
report = {
    "metric": "visible_mask_iou_against_same_fresh_source_masks",
    "width": w,
    "height": h,
    "matching": "one-to-one maximum IoU within label; old overlapping cushions included with sofa",
    "before_uncovered_fraction": float((old_owner < 0).mean()),
    "after_uncovered_fraction": float((new_owner < 0).mean()),
    "matched_before_mean": float(np.mean([r["before_visible_iou"] for r in matched]))
    if matched
    else None,
    "matched_after_mean": float(np.mean([r["after_visible_iou"] for r in matched]))
    if matched
    else None,
    "objects": list(rows.values()),
}
write_json(new / "before_after_metrics.json", report)
sheet = Image.new("RGB", (w * 3, h + 30), (32, 36, 44))
draw = ImageDraw.Draw(sheet)
for i, (title, im) in enumerate(
    [
        ("Before: original renderer", Image.open(old / "scene_glb_source.png")),
        ("Before GLB: pixel Z-buffer", Image.fromarray(old_rgb)),
        ("After GLB: pixel Z-buffer", Image.fromarray(new_rgb)),
    ]
):
    sheet.paste(im.resize((w, h)), (i * w, 30))
    draw.text((i * w + 8, 8), title, fill="white")
sheet.save(new / "before_after.jpg", quality=90)
