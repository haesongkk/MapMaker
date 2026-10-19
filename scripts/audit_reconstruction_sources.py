"""Replay source evidence and retry scheduling on saved development assets."""
import argparse
import copy
from pathlib import Path
import numpy as np
import trimesh
from PIL import Image
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_replay import pose_matrix
from mapmaker.scene_transfer import safe_name
from mapmaker.reconstruction_evidence import candidate_faces, assess
from mapmaker.reconstruction_schedule import ranked_depth_retries


def audit(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(source):
        raise ValueError('Use a new report outside the immutable source run')
    meta = read(source/'scene_metadata.json')
    source_hash = sha(source/'scene.glb')
    assert source_hash == meta['placement']['scene_sha256']
    assert sha(source/meta['input_image']) == meta['input_sha256']
    assert sha(source/meta['pointmap']['asset']) == meta['pointmap']['sha256']
    with np.load(source/meta['pointmap']['asset'], allow_pickle=False) as data:
        points = data['points']
    report = dict(completed=False,source=str(source),source_scene_sha256=source_hash,
        source_metadata_sha256=sha(source/'scene_metadata.json'),input_sha256=meta['input_sha256'],
        records=[],quality_gate_passed=False,fresh_gpu_inference=False,
        scope='Existing generated object subset only; no missing-object recovery or new-inference quality claim',
        code_sha256={p:sha(p) for p in ['mapmaker/reconstruction_evidence.py',
            'mapmaker/scene_visible_depth.py','mapmaker/reconstruction_schedule.py',__file__]})
    objects=[]
    write(output,report)
    for obj in meta['objects']:
        if obj.get('status') != 'generated':continue
        original = obj.get('reconstruction_review',{}).get('original_artifact')
        asset = original['asset'] if original else obj['asset']
        safe_name(asset)
        expected = original['sha256'] if original else obj['asset_sha256']
        assert sha(source/asset)==expected
        if original:
            assert sha(source/original['pose'])==original['pose_sha256']
        pose = read(source/original['pose']) if original else obj['pose']
        assert sha(source/obj['mask'])==obj['mask_sha256']
        mask=np.asarray(Image.open(source/obj['mask']).convert('L').resize(
            points.shape[1::-1],Image.Resampling.NEAREST))>0
        mesh=trimesh.load(source/asset,force='scene',process=False)
        evidence=assess(candidate_faces(mesh,pose_matrix(pose)),points,mask,visible_depth=True)
        objects.append(dict(id=obj['id'],status='generated',mask_sha256=obj['mask_sha256'],
            reconstruction_review=dict(original=evidence)))
        report['records'].append(dict(object_id=obj['id'],mask_sha256=obj['mask_sha256'],
            baseline_asset_sha256=expected,evidence=evidence))
        write(output,report)
        print(source.name,obj['id'],evidence.get('retry_recommended'),flush=True)
    selected=ranked_depth_retries(objects)
    renamed=copy.deepcopy(list(reversed(objects)))
    for i,obj in enumerate(renamed):obj['id']=str(i)
    assert [o['mask_sha256'] for o in selected]==[o['mask_sha256'] for o in ranked_depth_retries(renamed)]
    assert sha(source/'scene.glb')==source_hash
    report.update(completed=True,selected_ids=[o['id'] for o in selected],
        selected_mask_hashes=[o['mask_sha256'] for o in selected],names_and_input_order_invariant=True)
    write(output,report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    audit(args.source,args.output)
