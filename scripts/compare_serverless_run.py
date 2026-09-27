"""Compare two production-format scene runs without changing either result."""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
import trimesh


def compare(reference, current):
    old = json.loads((reference / "scene_metadata.json").read_text())
    new = json.loads((current / "scene_metadata.json").read_text())
    baseline = {obj["id"]: obj for obj in old["objects"]}
    actual = {obj["id"]: obj for obj in new["objects"]}
    rows = []
    for oid in sorted(baseline.keys() & actual.keys()):
        a, b = baseline[oid], actual[oid]
        ma = np.asarray(Image.open(reference / a["mask"])) > 0
        mb = np.asarray(Image.open(current / b["mask"])) > 0
        row = {"id": oid, "status": b["status"],
               "mask_iou": float((ma & mb).sum() / max(1, (ma | mb).sum()))}
        if a.get("pose") and b.get("pose") and b["status"] == "generated":
            pa, pb = a["pose"], b["pose"]
            qa, qb = np.asarray(pa["rotation"]).ravel(), np.asarray(pb["rotation"]).ravel()
            cosine = abs(np.dot(qa, qb) / (np.linalg.norm(qa) * np.linalg.norm(qb)))
            sa = trimesh.load(reference / a["asset"], force="scene", process=False)
            sb = trimesh.load(current / b["asset"], force="scene", process=False)
            row.update(
                rotation_difference_degrees=float(2 * np.degrees(np.arccos(np.clip(cosine, 0, 1)))),
                translation_distance=float(np.linalg.norm(np.asarray(pa["translation"]) - np.asarray(pb["translation"]))),
                scale_ratio=(np.asarray(pb["scale"]) / np.asarray(pa["scale"])).tolist(),
                mesh_extent_ratio=(sb.extents / sa.extents).tolist(),
            )
        rows.append(row)
    return {
        "reference_run": old["run_id"], "current_run": new["run_id"],
        "input_pixels_equal": bool(np.array_equal(
            np.asarray(Image.open(reference / old["input_image"])),
            np.asarray(Image.open(current / new["input_image"])))),
        "missing_objects": sorted(baseline.keys() - actual.keys()),
        "additional_objects": sorted(actual.keys() - baseline.keys()),
        "objects": rows, "errors": new["errors"],
        "note": "Measured differences, not a claim of bitwise equivalence across GPU architectures.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("current", type=Path)
    args = parser.parse_args()
    report = compare(args.reference, args.current)
    target = args.current / "logs/serverless_regression.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
