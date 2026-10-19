"""Analytic endpoint cases for the experimental overlap screen."""
import numpy as np
import pytest
import trimesh

pytest.importorskip('manifold3d')
from mapmaker.scene_overlap import OverlapSnapshot


def box(center=(0, 0, 0), size=2):
    mesh = trimesh.creation.box(extents=[size] * 3)
    mesh.apply_translation(center)
    return mesh.triangles.copy()


def move(x):
    result = np.eye(4)
    result[0, 3] = x
    return result


def pair(**others):
    return OverlapSnapshot(dict(moving=box(), fixed=box((1.5, 0, 0)), **others))


def test_partial_repair_uses_actual_overlap_volume():
    evidence = pair().assess('moving', move(-.25))
    assert evidence['accepted']
    check = evidence['checks'][0]
    assert check['before'] == pytest.approx(2.)
    assert check['after'] == pytest.approx(1.)


def test_reducing_one_overlap_cannot_create_another():
    evidence = pair(third=box((-2.75, 0, 0))).assess('moving', move(-.9))
    assert not evidence['accepted']
    assert evidence['reason'] == 'increased_closed_overlap'


def test_shrinking_an_enclosed_body_is_not_repair():
    scene = OverlapSnapshot(dict(moving=box(size=1), enclosing=box(size=4)))
    transform = np.diag([.8, .8, .8, 1.])
    evidence = scene.assess('moving', transform)
    assert not evidence['accepted']
    assert evidence['checks'][0]['relative_after'] == pytest.approx(1.)


def test_open_surface_is_not_filled_or_treated_as_solid():
    triangle = np.array([[[0, 3, 0], [3, 0, 0], [3, 3, 0]]], float)
    evidence = pair(surface=triangle).assess('moving', move(-.25))
    assert evidence['accepted']
    assert evidence['checks'][-1]['status'] == 'clear_surface_and_components'


def test_open_surface_crossing_vetoes_closed_volume_improvement():
    triangle = np.array([[[-3, -3, 0], [3, -3, 0], [0, 3, 0]]], float)
    evidence = pair(surface=triangle).assess('moving', move(-.25))
    assert not evidence['accepted']
    assert evidence['reason'] == 'open_surface_not_clear'


def test_disconnected_open_component_inside_mover_is_not_missed():
    triangles = np.array([[[0, 3, 0], [3, 0, 0], [3, 3, 0]],
                          [[0, 0, 0], [.1, 0, 0], [0, .1, 0]]], float)
    evidence = pair(surface=triangles).assess('moving', move(-.25))
    assert not evidence['accepted']
    assert evidence['reason'] == 'open_surface_enclosed_by_mover'


def test_invalid_closed_body_does_not_become_an_open_surface():
    evidence = OverlapSnapshot(dict(moving=box(), fixed=box((1.5, 0, 0))[:, ::-1])).assess('moving', move(-.25))
    assert not evidence['accepted']
    assert evidence['reason'] == 'fixed_volume_unavailable'


def test_snapshot_owns_geometry_and_names_are_only_keys():
    faces = {'first': box(), 'second': box((1.5, 0, 0))}
    snapshot = OverlapSnapshot(faces)
    faces['first'][:] = 0
    evidence = snapshot.assess('first', move(-.25))
    renamed = OverlapSnapshot({'': box(), 'anything': box((1.5, 0, 0))}).assess('', move(-.25))
    assert evidence['accepted'] == renamed['accepted'] is True
    assert evidence['checks'][0]['after'] == pytest.approx(renamed['checks'][0]['after'])


def test_nonuniform_deformation_is_rejected():
    with pytest.raises(ValueError, match='uniform scale'):
        pair().assess('moving', np.diag([1., .8, 1., 1.]))


def test_exhausted_triangle_budget_is_unknown_not_clear():
    triangle = np.array([[[-3, -3, 0], [3, -3, 0], [0, 3, 0]]], float)
    scene = OverlapSnapshot(dict(moving=box(), fixed=box((1.5, 0, 0)), surface=triangle), max_pairs=0)
    evidence = scene.assess('moving', move(-.25))
    assert not evidence['accepted']
    assert evidence['checks'][-1]['status'] == 'unknown'


def test_open_moving_surface_has_no_invented_volume():
    triangle = np.array([[[0, 3, 0], [3, 0, 0], [3, 3, 0]]], float)
    evidence = OverlapSnapshot(dict(moving=triangle, fixed=box())).assess('moving', move(-.25))
    assert not evidence['accepted']
    assert evidence['reason'] == 'moving_volume_unavailable'
