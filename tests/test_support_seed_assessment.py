import numpy as np
import trimesh
from mapmaker.scene_supported_refinement import support_seed_assessment


def test_stable_contact_and_missing_surface_are_distinguished():
    floor=trimesh.creation.box(extents=[4,.1,4]);floor.apply_translation([0,-.05,0])
    body=trimesh.creation.box(extents=[1,1,1]);body.apply_translation([0,.5,0])
    seeds, evidence=support_seed_assessment(body.vertices,floor.triangles,.14,.001)
    assert not seeds
    assert evidence['reason']=='already_supported'
    floor.apply_translation([10,0,0])
    seeds, evidence=support_seed_assessment(body.vertices,floor.triangles,.14,.001)
    assert not seeds
    assert evidence['reason']=='no_admissible_pose_seed'
    assert evidence['contact']['reason']=='missing_support_surface'
    assert all(d['reason']=='insufficient_observed_foot_samples' for d in evidence['seed_diagnostics'])


def test_diagnostics_do_not_mutate_geometry():
    floor=trimesh.creation.box(extents=[4,.1,4])
    body=trimesh.creation.box(extents=[1,1,1]);body.apply_translation([0,2,0])
    before=body.vertices.copy()
    seeds, evidence=support_seed_assessment(body.vertices,floor.triangles,.14,.001)
    np.testing.assert_array_equal(body.vertices,before)
    assert not seeds
    assert evidence['contact']['reason']=='support_shift_out_of_bounds'


def test_level_floating_body_has_a_bounded_translation_seed():
    from mapmaker.scene_geometry import support_translation
    floor=trimesh.creation.box(extents=[4,.1,4]);floor.apply_translation([0,-.05,0])
    body=trimesh.creation.box();body.apply_translation([0,.54,0])
    before=body.vertices.copy()
    seeds,evidence=support_seed_assessment(body.vertices,floor.triangles,.14,.001)
    translations=[(t,e) for t,e in seeds if e['method']=='foot_surface_gap_translation']
    assert len(translations)==1 and evidence['reason']=='pose_seeds_available'
    transform,detail=translations[0]
    np.testing.assert_allclose(transform[:3,:3],np.eye(3))
    np.testing.assert_allclose(transform[:3,3],[0,-.04,0],atol=1e-12)
    moved=trimesh.transform_points(body.vertices,transform)
    delta,_=support_translation(moved,floor.triangles,.14,.001)
    assert np.linalg.norm(delta)<=.001
    assert detail['requires_source_and_collision_validation']
    np.testing.assert_array_equal(body.vertices,before)


def test_translation_seed_cannot_exceed_vertex_motion_budget():
    floor=trimesh.creation.box(extents=[4,.1,4]);floor.apply_translation([0,-.05,0])
    body=trimesh.creation.box();body.apply_translation([0,.7,0])
    seeds,_=support_seed_assessment(body.vertices,floor.triangles,.3,.001)
    assert not seeds


def test_new_translation_proposal_does_not_bypass_source_gate(tmp_path,monkeypatch):
    from PIL import Image
    from mapmaker.scene_supported_refinement import refine_supported_poses
    floor=trimesh.creation.box(extents=[4,.1,4]);floor.apply_translation([0,-.05,3])
    body=trimesh.creation.box();body.apply_translation([0,.54,3])
    scene=trimesh.Scene();scene.add_geometry(body,node_name='body')
    scene.add_geometry(floor,node_name='floor')
    Image.fromarray(np.full((10,10),255,np.uint8)).save(tmp_path/'mask.png')
    y,x=np.mgrid[:10,:10]
    points=np.stack([(x-5)/10,y/10,np.full_like(x,2.5,dtype=float)],-1)
    calls=[]
    def rejected(faces,points,masks,**kwargs):
        calls.append(True)
        return {k:dict(accepted=False,reason='test_source_failure') for k in masks}
    monkeypatch.setattr('mapmaker.scene_supported_refinement.assess_masks',rejected)
    obj=dict(id='body',mask='mask.png',placement={},transform={})
    report=refine_supported_poses(tmp_path,scene,[obj],points,
        dict(contact_tolerance=.001,common_transform=np.eye(4)),
        dict(surfaces=[dict(node='floor',normal=[0,1,0],point=[0,0,3])]))
    assert len(calls)>=2 and not report['changes']
    candidates=report['records'][0]['candidates']
    assert candidates and all(c['reason']=='source_regression' for c in candidates)
    assert any(c['seed']['method']=='foot_surface_gap_translation' for c in candidates)
    np.testing.assert_array_equal(scene.graph['body'][0],np.eye(4))
