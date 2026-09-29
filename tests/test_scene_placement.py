import copy

import numpy as np
import pytest
import trimesh

from mapmaker.scene_placement import (
    FLOOR_NODE, align_objects, add_floor, bounds_of, correct_placement, finalize_scene, object_vertices,
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


def test_shared_alignment_preserves_relative_transforms_meshes_and_pose():
    scene, objects = fixture_scene()
    common = trimesh.transformations.rotation_matrix(.6, [1, 0, 1])
    common[:3, 3] = [2, -4, 7]
    for obj in objects:
        scene.graph.update(frame_from="Scene", frame_to=obj["id"], matrix=common @ np.array(obj["transform"]["matrix"]))
    originals = {o["id"]: scene.graph[o["id"]][0].copy() for o in objects}
    geometry = {k: v.vertices.copy() for k, v in scene.geometry.items()}
    poses = [copy.deepcopy(o["pose"]) for o in objects]
    report = correct_placement(scene, objects)
    np.testing.assert_allclose(report["mean_up_after"], [0, 1, 0], atol=1e-12)
    assert report["minimum_y_after"] == pytest.approx(0, abs=1e-12)
    assert report["individual_correction"] is False
    for i, obj in enumerate(objects):
        before = originals[obj["id"]]
        after = scene.graph[obj["id"]][0]
        np.testing.assert_allclose(after, np.array(report["common_transform"]) @ before, atol=1e-12)
        np.testing.assert_allclose(np.linalg.inv(scene.graph[objects[0]["id"]][0]) @ after,
                                   np.linalg.inv(originals[objects[0]["id"]]) @ before, atol=1e-12)
        assert obj["pose"] == poses[i]
    for k, v in scene.geometry.items():
        np.testing.assert_array_equal(v.vertices, geometry[k])
    # Global grounding leaves original differences between object bottoms intact.
    assert report["metrics"]["after"]["floating_count"] == 2


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
    before = object_vertices(scene, "object_0").copy()
    report = correct_placement(scene, objects)
    expected = trimesh.transform_points(before, report["common_transform"])
    np.testing.assert_allclose(object_vertices(scene, "object_0"), expected, atol=1e-12)
    assert object_vertices(scene, "object_0")[:, 1].min() == pytest.approx(0., abs=1e-12)


def test_all_categories_equal_weight_after_normalizing_scale():
    scene, objects = fixture_scene((0, 10), ("chair", "unknown"))
    root = trimesh.transformations.rotation_matrix(np.pi / 3, [0, 0, 1])
    root[:3, :3] @= np.diag([2, 20, 4])
    root[:3, 3] = [3, 10, 0]
    scene.graph.update(frame_from="Scene", frame_to="object_1", matrix=root)
    report = correct_placement(scene, objects)
    np.testing.assert_allclose(report["mean_up_before"], [-.5, np.sqrt(3)/2, 0], atol=1e-12)
    assert report["object_ids"] == ["object_0", "object_1"]
    np.testing.assert_allclose(objects[1]["transform"]["scale"], [2, 20, 4])
    matrix = trimesh.transformations.quaternion_matrix(objects[1]["transform"]["rotation_quaternion_wxyz"])
    np.testing.assert_allclose(matrix[:3, :3] @ np.diag([2, 20, 4]), np.array(objects[1]["transform"]["matrix"])[:3, :3], atol=1e-12)


@pytest.mark.parametrize("angle", [0., np.pi, np.pi - 1e-8])
def test_parallel_and_antiparallel_up(angle):
    scene, objects = fixture_scene((2,), ("unknown",))
    root = trimesh.transformations.rotation_matrix(angle, [1, 0, 0])
    scene.graph.update(frame_from="Scene", frame_to="object_0", matrix=root)
    report = correct_placement(scene, objects)
    np.testing.assert_allclose(report["mean_up_after"], [0, 1, 0], atol=1e-10)
    assert np.linalg.det(report["rotation_matrix"]) == pytest.approx(1.)
    assert report["minimum_y_after"] == pytest.approx(0.)


@pytest.mark.parametrize("angle", [np.pi, np.pi - 1e-7])
def test_cancelled_mean_fails_before_mutation(angle):
    scene, objects = fixture_scene((0, 0), ("chair", "unknown"))
    root = trimesh.transformations.rotation_matrix(angle, [1, 0, 0])
    scene.graph.update(frame_from="Scene", frame_to="object_1", matrix=root)
    original = copy.deepcopy(objects)
    with pytest.raises(ValueError, match="nearly cancels"):
        correct_placement(scene, objects)
    assert objects == original
    np.testing.assert_array_equal(scene.graph['object_1'][0], root)


def test_invalid_transform_and_empty_scene_fail():
    scene, objects = fixture_scene((0,), ("chair",))
    root = np.eye(4); root[1, 1] = 0
    scene.graph.update(frame_from="Scene", frame_to="object_0", matrix=root)
    with pytest.raises(ValueError, match="Invalid object transform"):
        correct_placement(scene, objects)
    with pytest.raises(ValueError, match="empty"):
        correct_placement(scene, [])


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


@pytest.mark.parametrize("version", [1, 2, 3])
def test_old_placement_version_is_not_reapplied(tmp_path, version):
    write(tmp_path / "scene_metadata.json", {"placement": {"version": version}})
    with pytest.raises(ValueError, match="uncorrected"):
        finalize_scene(tmp_path, render=False)


@pytest.mark.parametrize("angle", [.65, np.pi])
def test_individual_upright_around_own_pivot_and_ground(angle):
    scene, objects = fixture_scene((2, 3, 4), ("chair", "table", "television"))
    root = trimesh.transformations.rotation_matrix(angle, [1, 0, 0])
    root[:3, :3] @= np.diag([2, 3, 4])
    root[:3, 3] = [7, 9, -4]
    scene.graph.update(frame_from="Scene", frame_to="object_0", matrix=root)
    # Off-center child geometry must be grounded using actual vertices.
    scene.graph.update(frame_from="object_0", frame_to="object_0__mesh",
                       matrix=trimesh.transformations.translation_matrix([2, -3, 1]))
    poses = copy.deepcopy([o["pose"] for o in objects])
    vertices = {k: g.vertices.copy() for k, g in scene.geometry.items()}
    report = correct_placement(scene, objects)
    before = {o["id"]: scene.graph[o["id"]][0].copy() for o in objects}
    align_objects(scene, objects, report)
    for o in objects[:2]:
        mat = scene.graph[o["id"]][0]
        np.testing.assert_allclose(mat[:3, 1] / np.linalg.norm(mat[:3, 1]), [0, 1, 0], atol=1e-12)
        np.testing.assert_allclose(mat[[0, 2], 3], before[o["id"]][[0, 2], 3], atol=1e-12)
        np.testing.assert_allclose(np.linalg.norm(mat[:3, :3], axis=0), np.linalg.norm(before[o["id"]][:3, :3], axis=0))
        assert object_vertices(scene, o["id"])[:, 1].min() == pytest.approx(0., abs=1e-12)
    np.testing.assert_allclose(scene.graph['object_2'][0][:3, 3], before['object_2'][:3, 3], atol=1e-12)
    up = scene.graph['object_2'][0][:3, 1]
    np.testing.assert_allclose(up / np.linalg.norm(up), [0, 1, 0], atol=1e-12)
    assert [o["pose"] for o in objects] == poses
    for k, g in scene.geometry.items():np.testing.assert_array_equal(g.vertices, vertices[k])
    assert report["individual_metrics"]["after"]["floating_count"] == 0
    assert report["individual_metrics"]["after"]["penetrating_count"] == 0
    add_floor(scene, objects, report)
    floor = bounds_of(object_vertices(scene, FLOOR_NODE))
    for o in objects:
        b = bounds_of(object_vertices(scene, o["id"]))
        assert np.all(floor[0, [0, 2]] < b[0, [0, 2]])
        assert np.all(floor[1, [0, 2]] > b[1, [0, 2]])


def test_all_non_floor_categories_rotate_without_grounding():
    scene, objects = fixture_scene((0, 1, 2, 3), ("pillow", "plant", "book", "living room"))
    for i, o in enumerate(objects):
        matrix = trimesh.transformations.rotation_matrix(.3 * (i + 1), [1, 0, 0])
        matrix[:3, 3] = [i*3, i+2, 0]
        scene.graph.update(frame_from="Scene", frame_to=o["id"], matrix=matrix)
    report = correct_placement(scene, objects)
    before = {o["id"]: scene.graph[o["id"]][0].copy() for o in objects}
    align_objects(scene, objects, report)
    assert report["grounded_object_ids"] == []
    assert len(report["individual_object_ids"]) == 4
    for o in objects:
        mat = scene.graph[o["id"]][0]
        np.testing.assert_allclose(mat[:3, 3], before[o["id"]][:3, 3], atol=1e-12)
        np.testing.assert_allclose(mat[:3, 1]/np.linalg.norm(mat[:3, 1]), [0, 1, 0], atol=1e-12)
        assert o["placement"]["individual"]["ground_shift_y"] == 0
        assert not o["placement"]["individual"]["grounded"]


def test_individual_rotation_preserves_heading_when_already_upright():
    scene, objects = fixture_scene((3,), ("chair",))
    root = trimesh.transformations.rotation_matrix(.8, [0, 1, 0])
    root[:3, 3] = [10, 9, -4]
    scene.graph.update(frame_from="Scene", frame_to="object_0", matrix=root)
    report = correct_placement(scene, objects)
    before = scene.graph['object_0'][0].copy()
    align_objects(scene, objects, report)
    np.testing.assert_allclose(scene.graph['object_0'][0][:3, :3], before[:3, :3], atol=1e-12)
