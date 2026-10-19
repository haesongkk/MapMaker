import numpy as np
from PIL import Image
import trimesh
from mapmaker.scene_pose_refinement import refine_poses
from mapmaker.scene_run import sha


def setup_case(tmp_path,monkeypatch):
    Image.fromarray(np.full((10,10),255,np.uint8)).save(tmp_path/'mask.png')
    y,x=np.mgrid[:10,:10];points=np.stack([x*.02,y*.02,np.full_like(x,3.)],-1)
    scene=trimesh.Scene(base_frame='Scene')
    mesh=trimesh.creation.box(extents=[1,1,.2]);mesh.apply_translation([0,.5,3.1])
    scene.add_geometry(mesh,node_name='target')
    obj=dict(id='target',mask='mask.png',transform={},placement={})
    monkeypatch.setattr('mapmaker.scene_pose_refinement.silhouette_evidence',lambda *a:dict(accepted=True,silhouette_iou=1.,mask_covered_fraction=1.))
    return scene,obj,points


def test_pose_cannot_lift_an_already_supported_object(tmp_path,monkeypatch):
    scene,obj,points=setup_case(tmp_path,monkeypatch)
    floor=trimesh.Trimesh([[-2,0,1],[2,0,1],[-2,0,5],[2,0,5]],[[0,1,2],[1,3,2]],process=False)
    scene.add_geometry(floor,node_name='floor')
    transform=np.eye(4);transform[1,3]=.05
    monkeypatch.setattr('mapmaker.scene_pose_refinement.propose_similarity_transform',lambda *a,**kw:(transform,dict(reason='test_candidate')))
    report=refine_poses(tmp_path,scene,[obj],points,dict(common_transform=np.eye(4),contact_tolerance=.001),dict(surfaces=[dict(node='floor')]))
    assert not report['changes']
    assert report['records'][0]['reason']=='pose_preservation_failed'
    assert not report['records'][0]['rejected_preservation_candidates'][0]['support']['accepted']
    np.testing.assert_array_equal(scene.graph['target'][0],np.eye(4))


def test_strict_pose_rejects_original_mask_regression_when_current_mask_passes(tmp_path,monkeypatch):
    scene,obj,points=setup_case(tmp_path,monkeypatch)
    original=np.full((10,10),255,np.uint8);original[:,:2]=0
    Image.fromarray(original).save(tmp_path/'original.png')
    obj['mask_expansion']=dict(original_mask='original.png',original_sha256=sha(tmp_path/'original.png'))
    transform=np.eye(4);transform[0,3]=.01
    monkeypatch.setattr('mapmaker.scene_pose_refinement.propose_similarity_transform',lambda *a,**kw:(transform,dict(reason='test_candidate')))
    calls={}
    def assess(faces,points,mask,**kwargs):
        count=int(mask.sum());calls[count]=calls.get(count,0)+1
        value=.06 if count==80 and calls[count]>1 else .05
        return dict(accepted=True,projection=dict(accepted=True,silhouette_iou=1.,mask_covered_fraction=1.),
            normalized_depth_median=.05,normalized_depth_p90=.1,
            visible_depth=dict(available=True,matched_rays=256,hit_fraction=1.,normalized_median=value,normalized_p90=.1))
    monkeypatch.setattr('mapmaker.reconstruction_evidence.assess_masks',
        lambda faces,points,masks,**kw: {k:assess(faces,points,m,**kw) for k,m in masks.items()})
    report=refine_poses(tmp_path,scene,[obj],points,dict(common_transform=np.eye(4),contact_tolerance=.001),{},strict_source=True)
    assert calls=={100:2,80:2}
    assert not report['changes'] and report['records'][0]['reason']=='pose_preservation_failed'
    np.testing.assert_array_equal(scene.graph['target'][0],np.eye(4))
