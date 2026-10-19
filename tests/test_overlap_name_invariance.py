"""Exercise accepted native repair with real depth/projection and renamed labels."""
import copy
import json

import numpy as np
import pytest
import trimesh
from PIL import Image

pytest.importorskip('manifold3d')
from mapmaker.scene_overlap_refinement import refine_overlaps


def test_accepted_overlap_repair_is_invariant_to_display_names(tmp_path):
    yy, xx = np.mgrid[:64, :64]
    points = np.stack(((xx-32)*2/50, (yy-32)*2/50, np.full_like(xx, 2)), axis=-1)
    mask = (xx >= 1) & (xx <= 50) & (yy >= 7) & (yy <= 57)
    Image.fromarray(mask.astype(np.uint8)*255).save(tmp_path/'mask.png')
    scene = trimesh.Scene()
    for oid, center in [('a', (0, 0, 3.08)), ('b', (1.5, 0, 3.08))]:
        mesh = trimesh.creation.box(extents=(2, 2, 2))
        mesh.apply_translation(center)
        scene.add_geometry(mesh, node_name=oid)
    move = np.eye(4)
    move[:3, 3] = [-.22, 0, -.08]
    placement = dict(common_transform=np.eye(4).tolist(), contact_tolerance=.001,
                     pose_refinement=dict(records=[dict(object_id='a', applied=False,
                         starting_world_transform=np.eye(4).tolist(), rejected_collision_candidates=[dict(
                             camera_transform=move.tolist(), collision_checks=[dict(other_id='b', before='intersection')])])]))
    results = []
    matrices = []
    for names in [('plant', 'cabinet'), ('TV', 'shelf'), ('', ''), (None, None)]:
        objects = [dict(id='a', name=names[0], mask='mask.png', placement={}, transform={}),
                   dict(id='b', name=names[1], placement={}, transform={})]
        if names == (None, None):
            for obj in objects:
                del obj['name']
        current = scene.copy()
        report = refine_overlaps(tmp_path, current, objects, points, copy.deepcopy(placement), {'surfaces': []})
        assert len(report['changes']) == 1, report
        # A valid original depth fit must not be perturbed solely because the
        # neighboring alternatives happen to be enumerated first.
        np.testing.assert_array_equal(current.graph['a'][0], move)
        selected = report['records'][0]['candidates'][0]
        assert selected['accepted'] and selected['origin'] == 'depth_fit_seed'
        assert selected['depth']['after'] < 1e-12
        results.append(json.dumps(report, sort_keys=True))
        matrices.append(current.graph['a'][0])
        np.testing.assert_array_equal(current.graph['b'][0], scene.graph['b'][0])
    assert all(result == results[0] for result in results)
    for matrix in matrices[1:]:
        np.testing.assert_array_equal(matrices[0], matrix)


def test_strict_overlap_rejects_original_visible_depth_regression(tmp_path,monkeypatch):
    from mapmaker.scene_run import sha
    yy,xx=np.mgrid[:64,:64]
    points=np.stack(((xx-32)*2/50,(yy-32)*2/50,np.full_like(xx,2)),axis=-1)
    mask=(xx>=1)&(xx<=50)&(yy>=7)&(yy<=57)
    Image.fromarray(mask.astype(np.uint8)*255).save(tmp_path/'mask.png')
    original=mask.copy();original[:,1:4]=False
    Image.fromarray(original.astype(np.uint8)*255).save(tmp_path/'original.png')
    scene=trimesh.Scene()
    for oid,center in [('a',(0,0,3.08)),('b',(1.5,0,3.08))]:
        mesh=trimesh.creation.box(extents=(2,2,2));mesh.apply_translation(center)
        scene.add_geometry(mesh,node_name=oid)
    move=np.eye(4);move[:3,3]=[-.22,0,-.08]
    placement=dict(common_transform=np.eye(4).tolist(),contact_tolerance=.001,
        pose_refinement=dict(records=[dict(object_id='a',applied=False,
            starting_world_transform=np.eye(4).tolist(),rejected_collision_candidates=[dict(
                camera_transform=move.tolist(),collision_checks=[dict(other_id='b',before='intersection')])])]))
    objects=[dict(id='a',mask='mask.png',placement={},transform={},mask_expansion=dict(
        original_mask='original.png',original_sha256=sha(tmp_path/'original.png'))),
        dict(id='b',placement={},transform={})]
    calls={}
    def assess(faces,points,mask,**kwargs):
        assert kwargs['visible_depth']
        count=int(mask.sum());calls[count]=calls.get(count,0)+1
        value=.06 if count==int(original.sum()) and calls[count]>1 else .05
        return dict(accepted=True,projection=dict(accepted=True,silhouette_iou=1.,mask_covered_fraction=1.),
            normalized_depth_median=.05,normalized_depth_p90=.1,
            visible_depth=dict(available=True,matched_rays=256,hit_fraction=1.,normalized_median=value,normalized_p90=.1))
    monkeypatch.setattr('mapmaker.reconstruction_evidence.assess_masks',
        lambda faces,points,masks,**kw: {k:assess(faces,points,m,**kw) for k,m in masks.items()})
    result=refine_overlaps(tmp_path,scene,objects,points,placement,{'surfaces':[]},strict_source=True)
    assert not result['changes']
    rejected=[c for r in result['records'] for c in r['candidates'] if c.get('reason')=='strict_source_regression']
    assert rejected and set(calls)=={int(mask.sum()),int(original.sum())}
    np.testing.assert_array_equal(scene.graph['a'][0],np.eye(4))
