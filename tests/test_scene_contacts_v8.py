import copy

import numpy as np
import pytest
import trimesh

from mapmaker.scene_contacts import improve_contacts
from mapmaker.scene_geometry import support_translation
from mapmaker.scene_placement import object_vertices
from test_scene_quality import scene_of


def test_open_support_upper_surface_blocks_body_even_without_volume():
    def run(upper_surface):
        scene,objects,placement=scene_of([
            ('support',[2,2,2],[0,1,0]),('prop',[.4,.6,.4],[0,.7,0])])
        vertices=[[-1,-.5,-1],[1,-.5,-1],[1,-.5,1],[-1,-.5,1]]
        faces=[[0,1,2],[0,2,3]]
        if upper_surface:
            vertices += [[-.3,.05,-.3],[.3,.05,-.3],[.3,.05,.3],[-.3,.05,.3]]
            faces += [[4,5,6],[4,6,7]]
        _,key=scene.graph[objects[0]['id']+'mesh']
        scene.geometry[key]=trimesh.Trimesh(vertices=vertices,faces=faces,process=False)
        assert not scene.geometry[key].is_watertight
        before=scene.graph[objects[1]['id']][0].copy()
        improve_contacts(scene,objects,placement)
        return scene,objects,placement,before
    scene,objects,placement,before=run(True)
    np.testing.assert_array_equal(scene.graph[objects[1]['id']][0],before)
    assert any(r['object_id']==objects[1]['id'] and r['reason']=='support_body_mesh_collision'
               for r in placement['contacts']['rejections'])
    scene,objects,placement,_=run(False)
    assert object_vertices(scene,objects[1]['id'])[:,1].min()==pytest.approx(.5)


@pytest.mark.parametrize('scale', [.01, 1., 100.])
@pytest.mark.parametrize('gap', [0., .04])
def test_low_shelf_inside_tall_enclosure(scale, gap):
    scene, objects, placement = scene_of([
        ('arbitrary', [2, 4, 2], [0, 2, 0]),
        ('other', [.4, .2, .4], [0, .6 + gap, 0]),
    ])
    parts = []
    for size, center in [([2, .1, 2], [0, -1.55, 0]),
                         ([.1, 4, 2], [-.95, 0, 0]),
                         ([.1, 4, 2], [.95, 0, 0])]:
        part = trimesh.creation.box(extents=size)
        part.apply_translation(center)
        parts.append(part)
    node = objects[0]['id'] + 'mesh'
    _, key = scene.graph[node]
    scene.geometry[key] = trimesh.util.concatenate(parts)
    for mesh in scene.geometry.values():
        mesh.vertices *= scale
    for obj in objects:
        matrix = scene.graph[obj['id']][0].copy()
        matrix[:3, 3] *= scale
        scene.graph.update(frame_to=obj['id'], matrix=matrix)
    placement['contact_tolerance'] *= scale
    alternate = scene.copy()
    renamed, report = copy.deepcopy(objects), copy.deepcopy(placement)
    for obj in renamed:
        obj.pop('name')
    improve_contacts(scene, objects, placement)
    improve_contacts(alternate, renamed, report)
    assert object_vertices(scene, objects[1]['id'])[:, 1].min() == pytest.approx(.5 * scale)
    assert placement['contacts']['relations'][-1]['support_id'] == objects[0]['id']
    for obj in objects:
        np.testing.assert_allclose(scene.graph[obj['id']][0], alternate.graph[obj['id']][0])


def test_large_support_does_not_grant_tiny_prop_room_sized_movement():
    scene, objects, placement = scene_of([
        ('one', [100, 1, 100], [0, .5, 0]),
        ('two', [.1, .1, .1], [0, 2.05, 0]),
    ])
    before = scene.graph[objects[1]['id']][0].copy()
    improve_contacts(scene, objects, placement)
    np.testing.assert_array_equal(before, scene.graph[objects[1]['id']][0])
    assert any(r['reason'] == 'support_shift_out_of_bounds' for r in placement['contacts']['rejections'])


def test_stable_three_contacts_allow_a_lower_noncontacting_surface():
    # Three supports surround the bounds center; the fourth sampled surface is
    # lower. Requiring all surface heights to agree incorrectly rejects this.
    sites = [(-1., -1.), (1., -1.), (0., 1.), (0., 0.)]
    feet, faces = [], []
    for index, (x, z) in enumerate(sites):
        foot = trimesh.creation.box(extents=[.08, .5, .08])
        foot.apply_translation([x, .35, z])
        feet.extend(foot.vertices)
        patch = trimesh.creation.box(extents=[.2, .1, .2])
        patch.apply_translation([x, -.05 if index < 3 else -.2, z])
        faces.extend(patch.triangles)
    delta, evidence = support_translation(np.asarray(feet), np.asarray(faces), .2, .01)
    np.testing.assert_allclose(delta, [0, -.1, 0], atol=1e-8)
    assert evidence['offset_spread'] > .1


def test_one_high_corner_does_not_support_an_entire_object():
    feet, faces = [], []
    for index, (x, z) in enumerate([(-1., -1.), (1., -1.), (-1., 1.), (1., 1.)]):
        foot = trimesh.creation.box(extents=[.08, .5, .08])
        foot.apply_translation([x, .35, z]); feet.extend(foot.vertices)
        patch = trimesh.creation.box(extents=[.2, .1, .2])
        patch.apply_translation([x, -.05 if index == 0 else -.2, z]); faces.extend(patch.triangles)
    delta, evidence = support_translation(np.asarray(feet), np.asarray(faces), .2, .01)
    assert delta is None and evidence['reason'] == 'nonuniform_support_height'


def test_overhanging_body_can_rest_on_stable_real_contacts():
    # The tips overhang; the three inner feet enclose center and bear its load.
    feet=[]
    for x,z in [(-.5,-.5),(.5,-.5),(0,.5),(-1,0),(1,0)]:
        part=trimesh.creation.box(extents=[.08,.5,.08]);part.apply_translation([x,.35,z]);feet.extend(part.vertices)
    support=trimesh.creation.box(extents=[1.3,.1,1.3]);support.apply_translation([0,-.05,0])
    delta,evidence=support_translation(np.asarray(feet),support.triangles,.2,.01)
    np.testing.assert_allclose(delta,[0,-.1,0],atol=1e-8)
    assert evidence['missing_queries'] > 0
