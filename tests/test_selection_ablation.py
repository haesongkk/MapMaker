import copy
import numpy as np
import pytest
import trimesh
from mapmaker.scene_run import read,write,sha
from mapmaker.scene_replay import pose_matrix
from scripts.replay_reconstruction_selection import replay_originals


def test_counterfactual_reverts_only_selected_candidate_and_keeps_durable_provenance(tmp_path):
    source=tmp_path/'source';(source/'objects/candidates/item').mkdir(parents=True)
    (source/'input.png').write_bytes(b'immutable input')
    artifacts=[];poses=[]
    for seed,size in ((42,1),(43,2)):
        asset=f'objects/candidates/item/seed_{seed}.glb';pose=asset+'.pose.json'
        trimesh.creation.box(extents=[size]*3).export(source/asset)
        value=dict(rotation=[[1,0,0,0]],scale=[[1,1,1]],translation=[[size,0,3]])
        write(source/pose,value);poses.append(value)
        artifacts.append(dict(asset=asset,sha256=sha(source/asset),pose=pose,pose_sha256=sha(source/pose)))
    def evidence(coverage,depth):return dict(accepted=True,
        projection=dict(mask_covered_fraction=coverage,silhouette_iou=coverage),
        normalized_depth_median=depth,normalized_depth_p90=depth*2)
    chosen=dict(id='item',status='generated',asset=artifacts[1]['asset'],asset_sha256=artifacts[1]['sha256'],
        pose=poses[1],placement=dict(original_matrix=pose_matrix(poses[1]).tolist()),
        reconstruction_review=dict(selected_seed=43,attempted_seeds=[42,43],
            original=evidence(.3,.3),alternative=evidence(.8,.1),
            original_artifact=artifacts[0],alternative_artifact=artifacts[1]))
    other=copy.deepcopy(chosen);other.update(id='unrelated');other.pop('reconstruction_review')
    write(source/'scene_metadata.json',dict(input_image='input.png',input_sha256=sha(source/'input.png'),
        objects=[chosen,other],reconstruction_review=dict(maximum_extra_inferences=1,extra_inferences_used=1)))
    trimesh.creation.box().export(source/'scene.glb')
    before={p.name:sha(p) for p in source.iterdir() if p.is_file()}
    output=tmp_path/'replay';meta=replay_originals(source,output,finalize=False)
    assert meta['selection_ablation']['reverted_object_ids']==['item']
    assert meta['objects'][0]['asset_sha256']==artifacts[0]['sha256']
    assert meta['objects'][1]['asset_sha256']==artifacts[1]['sha256']
    scene=trimesh.load(output/'scene.glb',force='scene',process=False)
    np.testing.assert_allclose(scene.graph['item'][0],pose_matrix(poses[0]))
    np.testing.assert_allclose(scene.graph['unrelated'][0],pose_matrix(poses[1]))
    provenance=read(output/'replay_provenance.json')
    assert sha(output/provenance['source_metadata_asset'])==provenance['source_metadata_sha256']
    assert before=={p.name:sha(p) for p in source.iterdir() if p.is_file()}
    retained=tmp_path/'retained'
    retained_meta=replay_originals(source,retained,finalize=False,revert=False)
    assert retained_meta['selection_ablation']['reverted_object_ids']==[]
    assert retained_meta['selection_ablation']['selection']=='retained_selection'
    retained_scene=trimesh.load(retained/'scene.glb',force='scene',process=False)
    np.testing.assert_allclose(retained_scene.graph['item'][0],pose_matrix(poses[1]))
    with pytest.raises(ValueError,match='No selected alternative'):
        replay_originals(output,tmp_path/'redundant',finalize=False)
