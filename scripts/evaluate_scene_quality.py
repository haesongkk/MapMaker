"""Replay frozen saved scenes; no GPU, no production changes, no recall claims."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import time
import numpy as np
import trimesh
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_placement import finalize_scene, correct_placement, align_objects
from mapmaker.scene_contacts import improve_contacts


def evaluate(manifest_path, output):
    manifest=read(manifest_path)
    output.mkdir(parents=True,exist_ok=True)
    results=[]
    for record in manifest['saved_regression']:
        source=Path(record['source'])
        if sha(source/'scene.glb') != record['scene_sha256'] or sha(source/'scene_metadata.json') != record['metadata_sha256']:
            raise ValueError(f'Frozen baseline changed: {source}')
        target=output/source.name
        target.mkdir(exist_ok=False)
        shutil.copy2(source/'scene.glb',target/'scene.glb')
        shutil.copy2(source/'scene_metadata.json',target/'scene_metadata.json')
        original=read(source/'scene_metadata.json')
        # Legacy saved runs without a pointmap explicitly skip room estimation.
        if original.get('pointmap'):
            raise ValueError('Copy complete pointmap/mask inputs before replaying a spatial run')
        start=time.monotonic()
        placement=finalize_scene(target,render=False)
        meta=read(target/'scene_metadata.json')
        digest=sha(target/'scene.glb');finalize_scene(target,render=False)
        assert sha(target/'scene.glb')==digest
        scene=trimesh.load(source/'scene.glb',force='scene',process=False)
        objects=[copy.deepcopy(o) for o in original['objects'] if o['status']=='generated']
        for obj in objects:obj.pop('name',None)
        p=correct_placement(scene,objects);align_objects(scene,objects,p);improve_contacts(scene,objects,p)
        generated={o['id']:o for o in meta['objects'] if o['status']=='generated'}
        for obj in objects:
            assert np.allclose(obj['transform']['matrix'],generated[obj['id']]['transform']['matrix'],atol=1e-6)
        result=dict(source=str(source),output=str(target),objects=len(objects),
            label_invariance=True,idempotent=True,glb_roundtrip=True,
            contact_changes=placement['contacts']['changes'],
            unresolved_contacts=len(placement['contacts']['unresolved_props']),
            remaining_overlap_candidates=len(placement['contacts']['remaining_aabb_overlaps']),
            structure_status=meta['structure']['status'],elapsed_seconds=round(time.monotonic()-start,2))
        results.append(result)
        write(output/'report.json',dict(status='running',results=results))
        print(json.dumps({k:result[k] for k in ('source','objects','elapsed_seconds')},ensure_ascii=False),flush=True)
    report=dict(status='PASS',scope='saved-artifact geometry regression only',results=results,
        fresh_gpu_inference=False,holdout_evaluated=False,recall_measured=False,
        deployment_gate='BLOCKED_PENDING_REAL_GPU_AND_ANNOTATED_HOLDOUT',
        limitation='Names/roundtrip/idempotence are checked; correctness of inferred relations requires image annotations.')
    write(output/'report.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,default=Path('docs/QUALITY_EVALUATION_MANIFEST.json'))
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();evaluate(a.manifest,a.output)
