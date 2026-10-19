import numpy as np
import pytest
import trimesh
from mapmaker.scene_registration import propose_rigid_transform


def observations(mesh):
    rng = np.random.default_rng(41)
    faces = mesh.triangles[rng.integers(0, len(mesh.faces), 1500)]
    weights = rng.dirichlet([1,1,1], len(faces))
    return np.sum(faces*weights[:,:,None], axis=1)


def test_rigid_fit_improves_withheld_points_without_deforming_mesh():
    mesh = trimesh.creation.box(extents=[1, 2, 3])
    points = observations(mesh)
    pose = trimesh.transformations.rotation_matrix(np.deg2rad(6), [0, 0, 1])
    pose[:3,3] = [.1, .06, 0]
    points = trimesh.transform_points(points, pose)
    original = mesh.vertices.copy()
    transform, report = propose_rigid_transform(mesh, points)
    assert transform is not None
    assert report['after'] < report['before']*.8
    assert report['rotation_degrees'] <= 8
    assert report['center_displacement'] <= report['translation_budget']
    np.testing.assert_allclose(transform[:3,:3].T@transform[:3,:3], np.eye(3), atol=1e-8)
    np.testing.assert_array_equal(mesh.vertices, original)
    reordered, _ = propose_rigid_transform(mesh, points[::-1])
    np.testing.assert_allclose(transform, reordered)


def test_correct_geometry_is_not_changed_and_far_observations_are_rejected():
    mesh = trimesh.creation.box(extents=[1, 2, 3])
    points = observations(mesh)
    transform, evidence = propose_rigid_transform(mesh, points)
    assert transform is None and evidence['reason'] == 'already_matches_observed_depth'
    transform, _ = propose_rigid_transform(mesh, points+[10,0,0])
    assert transform is None


@pytest.mark.parametrize('axis', [0, 1, 2])
@pytest.mark.parametrize('origin', [[0, 0, 0], [3, -2, 5]])
def test_partial_step_improves_depth_when_full_step_exceeds_motion_budget(axis, origin):
    mesh = trimesh.creation.box(extents=[2, 2, 2])
    y, z = np.meshgrid(np.linspace(-.75, .75, 20), np.linspace(-.75, .75, 20))
    points = np.column_stack([np.full(y.size, 1.4), y.ravel(), z.ravel()])
    points = np.roll(points, axis, axis=1)+origin
    mesh.apply_translation(origin)
    original = mesh.vertices.copy()
    transform, report = propose_rigid_transform(mesh, points)
    assert transform is not None
    assert 0 < report['center_displacement'] <= report['translation_budget'] < .4
    assert report['after'] < report['before']*.4
    assert report['after_p90'] < report['before_p90']
    assert report['rotation_degrees'] <= 8
    np.testing.assert_allclose(transform[:3,:3].T@transform[:3,:3], np.eye(3), atol=1e-8)
    np.testing.assert_array_equal(mesh.vertices, original)
    reordered, _ = propose_rigid_transform(mesh, points[::-1])
    np.testing.assert_allclose(transform, reordered)
