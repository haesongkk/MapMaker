"""Audit real run artifacts and optionally compare masks to the frozen reference."""

from pathlib import Path
import argparse, json, struct
import numpy as np
from PIL import Image
import trimesh

p = argparse.ArgumentParser()
p.add_argument("run", type=Path)
p.add_argument("--reference", type=Path)
a = p.parse_args()
run = a.run.resolve()
meta = json.loads((run / "scene_metadata.json").read_text())
image = np.asarray(Image.open(run / meta["input_image"]).convert("RGB"))
objects = [o for o in meta["objects"] if o["status"] == "generated"]
assert objects
assert (
    meta["pipeline"]["object_extraction_model"] == "RAM++"
    and meta["object_extraction"]["raw_tags"]
)
scene = trimesh.load(run / meta["scene_asset"], force="scene", process=False)
checks = []
masks = {}
for o in objects:
    mask = np.asarray(Image.open(run / o["mask"]))
    assert mask.shape == image.shape[:2] and set(np.unique(mask)).issubset({0, 255})
    masks[o["id"]] = mask > 0
    asset = trimesh.load(run / o["asset"], force="scene", process=False)
    assert len(asset.geometry) and np.isfinite(asset.bounds).all()
    assert o["id"] in scene.graph.nodes
    assert np.allclose(scene.graph[o["id"]][0], o["transform"]["matrix"], atol=1e-6)
    assert (np.asarray(o["transform"]["scale"]) > 0).all()
    checks.append(
        {
            "id": o["id"],
            "mask_pixels": int(masks[o["id"]].sum()),
            "geometry_count": len(asset.geometry),
            "valid": True,
        }
    )
raw = (run / "scene.glb").read_bytes()
assert raw[:4] == b"glTF"
length, kind = struct.unpack_from("<II", raw, 12)
assert kind == 0x4E4F534A
gltf = json.loads(raw[20 : 20 + length])
names = {n.get("name") for n in gltf["nodes"]}
assert all(o["id"] in names for o in objects)
report = {
    "passed": True,
    "run": str(run),
    "objects": checks,
    "node_count": len(objects),
    "gltf_node_count": len(gltf["nodes"]),
    "errors": meta["errors"],
    "previews": [str(p.relative_to(run)) for p in (run / "previews").rglob("*.png")],
}
assert report["previews"]
if a.reference:
    ref = a.reference.resolve()
    refimage = np.asarray(Image.open(ref / "input/rgb.png").convert("RGB"))
    report["reference_input_pixels_equal"] = bool(np.array_equal(image, refimage))
    assert report["reference_input_pixels_equal"]
    reference = []
    for old in json.loads((ref / "segmentation/method.json").read_text())["masks"]:
        if old.get("status") != "SELECTED":
            continue
        mask = np.asarray(Image.open(ref / old["mask"])) > 0
        scores = {
            oid: float((mask & m).sum() / max(1, (mask | m).sum()))
            for oid, m in masks.items()
        }
        match = max(scores, key=scores.get)
        current = next(o for o in objects if o["id"] == match)
        old_dir = ref / "reconstruction" / old["slug"]
        old_pose = json.loads((old_dir / "pose.json").read_text())
        old_mesh = trimesh.load(old_dir / "mesh.glb", force="scene", process=False)
        new_mesh = trimesh.load(run / current["asset"], force="scene", process=False)
        old_q = np.asarray(old_pose["rotation"]).reshape(4)
        new_q = np.asarray(current["pose"]["rotation"]).reshape(4)
        cosine = abs(
            np.dot(old_q, new_q) / (np.linalg.norm(old_q) * np.linalg.norm(new_q))
        )
        reference.append(
            {
                "reference": old["label"],
                "pose_translation_distance": float(
                    np.linalg.norm(
                        np.asarray(old_pose["translation"])
                        - np.asarray(current["pose"]["translation"])
                    )
                ),
                "pose_rotation_angle_degrees": float(
                    2 * np.rad2deg(np.arccos(np.clip(cosine, 0, 1)))
                ),
                "pose_scale_ratio": (
                    np.asarray(current["pose"]["scale"]) / np.asarray(old_pose["scale"])
                ).tolist(),
                "local_mesh_extent_ratio": (
                    new_mesh.extents / old_mesh.extents
                ).tolist(),
                "best_node": match,
                "mask_iou": scores[match],
                "covered": scores[match] >= 0.5,
            }
        )
    report["reference_masks"] = reference
    report["reference_coverage"] = sum(x["covered"] for x in reference)
(run / "logs/artifact_validation.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
