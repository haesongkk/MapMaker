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
from mapmaker.reconstruction_review import validate_review_artifacts
review_validation = validate_review_artifacts(run, meta)
image = np.asarray(Image.open(run / meta["input_image"]).convert("RGB"))
objects = [o for o in meta["objects"] if o["status"] == "generated"]
assert objects
assert meta["pipeline"]["object_extraction_model"] == "RAM++"
point_path = meta['object_extraction'].get('point_segmentation', {})
assert (meta['object_extraction']['raw_tags'] or
        (point_path.get('weights', {}).get('checkpoint_coverage') == 'complete'
         and point_path.get('points', 0) > 0
         and any(o.get('proposal_method') == 'uniform_point_grid' for o in objects)))
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
    if meta['placement'].get('version', 0) >= 8:
        groups = meta['assembly']['groups']
        assert all(scene.graph.transforms.parents[o['id']] == groups['objects'] for o in objects)
        assert all(scene.graph.transforms.parents[s['node']] == groups['space'] for s in meta.get('structure', {}).get('surfaces', []))
    for obj in objects:
        bounds = bounds_of(object_vertices(scene, obj["id"]))
        assert np.allclose(bounds, obj["placement"]["world_bounds_after"], atol=1e-6)
        before = np.asarray(obj["placement"]["original_matrix"])
        after = np.asarray(obj["transform"]["matrix"])
        if meta["placement"].get("version") in (2, 3, 4, 5, 6, 7, 8, 9, 10):
            common = np.asarray(meta["placement"]["common_transform"])
            global_matrix = common @ before
            if meta["placement"]["version"] in (3, 4, 5, 6, 7, 8, 9, 10):
                individual = obj["placement"]["individual"]
                delta = np.asarray(individual["transform"])
                expected = delta @ global_matrix
                expected[:3, 3] += obj['placement'].get('registration_translation', [0., 0., 0.])
                contacts = obj['placement'].get('contacts', [])
                pose_key = 'pose_depth' if 'pose_depth_transform' in obj['placement'] else 'rigid_depth'
                rigid = obj['placement'].get(pose_key+'_transform')
                prior_count = obj['placement'].get(pose_key+'_prior_contact_count', 0) if rigid is not None else len(contacts)
                assert 0 <= prior_count <= len(contacts)
                for contact in contacts[:prior_count]:
                    expected[:3,3] += contact['translation']
                if rigid is not None:
                    rigid = np.asarray(rigid)
                    assert rigid.shape == (4,4) and np.isfinite(rigid).all()
                    factor=float(np.cbrt(np.linalg.det(rigid[:3,:3]))) if pose_key=='pose_depth' else 1.
                    assert .9-1e-8 <= factor <= 1.1+1e-8
                    assert np.allclose(rigid[:3,:3].T@rigid[:3,:3], np.eye(3)*factor**2, atol=1e-6)
                    assert np.isclose(np.linalg.det(rigid[:3,:3]),factor**3)
                    assert np.allclose(rigid[3],[0,0,0,1])
                    expected = rigid@expected
                for contact in contacts[prior_count:]:
                    expected[:3,3] += contact['translation']
                assert np.allclose(after, expected, atol=1e-6)
                assert np.allclose(delta[:3, :3].T @ delta[:3, :3], np.eye(3), atol=1e-6)
                assert np.isclose(np.linalg.det(delta[:3, :3]), 1.)
                if meta["placement"]["version"] in (4, 5):
                    assert np.allclose(after[:3, 1] / np.linalg.norm(after[:3, 1]), [0, 1, 0], atol=1e-6)
                if individual.get("grounded", individual["applied"]):
                    assert np.allclose(after[:3, 1] / np.linalg.norm(after[:3, 1]), [0, 1, 0], atol=1e-6)
                    assert abs(bounds[0, 1]) < 1e-6
                    if meta["placement"]["version"] < 5:
                        assert np.allclose(after[[0, 2], 3], global_matrix[[0, 2], 3], atol=1e-6)
                elif meta["placement"]["version"] in (5, 6, 7, 8, 9, 10):
                    pass  # Contact translations are checked in expected above.
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
    if meta["placement"].get("version") in (2, 3, 4, 5, 6, 7, 8, 9, 10):
        from alignment_reference import alignment_objects
        references = alignment_objects(meta)
        ups = np.array([(common @ np.asarray(o["placement"]["original_matrix"]))[:3, 1] for o in references])
        ups /= np.linalg.norm(ups, axis=1)[:, None]
        mean = ups.mean(axis=0)
        if (meta['placement'].get('method') == 'pointmap_surface_normals'
                or meta['placement'].get('orientation_evidence', {}).get('accepted')):
            assert np.allclose(common[:3, :3] @ meta['placement']['orientation_evidence']['up'], [0, 1, 0], atol=1e-6)
        else:
            assert np.allclose(mean / np.linalg.norm(mean), [0, 1, 0], atol=1e-6)
        if meta["placement"]["version"] < 4:
            assert abs(min(bounds_of(object_vertices(scene, o["id"]))[0, 1] for o in objects)) < 1e-6
        assert np.allclose(common[:3, :3].T @ common[:3, :3], np.eye(3), atol=1e-6)
        assert np.isclose(np.linalg.det(common[:3, :3]), 1.)
    for floor in meta.get("background", []):
        assert floor["node"] in names
        bounds = bounds_of(object_vertices(scene, floor["node"]))
        if "top_y" in floor:
            assert abs(bounds[1, 1] - floor["top_y"]) < 1e-6
        else:
            assert np.allclose(bounds, floor["bounds"], atol=1e-6)
    if not meta.get("background"):
        assert "background_floor" not in names
    placement_checks = {"background": True, "transform_composition": True, "world_bounds": True}
report = {
    "passed": True,
    "reconstruction_review": review_validation,
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
(run / "logs").mkdir(exist_ok=True)
(run / "logs/artifact_validation.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
