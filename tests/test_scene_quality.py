import copy
import numpy as np
import pytest
import trimesh
from mapmaker.scene_contacts import improve_contacts, surface_height
from mapmaker.scene_placement import correct_placement, align_objects, object_vertices
from mapmaker.mask_selection import select_masks


def scene_of(specs):
    scene = trimesh.Scene(base_frame='Scene'); objects = []
    for i, (name, size, center) in enumerate(specs):
        oid = f'{name}_{i}'
        matrix = trimesh.transformations.translation_matrix(center)
        scene.graph.update(frame_from='Scene', frame_to=oid, matrix=matrix)
        scene.add_geometry(trimesh.creation.box(extents=size), parent_node_name=oid, node_name=oid+'mesh')
        objects.append(dict(id=oid, name=name, transform={}, pose={'original': True}))
    placement = correct_placement(scene, objects)
    align_objects(scene, objects, placement)
    return scene, objects, placement


@pytest.mark.parametrize('bottom', [1.3, .95])
def test_floating_and_penetrating_props_contact_surface(bottom):
    scene, objects, placement = scene_of([('table', [2, 1, 2], [0, .5, 0]),
                                         ('book', [.4, .2, .4], [0, bottom+.1, 0])])
    geometry = {k: m.vertices.copy() for k,m in scene.geometry.items()}
    before = copy.deepcopy(objects[1]['pose'])
    improve_contacts(scene, objects, placement)
    assert object_vertices(scene, objects[1]['id'])[:, 1].min() == pytest.approx(1)
    assert objects[1]['pose'] == before
    for k,m in scene.geometry.items(): np.testing.assert_array_equal(m.vertices, geometry[k])
    assert objects[1]['placement']['contacts'][0]['support_id'] == objects[0]['id']


def test_large_gap_or_outside_support_unchanged():
    for center in ([0, 3, 0], [3, 1.3, 0]):
        scene, objects, placement = scene_of([('table', [2,1,2], [0,.5,0]), ('book', [.4,.2,.4], center)])
        before = scene.graph[objects[1]['id']][0].copy()
        improve_contacts(scene, objects, placement)
        np.testing.assert_array_equal(before, scene.graph[objects[1]['id']][0])
        assert objects[1]['id'] in placement['contacts']['unresolved_props']


def test_mesh_hole_is_not_bbox_support():
    left = trimesh.creation.box(extents=[.2,1,2]); left.apply_translation([-.9,.5,0])
    right = left.copy(); right.apply_translation([1.8,0,0])
    assert surface_height(np.concatenate([left.triangles, right.triangles]), [0,0]) is None


def test_confirmed_shallow_intersection_resolved_but_deep_interlock_unchanged():
    for x, moved in ((1.95, True), (.5, False)):
        scene, objects, placement = scene_of([('cabinet', [2,1,2], [0,.5,0]), ('cabinet', [2,1,2], [x,.5,0])])
        improve_contacts(scene, objects, placement)
        assert bool(placement['contacts']['changes']) is moved
        assert bool(placement['contacts']['remaining_aabb_overlaps']) is not moved
        for o in objects: assert object_vertices(scene,o['id'])[:,1].min() == pytest.approx(0)


def test_masks_reserve_small_slots_reject_noise_and_same_label_duplicate():
    raw=[]
    for i in range(13):
        mask=np.zeros((1000,1000),bool); mask[i*60:i*60+55,:100]=True
        raw.append((dict(name='chair',candidate_index=i,confidence=.9),mask))
    small=np.zeros((1000,1000),bool);small[900:925,:25]=True
    raw.append((dict(name='cup',candidate_index=0,confidence=.85),small))
    raw.append((dict(name='cup',candidate_index=1,confidence=.9),small.copy()))
    noise=np.zeros((1000,1000),bool);noise[950:975,:25]=True
    raw.append((dict(name='bottle',candidate_index=0,confidence=.7),noise))
    selected=select_masks(raw,1000000)
    assert len(selected)==12
    assert sum(r['name']=='cup' for r,m in selected)==1
    assert not any(r['name']=='bottle' for r,m in selected)


def test_distinct_small_prop_inside_furniture_mask_survives():
    large=np.zeros((1000,1000),bool); large[:200,:200]=True
    small=np.zeros_like(large);small[20:45,20:45]=True
    raw=[(dict(name='table',candidate_index=0,confidence=.9),large),
         (dict(name='cup',candidate_index=0,confidence=.9),small)]
    assert len(select_masks(raw,1000000))==2


def test_prop_is_not_lowered_into_another_object():
    scene, objects, placement = scene_of([
        ('table', [2,1,2], [0,.5,0]),
        ('book', [.4,.2,.4], [0,1.5,0]),
        ('unknown', [.4,.2,.4], [0,1.1,0]),
    ])
    before = scene.graph[objects[1]['id']][0].copy()
    improve_contacts(scene, objects, placement)
    np.testing.assert_array_equal(before, scene.graph[objects[1]['id']][0])
    assert objects[1]['id'] in placement['contacts']['unresolved_props']


def test_ambiguous_supports_do_not_move_prop():
    scene, objects, placement = scene_of([
        ('table', [2,1,2], [0,.5,0]),
        ('cabinet', [2,1,2], [0,.5,0]),
        ('book', [.4,.2,.4], [0,1.4,0]),
    ])
    before = scene.graph[objects[2]['id']][0].copy()
    improve_contacts(scene, objects, placement)
    np.testing.assert_array_equal(before, scene.graph[objects[2]['id']][0])
    assert objects[2]['id'] in placement['contacts']['unresolved_props']


def test_furniture_separation_does_not_hit_third_object():
    scene, objects, placement = scene_of([
        ('cabinet', [2,1,2], [0,.5,0]),
        ('cabinet', [2,1,2], [1.95,.5,0]),
        ('unknown', [.03,1,2], [-1.04,.5,0]),
    ])
    before = scene.graph[objects[0]['id']][0].copy()
    improve_contacts(scene, objects, placement)
    np.testing.assert_array_equal(before, scene.graph[objects[0]['id']][0])


def test_small_slot_budget_returns_unused_slots_and_excludes_tiny_noise():
    raw=[]
    for i in range(12):
        mask=np.zeros((1000,1000),bool); mask[i*60:i*60+55,:100]=True
        raw.append((dict(name='chair',candidate_index=i,confidence=.9),mask))
    noise=np.zeros((1000,1000),bool);noise[950:955,:5]=True
    raw.append((dict(name='cup',candidate_index=0,confidence=.99),noise))
    selected=select_masks(raw,1000000)
    assert len(selected)==12
    assert all(r['name']=='chair' for r,m in selected)
