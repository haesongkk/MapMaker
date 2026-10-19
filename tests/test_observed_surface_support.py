import copy

import numpy as np
import pytest
import trimesh

from mapmaker.scene_contacts import improve_contacts
from mapmaker.scene_placement import object_vertices
from test_scene_quality import scene_of


def fixture(kind='flat'):
    scene, objects, placement = scene_of([
        ('patch', [2, 1, 2], [0, .5, 0]),
        ('item', [.4, .2, .4], [0, 1.14, 0]),
    ])
    vertices = [[-1, .5, -1], [1, .5, -1], [1, .5, 1], [-1, .5, 1]]
    faces = [[0, 1, 2], [0, 2, 3]]
    if kind == 'wall':
        vertices = [[-1, -.5, 0], [1, -.5, 0], [1, 1, 0], [-1, 1, 0]]
    if kind == 'hole':
        vertices = [[.5, .5, -1], [1, .5, -1], [1, .5, 1], [.5, .5, 1]]
    if kind == 'upper':
        vertices += [[-.5, .65, -.5], [.5, .65, -.5], [.5, .65, .5], [-.5, .65, .5]]
        faces += [[4, 5, 6], [4, 6, 7]]
    sid = objects[0]['id']
    _, key = scene.graph[sid+'mesh']
    scene.geometry[key] = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    bounds = np.stack([object_vertices(scene, sid).min(0), object_vertices(scene, sid).max(0)])
    surface = dict(node=sid, kind='observed', bounds=bounds.tolist(),
        evidence='valid_unclaimed_shared_pointmap_neighbors',
        triangle_support='all_original_pixels_in_triangle_observed_and_unmasked')
    return scene, objects[1:], placement, dict(surfaces=[surface])


def test_observed_horizontal_patch_supports_without_plane_classification():
    scene, objects, placement, structure = fixture()
    alternate, renamed, other = scene.copy(), copy.deepcopy(objects), copy.deepcopy(placement)
    for obj in renamed:
        obj.pop('name')
    improve_contacts(scene, objects, placement, structure, source_guard=lambda *args: dict(accepted=True))
    improve_contacts(alternate, renamed, other, structure, source_guard=lambda *args: dict(accepted=True))
    assert object_vertices(scene, objects[0]['id'])[:, 1].min() == pytest.approx(1.)
    assert placement['contacts']['relations'][0]['support_id'] == structure['surfaces'][0]['node']
    assert placement['contacts']['source_checks']
    assert placement['contacts'] == other['contacts']
    np.testing.assert_array_equal(scene.graph[objects[0]['id']][0], alternate.graph[objects[0]['id']][0])


@pytest.mark.parametrize('kind', ['wall', 'hole', 'upper', 'unverified', 'source_reject'])
def test_observed_patch_does_not_bypass_support_or_collision_evidence(kind):
    scene, objects, placement, structure = fixture(kind)
    before = scene.graph[objects[0]['id']][0].copy()
    if kind == 'unverified':
        structure['surfaces'][0].pop('evidence')
    guard = lambda *args: dict(accepted=kind != 'source_reject', reason='test_source_rejection')
    improve_contacts(scene, objects, placement, structure, source_guard=guard)
    np.testing.assert_array_equal(before, scene.graph[objects[0]['id']][0])
    assert not placement['contacts']['changes']
