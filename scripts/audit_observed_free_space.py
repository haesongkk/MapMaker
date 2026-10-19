"""Measure mesh surfaces contradicting observed free space; never edits meshes.

Seven samples are evidence for investigation, not proof that a whole triangle
can be removed. Occluded/back surfaces are not free-space violations.
"""
import argparse
from pathlib import Path
import numpy as np
from PIL import Image
from scipy.ndimage import minimum_filter, maximum_filter, binary_dilation
import trimesh
from mapmaker.scene_geometry import triangles
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_vanishing import fit_camera


def surface_evidence(faces, points, mask):
    camera=fit_camera(points)
    if not camera['accepted']:
        return dict(accepted=False,reason='camera_fit_rejected')
    valid=np.isfinite(points).all(-1)&(abs(points[...,2])>1e-6)
    sign=np.sign(np.median(points[...,2][valid]))
    depth=points[...,2]*sign
    lower=minimum_filter(np.where(valid,depth,np.inf),size=3)
    upper=maximum_filter(np.where(valid,depth,-np.inf),size=3)
    reliable=minimum_filter(valid.astype(np.uint8),size=3)>0
    reliable &= upper-lower < .02*np.maximum(lower,1e-6)
    expanded=binary_dilation(mask,iterations=2)
    h,w=depth.shape
    weights=np.array([[1,0,0],[0,1,0],[0,0,1],[.5,.5,0],[0,.5,.5],[.5,0,.5],[1/3]*3])
    hits=[]
    for start in range(0,len(faces),8192):
        f=faces[start:start+8192]
        samples=np.einsum('sc,fcd->fsd',weights,f)
        p=samples@np.asarray(camera['matrix']).T
        uv=np.divide(p[...,:2],p[...,2,None],out=np.full_like(p[...,:2],-1),where=abs(p[...,2,None])>1e-8)
        finite=np.isfinite(uv).all(-1)
        safe=np.where(np.isfinite(uv),uv,-1)
        x=np.clip(np.rint(safe[...,0]),0,w-1).astype(int)
        y=np.clip(np.rint(safe[...,1]),0,h-1).astype(int)
        inside=finite&(uv[...,0]>=1)&(uv[...,0]<w-1)&(uv[...,1]>=1)&(uv[...,1]<h-1)
        front=(samples[...,2]*sign>0)&(samples[...,2]*sign<.98*lower[y,x])
        hits.append((inside&reliable[y,x]&~expanded[y,x]&front).all(1))
    contradicted=np.concatenate(hits) if hits else np.zeros(0,bool)
    area=np.linalg.norm(np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0]),axis=1)*.5
    return dict(accepted=True,triangles=len(faces),contradicted_triangles=int(contradicted.sum()),
        contradicted_surface_fraction=float(area[contradicted].sum()/max(area.sum(),1e-12)),
        uses_object_names=False,limitation='Sampled diagnostic; not permission to delete whole faces')


def main(source,output):
    meta=read(source/'scene_metadata.json')
    points=np.load(source/meta['pointmap']['asset'])['points']
    scene=trimesh.load(source/'scene.glb',force='scene',process=False)
    inverse=np.linalg.inv(meta['placement']['common_transform'])
    digest=sha(source/'scene.glb')
    reports=[]
    for obj in meta['objects']:
        if obj['status']!='generated':
            continue
        mask=np.asarray(Image.open(source/obj['mask']).convert('L').resize(points.shape[1::-1],Image.Resampling.NEAREST))>0
        faces=triangles(scene,obj['id'])
        raw=trimesh.transform_points(faces.reshape(-1,3),inverse).reshape(-1,3,3)
        reports.append(dict(object_id=obj['id'],**surface_evidence(raw,points,mask)))
    assert sha(source/'scene.glb')==digest
    write(output,dict(source=str(source),source_scene_sha256=digest,source_unchanged=True,reports=reports))
    print(reports)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();main(a.source,a.output)
