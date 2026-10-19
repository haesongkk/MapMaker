import copy
import numpy as np
import pytest
from mapmaker.mask_geometry import review_composites
from mapmaker.scene_contacts import improve_contacts
from test_scene_quality import scene_of
from PIL import Image
from mapmaker.mask_geometry import refine_selected


def fixture():
    a = np.zeros((40, 40), bool)
    b = a.copy()
    a[2:12, 2:12] = True
    b[20:30, 20:30] = True
    y, x = np.mgrid[:40, :40]
    points = np.stack([x / 40, y / 40, np.ones_like(x)], axis=-1)
    points[b, 2] = 3
    return {'a': a, 'b': b, 'parent': a | b}, points


@pytest.mark.parametrize('scale', [.01, 1., 100.])
def test_exact_disconnected_union_is_redundant_and_order_independent(scale):
    masks, points = fixture()
    review = review_composites(masks, points * scale)
    assert review == review_composites(dict(reversed(list(masks.items()))), points * scale)
    assert review[0]['action'] == 'suppress'
    renamed = review_composites({str(i): m for i, m in enumerate(masks.values())}, points * scale)
    assert renamed[0]['action'] == 'suppress'


@pytest.mark.parametrize('ambiguity', ['bridge', 'same_depth', 'invalid_depth', 'tiny_child', 'overlap'])
def test_ambiguous_parent_and_small_objects_are_retained(ambiguity):
    masks, points = fixture()
    if ambiguity == 'bridge':
        masks['parent'][11:21, 10:22] = True
    elif ambiguity == 'same_depth':
        points[..., 2] = 1
    elif ambiguity == 'invalid_depth':
        points[masks['a']] = np.nan
    elif ambiguity == 'tiny_child':
        masks['b'][:] = False
        masks['b'][20, 20] = True
        masks['parent'] = masks['a'] | masks['b']
    else:
        masks['b'][2:5, 2:5] = True
    assert all(r['action'] == 'retain_ambiguous' for r in review_composites(masks, points))


def test_contact_rejections_are_explained_and_name_independent():
    scene, objects, placement = scene_of([
        ('base', [2, 1, 2], [0, .5, 0]),
        ('floating', [.4, .2, .4], [0, 5, 0]),
    ])
    other = scene.copy()
    renamed, report = copy.deepcopy(objects), copy.deepcopy(placement)
    for obj in renamed:
        obj.pop('name', None)
    improve_contacts(scene, objects, placement)
    improve_contacts(other, renamed, report)
    contacts = placement['contacts']
    assert contacts['rejections'] == report['contacts']['rejections']
    assert contacts['rejection_counts']['support_shift_out_of_bounds'] == 1
    assert contacts['rejection_counts']['no_supported_candidate'] == 2
    assert {r['object_id'] for r in contacts['rejections'] if r['stage'] == 'selection'} == set(contacts['unresolved_props'])
    assert not contacts['changes']


def test_refinement_keeps_children_and_mask_files(tmp_path):
    masks, points = fixture()
    meta = {'objects': []}
    original = {}
    for key, mask in masks.items():
        file = tmp_path / f'{key}.png'
        Image.fromarray(mask.astype(np.uint8) * 255).save(file)
        original[file] = file.read_bytes()
        meta['objects'].append(dict(id=key, name='arbitrary', mask=file.name, status='selected'))
    refine_selected(tmp_path, meta, points, np.full((40, 40, 3), 128, np.uint8))
    by_id = {o['id']: o for o in meta['objects']}
    assert by_id['parent']['status'] == 'duplicate'
    assert by_id['a']['status'] == by_id['b']['status'] == 'selected'
    assert set(by_id['parent']['duplicate_of']) == {'a', 'b'}
    assert all(file.read_bytes() == content for file, content in original.items())
