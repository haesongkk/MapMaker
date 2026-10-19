import copy
import numpy as np
import pytest
import trimesh
from PIL import Image
from mapmaker.scene_run import sha
from mapmaker.reconstruction_deferred import review_ranked_scene
from mapmaker.reconstruction_review import validate_review_artifacts


def evidence(error, better=False):
    return dict(accepted=True,retry_recommended=True,
        projection=dict(mask_covered_fraction=.9 if better else .7,silhouette_iou=.8 if better else .6),
        normalized_depth_median=.02 if better else .1,normalized_depth_p90=.05 if better else .2,
        visible_depth=dict(available=True,matched_rays=200,hit_fraction=.9,
            normalized_median=error,normalized_p90=error*2))


@pytest.mark.parametrize('mode',['accepted','worse','exception','context_loss'])
def test_deferred_retries_preserve_baselines_and_update_matching_output_only(tmp_path,mode):
    (tmp_path/'objects').mkdir();(tmp_path/'masks').mkdir()
    objects=[];outputs=[]
    pose=dict(rotation=[1,0,0,0],translation=[0,0,3],scale=[1,1,1])
    for i,error in enumerate([.15,.4,.5]):
        asset=f'objects/{i}.glb';mask=f'masks/{i}.png'
        trimesh.creation.box(extents=[i+1]*3).export(tmp_path/asset)
        pixels=np.zeros((8,8),np.uint8);pixels[:i+2,:]=255
        Image.fromarray(pixels).save(tmp_path/mask)
        objects.append(dict(id=str(i),status='generated',mask=mask,mask_sha256=sha(tmp_path/mask),
            asset=asset,asset_sha256=sha(tmp_path/asset),pose=copy.deepcopy(pose),
            reconstruction_review=dict(selected_seed=42,attempted_seeds=[42],original=evidence(error))))
        outputs.append(dict(pose,gaussian=f'original-{i}'))
    meta=dict(objects=objects,reconstruction_review=dict(maximum_extra_inferences=2,
        extra_inferences_used=0,visible_depth=True,order='descending_visible_depth_error_then_mask_sha256'))
    originals=[(tmp_path/o['asset']).read_bytes() for o in objects]
    calls=[]
    def generate(obj,mask,seed):
        assert seed==43
        assert np.array_equal(mask,np.asarray(Image.open(tmp_path/obj['mask']))>0)
        calls.append(obj['id'])
        if mode=='exception':raise RuntimeError('simulated GPU failure')
        return dict(pose,translation=[1,0,3],gaussian='candidate-'+obj['id'],
            glb=trimesh.creation.box(extents=[.5]*3))
    def measure(candidate,mask):
        return evidence(.03,True) if mode in ('accepted','context_loss') else evidence(.9)
    def pose_of(candidate):return {key:candidate[key] for key in pose}
    guard=(lambda obj,old,new: dict(accepted=False,reason='sampled_contact_lost')) if mode=='context_loss' else None
    review_ranked_scene(tmp_path,meta,objects,outputs,generate,measure,pose_of,context_guard=guard)
    assert calls==['2','1']
    assert meta['reconstruction_review']['extra_inferences_used']==2
    assert (tmp_path/objects[0]['asset']).read_bytes()==originals[0]
    for i in (1,2):
        obj=objects[i];review=obj['reconstruction_review']
        assert (tmp_path/review['original_artifact']['asset']).read_bytes()==originals[i]
        if mode=='accepted':
            assert outputs[i]['gaussian']==f'candidate-{i}' and obj['pose']['translation']==[1,0,3]
            assert review['selected_seed']==43
        else:
            assert outputs[i]['gaussian']==f'original-{i}' and obj['pose']==pose
            assert (tmp_path/obj['asset']).read_bytes()==originals[i]
            assert review['selected_seed']==42
            if mode=='context_loss':assert review['reason']=='context_regression_original_preserved'
    assert validate_review_artifacts(tmp_path,meta)['extra_inferences']==2
