"""Compare completed pose-on/off replays without treating them as GPU quality."""
import argparse
from pathlib import Path
import numpy as np
from mapmaker.scene_run import read,write,sha


def compare(candidate,baseline):
    a,b=[read(root/'scene_metadata.json') for root in (candidate,baseline)]
    assert a['input_sha256']==b['input_sha256']
    for root,meta in ((candidate,a),(baseline,b)):
        assert sha(root/'scene.glb')==meta['placement']['scene_sha256']
    assert b['placement']['pose_refinement']['ablation_disabled']
    generated=lambda m:{o['id']:o for o in m['objects'] if o['status']=='generated'}
    current,previous=generated(a),generated(b)
    assert current.keys()==previous.keys(), 'Pose ablation must not change selected objects'
    for key in current:
        assert current[key]['mask_sha256']==previous[key]['mask_sha256']
    changes=a['placement']['pose_refinement']['changes']
    moved=[]
    for oid,obj in current.items():
        if not np.allclose(obj['transform']['matrix'],previous[oid]['transform']['matrix'],atol=1e-7):
            moved.append(oid)
    repaired=[dict(object_id=r['object_id'],other_id=c['other_id'],evidence=c)
        for r in changes for c in r['collision_checks']
        if c.get('penetration_confirmed') and c['after']=='clear']
    return dict(run=candidate.name,objects=len(current),selected_objects_and_masks_unchanged=True,
        candidate_sha256=sha(candidate/'scene.glb'),baseline_sha256=sha(baseline/'scene.glb'),
        changed_transforms=moved,pose_changes=len(changes),confirmed_repaired_pairs=repaired,
        source_projection_checks=[dict(object_id=r['object_id'],before=r['before_projection'],after=r['after_projection']) for r in changes],
        contact_changes_before=b['placement']['contacts']['changes'],contact_changes_after=a['placement']['contacts']['changes'],
        fresh_gpu_inference=False,quality_gate_passed=False,
        limitation='Same recovered inference assets; preserved masks do not prove recall or support correctness')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('candidate',type=Path);p.add_argument('baseline',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();write(a.output,compare(a.candidate,a.baseline))
