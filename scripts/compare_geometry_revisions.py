"""Compare completed revisions on identical inference assets, without a quality pass."""
import argparse
from pathlib import Path
import numpy as np
from mapmaker.scene_run import read, write, sha


def compare(candidate, baseline):
    current, previous = [read(p/'scene_metadata.json') for p in (candidate,baseline)]
    for path, meta in ((candidate,current),(baseline,previous)):
        assert sha(path/'scene.glb') == meta['placement']['scene_sha256']
        assert sha(path/meta['input_image']) == meta['input_sha256'], 'Input bytes differ from recorded hash'
        assert sha(path/meta['pointmap']['asset']) == meta['pointmap']['sha256'], 'Pointmap bytes differ from recorded hash'
    assert current['input_sha256']==previous['input_sha256']
    assert current['pointmap']['sha256']==previous['pointmap']['sha256']
    objects = lambda m: {o['id']:o for o in m['objects'] if o['status']=='generated'}
    a,b = objects(current),objects(previous)
    assert a.keys()==b.keys(), 'Selected objects changed; compare extraction separately'
    changed=[]
    camera_changed=[]
    current_common=np.asarray(current['placement']['common_transform'])
    previous_common=np.asarray(previous['placement']['common_transform'])
    current_inverse=np.linalg.inv(current_common)
    previous_inverse=np.linalg.inv(previous_common)
    for oid,obj in a.items():
        assert obj['mask_sha256']==b[oid]['mask_sha256']
        assert sha(candidate/obj['mask']) == obj['mask_sha256'], 'Candidate mask hash mismatch'
        assert sha(baseline/b[oid]['mask']) == b[oid]['mask_sha256'], 'Baseline mask hash mismatch'
        assert sha(candidate/obj['asset'])==sha(baseline/b[oid]['asset'])
        if not np.allclose(obj['transform']['matrix'],b[oid]['transform']['matrix'],atol=1e-7,rtol=0):
            changed.append(oid)
        if not np.allclose(current_inverse@np.asarray(obj['transform']['matrix']),
                           previous_inverse@np.asarray(b[oid]['transform']['matrix']),atol=1e-7,rtol=0):
            camera_changed.append(oid)
    def details(meta):
        placement=meta['placement']
        poses=placement.get('pose_refinement',{}).get('changes',[])
        overlap=placement.get('overlap_refinement',{})
        overlap_records=[]
        for record in overlap.get('records',[]):
            if not record.get('applied'):
                continue
            selected=record['candidates'][record['selected_candidate']]
            assert selected['accepted'] and selected['depth']['accepted']
            assert selected['overlap']['accepted'] and selected['support']['accepted']
            overlap_records.append(dict(object_id=record['object_id'],
                depth=selected['depth'], overlap=selected['overlap'], support=selected['support'],
                before_projection=selected['before_projection'],after_projection=selected['after_projection']))
        assert {r['object_id'] for r in overlap_records}=={r['object_id'] for r in overlap.get('changes',[])}, 'Incomplete overlap application evidence'
        return dict(pose_ids=[r['object_id'] for r in poses],
            overlap_repairs=overlap_records,overlap_scope=overlap.get('scope'),
            repaired_pairs=[dict(object_id=r['object_id'],other_id=c['other_id'])
                for r in poses for c in r['collision_checks'] if c.get('penetration_confirmed') and c['after']=='clear'],
            contact_changes=placement['contacts']['changes'],
            surfaces=[dict(node=s['node'],kind=s['kind']) for s in meta['structure']['surfaces']])
    return dict(run=candidate.name, candidate_scene_sha256=sha(candidate/'scene.glb'),
        baseline_scene_sha256=sha(baseline/'scene.glb'), objects=len(a),
        input_pointmap_masks_and_object_assets_unchanged=True,
        changed_transforms=changed,changed_camera_frame_transforms=camera_changed,
        global_transform_changed=not np.allclose(current_common,previous_common,atol=1e-7,rtol=0),
        before=details(previous),after=details(current),
        fresh_gpu_inference=False,quality_gate_passed=False,
        limitation='Stored inference geometry only; no claim of small-object recall, unseen shape, or support correctness')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate',type=Path)
    parser.add_argument('baseline',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    write(args.output,compare(args.candidate,args.baseline))
