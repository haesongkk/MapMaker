import numpy as np
import trimesh

from mapmaker.scene_pose_search import SourceDepthScreen, translation_alternatives


def test_depth_screen_accepts_correct_pose_and_rejects_opposite_move():
    mesh = trimesh.creation.box(extents=[2, 2, 2])
    y, z = np.meshgrid(np.linspace(-.8, .8, 16), np.linspace(-.8, .8, 16))
    observed = np.column_stack([np.full(y.size, 1.05), y.ravel(), z.ravel()])
    transform = np.eye(4)
    transform[0, 3] = .05
    screen = SourceDepthScreen(mesh, observed)
    assert screen.assess(transform)['accepted']
    transform[0, 3] = -.05
    assert not screen.assess(transform)['accepted']


def test_observation_order_does_not_change_depth_evidence():
    mesh = trimesh.creation.box(extents=[2, 2, 2])
    y, z = np.meshgrid(np.linspace(-.8, .8, 16), np.linspace(-.8, .8, 16))
    observed = np.column_stack([np.full(y.size, 1.05), y.ravel(), z.ravel()])
    transform = np.eye(4)
    transform[0, 3] = .05
    assert SourceDepthScreen(mesh, observed).assess(transform) == SourceDepthScreen(mesh, observed[::-1]).assess(transform)


def test_alternatives_never_exceed_original_motion_budget():
    mesh = trimesh.creation.box(extents=[2, 1, .5])
    mesh.apply_translation([10, 20, 30])
    base = np.eye(4)
    base[0, 3] = np.linalg.norm(mesh.extents)*.07
    alternatives = list(translation_alternatives(base, mesh))
    assert alternatives
    np.testing.assert_array_equal(alternatives[0][0], base)
    assert alternatives[0][1]['origin'] == 'depth_fit_seed'
    for transform, _ in alternatives:
        actual = np.linalg.norm(trimesh.transform_points(mesh.bounds.mean(0)[None], transform)[0]-mesh.bounds.mean(0))
        assert actual <= np.linalg.norm(mesh.extents)*.08
