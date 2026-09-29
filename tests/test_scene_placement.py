import copy

import numpy as np
import pytest
import trimesh

from mapmaker.scene_placement import (
    FLOOR_NODE, add_floor, bounds_of, correct_placement, finalize_scene, object_vertices,
)
from mapmaker.scene_run import read, write, sha


def fixture_scene(bottoms=(0, 0.2, -0.1), names=("chair", "table", "cabinet")):
    scene = trimesh.Scene(base_frame="Scene")
    objects = []
    for i, (bottom, name) in enumerate(zip(bottoms, names)):
        oid = f"object_{i}"
        matrix = np.eye(4)
        matrix[:3, 3] = [i * 3, bottom + 1, 0]
        scene.graph.update(frame_from="Scene", frame_to=oid, matrix=matrix)
        scene.add_geometry(trimesh.creation.box(extents=[2, 2, 2]), parent_node_name=oid, node_name=f"{oid}__mesh")
        objects.append({"id": oid, "name": name, "status": "generated", "pose": {"sentinel": "unchanged"},
                        "transform": {"matrix": matrix.tolist(), "position": matrix[:3, 3].tolist(), "scale": [1, 1, 1]}})
    return scene, objects


def test_floor_contact_preserves_pose_xz_rotation_and_scale():
    scene, objects = fixture_scene()
    originals = copy.deepcopy(objects)
    report = correct_placement(scene, objects)
    assert report["metrics"]["before"]["floating_count"] == 1
    assert report["metrics"]["before"]["penetrating_count"] == 1
    for obj, original in zip(objects, originals):
        before = np.array(original["transform"]["matrix"])
        after = np.array(obj["transform"]["matrix"])
        assert np.array_equal(before[:3, :3], after[:3, :3])
        assert np.array_equal(before[[0, 2], 3], after[[0, 2], 3])
        assert obj["pose"] == original["pose"]
        assert bounds_of(object_vertices(scene, obj["id"]))[0, 1] == pytest.approx(0)


def test_nested_instances_rotated_scaled_nonzero_pivot_bounds():
    scene, objects = fixture_scene((0,), ("chair",))
    root = trimesh.transformations.rotation_matrix(0.41, [0, 0, 1])
    root[:3, :3] @= np.diag([2, 3, 4])
    root[:3, 3] = [1, 2, 3]
    child = trimesh.transformations.translation_matrix([3, -4, 5])
    scene.graph.update(frame_from="Scene", frame_to="object_0", matrix=root)
    scene.graph.update(frame_from="object_0", frame_to="nested", matrix=child)
    scene.graph.update(frame_from="nested", frame_to="object_0__mesh", matrix=np.eye(4))
    mesh = scene.geometry[scene.graph['object_0__mesh'][1]]
    expected = trimesh.transform_points(mesh.vertices, root @ child)
    np.testing.assert_allclose(bounds_of(object_vertices(scene, "object_0")), bounds_of(expected))
    # A shared geometry instance must contribute independently.
    scene.graph.update(frame_from="object_0", frame_to="instance", matrix=np.eye(4), geometry=scene.graph['object_0__mesh'][1])
    assert len(object_vertices(scene, "object_0")) == 2 * len(mesh.vertices)


def test_unknown_and_large_shift_not_snapped():
    scene, objects = fixture_scene((0, 0, 10, 2), ("chair", "chair", "chair", "houseplant"))
    originals = copy.deepcopy(objects)
    correct_placement(scene, objects)
    assert objects[2]["placement"]["reason"] == "excessive_shift_skipped"
    assert objects[3]["placement"]["reason"] == "category_not_floor_supported"
    for i in (2, 3):
        assert objects[i]["transform"]["matrix"] == originals[i]["transform"]["matrix"]


def test_bedding_follows_bed_without_changing_relative_position():
    scene, objects = fixture_scene((0, .2, .2), ("bed", "chair", "chair"))
    matrix = np.eye(4)
    matrix[1, 3] = 2
    scene.graph.update(frame_from="Scene", frame_to="pillow", matrix=matrix)
    scene.add_geometry(trimesh.creation.box(extents=[.4, .2, .4]), parent_node_name="pillow", node_name="pillow_mesh")
    objects.append({"id": "pillow", "name": "bedding", "transform": {"matrix": matrix.tolist()}})
    correct_placement(scene, objects)
    assert objects[-1]["placement"]["support_object"] == "object_0"
    assert objects[-1]["placement"]["delta_y"] == pytest.approx(.2)


def test_floor_top_footprint_and_glb_roundtrip(tmp_path):
    scene, objects = fixture_scene()
    report = correct_placement(scene, objects)
    floor = add_floor(scene, objects, report)
    scene.export(tmp_path / "floor.glb")
    loaded = trimesh.load(tmp_path / "floor.glb", force="scene", process=False)
    bounds = bounds_of(object_vertices(loaded, FLOOR_NODE))
    assert bounds[1, 1] == pytest.approx(report["floor_y"], abs=1e-7)
    for obj in objects:
        b = bounds_of(object_vertices(loaded, obj["id"]))
        assert np.all(bounds[0, [0, 2]] < b[0, [0, 2]])
        assert np.all(bounds[1, [0, 2]] > b[1, [0, 2]])
    assert floor["margin_each_side_ratio"] == .15


def test_finalize_idempotent_and_hash_checked(tmp_path):
    scene, objects = fixture_scene()
    scene.export(tmp_path / "scene.glb")
    write(tmp_path / "scene_metadata.json", {"objects": objects, "pipeline": {}})
    finalize_scene(tmp_path, render=False)
    first_hash = sha(tmp_path / "scene.glb")
    first_meta = read(tmp_path / "scene_metadata.json")
    finalize_scene(tmp_path, render=False)
    assert sha(tmp_path / "scene.glb") == first_hash
    assert read(tmp_path / "scene_metadata.json") == first_meta
    (tmp_path / "scene.glb").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="hash mismatch"):
        finalize_scene(tmp_path, render=False)


def test_no_known_support_uses_scene_bottom_without_moving_objects():
    scene, objects = fixture_scene((2,), ("unknown",))
    original = copy.deepcopy(objects)
    report = correct_placement(scene, objects)
    assert report["floor_y"] == 2
    assert report["floor_source"] == "scene_bottom"
    assert objects[0]["transform"]["matrix"] == original[0]["transform"]["matrix"]
