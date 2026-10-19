import numpy as np
import trimesh
import copy
import pytest

from mapmaker.reconstruction_evidence import assess, prefer_alternative


@pytest.mark.parametrize('visible_depth', [False, True])
def test_grouped_masks_match_independent_evidence_and_isolate_geometry(monkeypatch, visible_depth):
    import mapmaker.reconstruction_evidence as evidence
    y,x=np.mgrid[:80,:80]
    points=np.stack([(x-40)/40,(y-40)/40,np.full_like(x,3)],-1)
    masks={'current':(x>=24)&(x<=56)&(y>=24)&(y<=56),
        'original':(x>=30)&(x<=50)&(y>=30)&(y<=50)}
    mesh=trimesh.creation.box(extents=[2,2,1]);mesh.apply_translation([0,0,2.5])
    faces=mesh.triangles.copy()
    build=evidence._evidence_mesh
    built=[]
    def tracked(faces):
        result=build(faces);built.append(result);return result
    monkeypatch.setattr(evidence,'_evidence_mesh',tracked)
    expected={k:assess(faces,points,m,visible_depth=visible_depth) for k,m in masks.items()}
    assert len(built)==2
    built.clear()
    actual=evidence.assess_masks(faces,points,masks,visible_depth=visible_depth)
    assert actual==expected and len(built)==1
    first=built[0]
    faces += [0,0,.2]
    changed=evidence.assess_masks(faces,points,masks,visible_depth=visible_depth)
    assert len(built)==2 and built[1] is not first
    assert changed=={k:assess(faces,points,m,visible_depth=visible_depth) for k,m in masks.items()}
    assert changed!=actual


def test_grouped_rejected_depth_does_not_build_geometry(monkeypatch):
    import mapmaker.reconstruction_evidence as evidence
    def unexpected(_):
        raise AssertionError('Rejected evidence should not construct a mesh')
    monkeypatch.setattr(evidence,'_evidence_mesh',unexpected)
    points=np.zeros((10,10,3))
    assert evidence.assess_masks([],points,{})=={}
    result=evidence.assess_masks([],points,{'invalid':np.ones((10,10),bool)})
    assert result['invalid']==dict(accepted=False,reason='insufficient_reliable_depth')


def test_candidate_evidence_uses_exported_child_and_root_pose():
    from mapmaker.reconstruction_evidence import candidate_faces
    mesh=trimesh.creation.box(extents=[1,2,3])
    scene=trimesh.Scene()
    child=trimesh.transformations.rotation_matrix(.4,[0,1,0]);child[:3,3]=[2,0,1]
    scene.add_geometry(mesh,transform=child)
    root=trimesh.transformations.rotation_matrix(.2,[1,0,0]);root[:3,3]=[0,3,2]
    expected=trimesh.transform_points(mesh.vertices,root@child)[mesh.faces]
    np.testing.assert_allclose(candidate_faces(scene,root),expected)
    np.testing.assert_allclose(candidate_faces(mesh,np.eye(4)),mesh.triangles)


def test_visible_mismatch_requests_retry_but_hidden_extension_does_not():
    y,x=np.mgrid[:80,:80]
    points=np.stack([(x-40)/40,(y-40)/40,np.full_like(x,3)],-1)
    mask=np.zeros((80,80),bool);mask[24:57,24:57]=True
    vertices=np.array([[-.4,-.4,3],[.4,-.4,3],[.4,.4,3],[-.4,.4,3]])
    faces=vertices[[[0,1,2],[0,2,3]]]
    good=assess(faces,points,mask)
    wrong=assess(faces+[2,0,0],points,mask)
    extended=faces.copy();extended[:,:,:2]*=2
    over=assess(extended,points,mask)
    assert good['accepted'] and not good['retry_recommended']
    assert wrong['retry_recommended']
    assert not over['retry_recommended']
    assert prefer_alternative(wrong,good)
    assert not prefer_alternative(good,wrong)
    assert not prefer_alternative(good,over)


def test_unreliable_depth_cannot_authorize_retry_selection():
    y,x=np.mgrid[:80,:80]
    points=np.stack([x/80,y/80,np.ones_like(x)],-1).astype(float)
    points[:20]=np.nan
    result=assess(np.array([[[0,0,1],[1,0,1],[0,1,1]]]),points,np.ones((80,80),bool))
    assert not result['accepted']
    assert not prefer_alternative(result,result)


def test_first_surface_mismatch_requests_retry_even_with_good_silhouette():
    y,x=np.mgrid[:80,:80]
    points=np.stack([(x-40)/40,(y-40)/40,np.full_like(x,3)],-1)
    mask=np.zeros((80,80),bool);mask[30:51,30:51]=True
    mesh=trimesh.creation.box(extents=[2,2,1]);mesh.apply_translation([0,0,2.5])
    baseline=assess(mesh.triangles,points,mask)
    measured=assess(mesh.triangles,points,mask,visible_depth=True)
    assert not baseline['retry_recommended']
    assert measured['retry_recommended']
    assert measured['reason']=='visible_first_surface_depth_mismatch'


def test_visible_selection_requires_nonregression_in_every_existing_measure():
    original=dict(accepted=True,projection=dict(mask_covered_fraction=1.,silhouette_iou=.8),
        normalized_depth_median=.02,normalized_depth_p90=.04,
        visible_depth=dict(available=True,matched_rays=256,hit_fraction=1.,normalized_median=.2,normalized_p90=.3))
    better=copy.deepcopy(original)
    better['visible_depth'].update(normalized_median=.1,normalized_p90=.2)
    assert prefer_alternative(original,better)
    for section,key,value in [('projection','silhouette_iou',.79),('visible_depth','hit_fraction',.9),('visible_depth','normalized_p90',.31),('visible_depth','normalized_median',None)]:
        worse=copy.deepcopy(better);worse[section][key]=value
        assert not prefer_alternative(original,worse)
    missing=copy.deepcopy(better);missing.pop('visible_depth')
    assert not prefer_alternative(original,missing)
    worse=copy.deepcopy(better);worse['normalized_depth_p90']=.041
    assert not prefer_alternative(original,worse)
