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
placement_checks = None
if meta.get("placement"):
    from mapmaker.scene_placement import bounds_of, object_vertices
    from mapmaker.scene_run import sha
    assert sha(run / "scene.glb") == meta["placement"]["scene_sha256"]
    for obj in objects:
        bounds = bounds_of(object_vertices(scene, obj["id"]))
        assert np.allclose(bounds, obj["placement"]["world_bounds_after"], atol=1e-6)
        before = np.asarray(obj["placement"]["original_matrix"])
        after = np.asarray(obj["transform"]["matrix"])
        if meta["placement"].get("version") in (2, 3, 4):
            common = np.asarray(meta["placement"]["common_transform"])
            global_matrix = common @ before
            if meta["placement"]["version"] in (3, 4):
                individual = obj["placement"]["individual"]
                delta = np.asarray(individual["transform"])
                assert np.allclose(after, delta @ global_matrix, atol=1e-6)
                assert np.allclose(delta[:3, :3].T @ delta[:3, :3], np.eye(3), atol=1e-6)
                assert np.isclose(np.linalg.det(delta[:3, :3]), 1.)
                if meta["placement"]["version"] == 4:
                    assert np.allclose(after[:3, 1] / np.linalg.norm(after[:3, 1]), [0, 1, 0], atol=1e-6)
                if individual.get("grounded", individual["applied"]):
                    assert np.allclose(after[:3, 1] / np.linalg.norm(after[:3, 1]), [0, 1, 0], atol=1e-6)
                    assert abs(bounds[0, 1]) < 1e-6
                    assert np.allclose(after[[0, 2], 3], global_matrix[[0, 2], 3], atol=1e-6)
                elif meta["placement"]["version"] == 4:
                    assert np.allclose(after[:3, 3], global_matrix[:3, 3], atol=1e-6)
                else:
                    assert np.allclose(after, global_matrix, atol=1e-6)
            else:
                assert np.allclose(after, global_matrix, atol=1e-6)
            if meta["placement"]["version"] < 4:
                assert bounds[0, 1] >= -1e-6
        else:
            assert np.array_equal(before[:3, :3], after[:3, :3])
            assert np.array_equal(before[[0, 2], 3], after[[0, 2], 3])
        if obj["placement"]["reason"] == "floor_contact":
            assert abs(bounds[0, 1] - meta["placement"]["floor_y"]) < 1e-6
    if meta["placement"].get("version") in (2, 3, 4):
        ups = np.array([(common @ np.asarray(o["placement"]["original_matrix"]))[:3, 1] for o in objects])
        ups /= np.linalg.norm(ups, axis=1)[:, None]
        mean = ups.mean(axis=0)
        assert np.allclose(mean / np.linalg.norm(mean), [0, 1, 0], atol=1e-6)
        if meta["placement"]["version"] < 4:
            assert abs(min(bounds_of(object_vertices(scene, o["id"]))[0, 1] for o in objects)) < 1e-6
        assert np.allclose(common[:3, :3].T @ common[:3, :3], np.eye(3), atol=1e-6)
        assert np.isclose(np.linalg.det(common[:3, :3]), 1.)
    floor = meta["background"][0]
    assert floor["node"] in names
    bounds = bounds_of(object_vertices(scene, floor["node"]))
    assert abs(bounds[1, 1] - floor["top_y"]) < 1e-6
    placement_checks = {"floor": True, "transform_composition": True, "world_bounds": True}
report = {
    "passed": True,
    "run": str(run),
    "objects": checks,
    "node_count": len(objects),
    "gltf_node_count": len(gltf["nodes"]),
    "errors": meta["errors"],
    "placement": placement_checks,
    "previews": [str(p.relative_to(run)) for p in (run / "previews").rglob("*.png")],
}
assert report["previews"]
if a.reference:
    from compare_serverless_run import compare
    report["reference"] = compare(a.reference.resolve(), run)
    assert report["reference"]["input_pixels_equal"]
(run / "logs/artifact_validation.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
