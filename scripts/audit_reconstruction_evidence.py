"""Diagnose gross source mismatch on saved development meshes; no regeneration."""
import argparse
from pathlib import Path
import numpy as np
from PIL import Image
import trimesh
from mapmaker.reconstruction_evidence import assess
from mapmaker.scene_geometry import triangles
from mapmaker.scene_run import read, write, sha


def audit(run, output):
    meta=read(run/'scene_metadata.json'); digest=sha(run/'scene.glb')
    points=np.load(run/meta['pointmap']['asset'],allow_pickle=False)['points']
    scene=trimesh.load(run/'scene.glb',force='scene',process=False)
    inverse=np.linalg.inv(meta['placement']['common_transform'])
    rows=[]
    for obj in meta['objects']:
        if obj['status']!='generated': continue
        mask=np.asarray(Image.open(run/obj['mask']).convert('L').resize(
            points.shape[:2][::-1], Image.Resampling.NEAREST))>0
        faces=triangles(scene,obj['id'])
        faces=trimesh.transform_points(faces.reshape(-1,3),inverse).reshape(-1,3,3)
        evidence=assess(faces,points,mask)
        rows.append(dict(object_id=obj['id'],**evidence))
        print(dict(object_id=obj['id'],retry=evidence.get('retry_recommended')),flush=True)
        write(output,dict(source_scene_sha256=digest,objects=rows,
            complete=False,fresh_gpu_inference=False,changes_applied=False))
    assert sha(run/'scene.glb')==digest
    write(output,dict(source_scene_sha256=digest,objects=rows,
        complete=True,fresh_gpu_inference=False,changes_applied=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();audit(a.run,a.output)
