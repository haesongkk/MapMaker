"""Conservative experimental face rejection from complete projected depth boxes.

The pointmap remains an uncertain monocular observation. This is conditional
geometric evidence, not ground-truth visibility or a watertight repair.
"""
import numpy as np
from scipy.ndimage import binary_dilation, minimum_filter, maximum_filter
from .scene_vanishing import fit_camera


def free_space_faces(faces, points, mask, *, max_box_pixels=4096):
    faces=np.asarray(faces,float)
    removed=np.zeros(len(faces),bool)
    camera=fit_camera(points)
    if not camera['accepted']:
        return removed,dict(accepted=False,reason='camera_fit_rejected')
    h,w=points.shape[:2]
    valid=np.isfinite(points).all(-1)&(abs(points[...,2])>1e-6)
    sign=float(np.sign(np.median(points[...,2][valid])))
    depth=points[...,2]*sign
    valid &= depth>0
    padding=max(2,int(np.ceil(camera['residual_p90']))+1)
    protected=binary_dilation(mask,iterations=padding)
    invalid=(~valid)|protected
    integral=np.pad(invalid.astype(np.int64),((1,0),(1,0))).cumsum(0).cumsum(1)
    projected=faces@np.asarray(camera['matrix']).T
    uv=np.divide(projected[...,:2],projected[...,2,None],out=np.full_like(projected[...,:2],-1),
                 where=abs(projected[...,2,None])>1e-8)
    finite=np.isfinite(faces).all((1,2))&np.isfinite(uv).all((1,2))
    finite &= (faces[...,2]*sign>1e-6).all(1)
    safe=np.where(np.isfinite(uv),uv,-1)
    lo=np.floor(np.clip(safe.min(1),-1,max(h,w)+1)).astype(int)
    hi=np.ceil(np.clip(safe.max(1),-1,max(h,w)+1)).astype(int)
    size=hi-lo+1
    candidates=finite&(lo[:,0]>=padding)&(lo[:,1]>=padding)&(hi[:,0]<w-padding)&(hi[:,1]<h-padding)
    candidates &= (size[:,0]*size[:,1]<=max_box_pixels)&(size>0).all(1)
    ids=np.flatnonzero(candidates)
    x0,y0=lo[ids].T; x1,y1=hi[ids].T
    counts=integral[y1+1,x1+1]-integral[y0,x1+1]-integral[y1+1,x0]+integral[y0,x0]
    ids=ids[counts==0]
    if len(ids):
        # Four power-of-two windows exactly cover any integer rectangle.
        # This queries every pixel in the box, not just face vertices/seeds.
        exponents=np.floor(np.log2(size[ids])).astype(int)
        for ex,ey in np.unique(exponents,axis=0):
            group=ids[np.all(exponents==[ex,ey],axis=1)]
            sx,sy=2**ex,2**ey
            lower=minimum_filter(np.where(valid,depth,np.inf),size=(sy,sx),mode='constant',cval=np.inf)
            upper=maximum_filter(np.where(valid,depth,-np.inf),size=(sy,sx),mode='constant',cval=-np.inf)
            x0,y0=lo[group].T; x1,y1=hi[group].T
            left=x0+sx//2; right=x1-sx+1+sx//2
            top=y0+sy//2; bottom=y1-sy+1+sy//2
            low=np.minimum.reduce([lower[top,left],lower[top,right],lower[bottom,left],lower[bottom,right]])
            high=np.maximum.reduce([upper[top,left],upper[top,right],upper[bottom,left],upper[bottom,right]])
            stable=high-low<=.02*low
            removed[group]=stable&((faces[group,:,2]*sign).max(1)<.98*low)
    area=np.linalg.norm(np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0]),axis=1)*.5
    return removed,dict(accepted=True,removed_faces=int(removed.sum()),faces=len(faces),
        removed_area_fraction=float(area[removed].sum()/max(area.sum(),1e-12)),
        protected_mask_padding=padding,uses_object_names=False,
        method='all_projected_box_pixels_valid_unmasked_stable_depth_beyond_farthest_face_vertex',
        limitation='Conditional on monocular depth and fitted camera; can open meshes; not a watertight repair')
