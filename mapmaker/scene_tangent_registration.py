"""Experimental source fitting constrained to a supporting plane's rigid motions."""
import numpy as np
import trimesh
from .scene_proximity import closest_points


def propose_tangent_pose(mesh, initial, observed, normal, *, iterations=12, candidate_filter=None, fit_fraction=.8):
    if not .5<=fit_fraction<=1:
        raise ValueError('Fit fraction must be between one half and one')
    cloud=np.asarray(observed,float)
    cloud=cloud[np.isfinite(cloud).all(-1)]
    normal=np.asarray(normal,float)
    initial=np.asarray(initial,float)
    if normal.shape!=(3,) or not np.isfinite(normal).all() or not np.isclose(np.linalg.norm(normal),1):
        raise ValueError('Expected unit support normal')
    if initial.shape!=(4,4) or not np.isfinite(initial).all() or not np.allclose(initial[3],[0,0,0,1]) or not np.allclose(initial[:3,:3].T@initial[:3,:3],np.eye(3)) or not np.isclose(np.linalg.det(initial[:3,:3]),1):
        raise ValueError('Expected proper rigid initial pose')
    if len(cloud)<64:return None,dict(reason='insufficient_source_points')
    scale=float(np.linalg.norm(mesh.extents));budget=scale*.08
    order=np.lexsort((cloud[:,2],cloud[:,1],cloud[:,0]))
    sample=cloud[order[np.linspace(0,len(cloud)-1,min(256,len(cloud))).astype(int)]]
    fit,validation=sample[::2],sample[1::2]
    frame=trimesh.geometry.align_vectors([0,1,0],normal)[:3,:3]
    basis=frame[:,[0,2]]
    def nearest(points,transform):
        local=trimesh.transform_points(points,np.linalg.inv(transform))
        closest,distance,_=closest_points(mesh,local)
        return trimesh.transform_points(closest,transform),distance
    def score(distance):return float(np.mean(np.sort(distance)[:max(1,int(len(distance)*.8))]**2))
    current=initial.copy();_,baseline=nearest(validation,current)
    best_score=score(baseline);history=[]
    for iteration in range(iterations):
        closest,distance=nearest(fit,current)
        keep=distance<=np.quantile(distance,fit_fraction)
        a,b=closest[keep]@basis,fit[keep]@basis
        ca,cb=a.mean(0),b.mean(0)
        u,_,vh=np.linalg.svd((a-ca).T@(b-cb))
        rotation=vh.T@u.T
        if np.linalg.det(rotation)<0:
            vh[-1]*=-1;rotation=vh.T@u.T
        delta=np.eye(4);delta[:3,:3]=basis@rotation@basis.T+np.outer(normal,normal)
        delta[:3,3]=basis@(cb-rotation@ca)
        proposal=delta@current
        moved=trimesh.transform_points(mesh.vertices,proposal)
        motion=float(np.linalg.norm(moved-mesh.vertices,axis=1).max())
        angle=float(np.rad2deg(np.arccos(np.clip((np.trace(proposal[:3,:3])-1)/2,-1,1))))
        if motion>budget or angle>8:
            history.append(dict(reason='motion_bound',motion=motion,angle=angle));break
        if candidate_filter is not None and not candidate_filter(proposal):
            history.append(dict(reason='candidate_filter_rejected',iteration=iteration));break
        _,after=nearest(validation,proposal);value=score(after)
        history.append(dict(iteration=iteration,validation_score=value,motion=motion,angle=angle))
        if value>=best_score-1e-14:break
        current=proposal;best_score=value
    improved=best_score<score(baseline)-1e-14
    return (current if improved else None),dict(reason='validation_improved' if improved else 'no_independent_improvement',
        baseline_score=score(baseline),candidate_score=best_score,history=history,
        scope='Preserves infinite-plane height; finite support, visible source and collisions require separate checks',
        requires_source_and_collision_validation=True,uses_object_names=False)
