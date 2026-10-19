"""Bounded rigid proposals to restore measured contacts after mesh replacement."""
import numpy as np
import trimesh
from .scene_proximity import closest_points
from .reconstruction_context import contact_context_screen


def restore_contact_pose(original, alternative, others, tolerance, *, samples=512, iterations=4):
    """Return a proposal only; source agreement and intersections need separate checks.

    The targets are observed near-contact points on unchanged neighboring meshes.
    No semantic class, fabricated floor, or vertex deformation is used.
    """
    old,new=np.asarray(original,float),np.asarray(alternative,float)
    others=list(others)
    if any(f.ndim!=3 or f.shape[1:]!=(3,3) or not len(f) or not np.isfinite(f).all() for f in (old,new)):
        raise ValueError('Expected finite nonempty triangle arrays')
    if tolerance<=0 or not np.isfinite(tolerance) or samples<3 or not 1<=iterations<=4:
        raise ValueError('Invalid contact proposal bounds')
    def mesh(f):return trimesh.Trimesh(f.reshape(-1,3),np.arange(len(f)*3).reshape(-1,3),process=False)
    original_mesh=mesh(old)
    lower=old.min((0,1))-tolerance;upper=old.max((0,1))+tolerance
    targets=[]
    for _,faces in others:
        faces=np.asarray(faces,float)
        relevant=faces[np.all(faces.max(1)>=lower,axis=1)&np.all(faces.min(1)<=upper,axis=1)]
        if not len(relevant):continue
        points=np.unique(np.concatenate([relevant.reshape(-1,3),relevant.mean(1)]),axis=0)
        points=points[np.linspace(0,len(points)-1,min(samples,len(points))).astype(int)]
        _,distance,_=closest_points(original_mesh,points)
        targets.extend(points[distance<=tolerance])
    result=dict(proposed=False,uses_object_names=False,quality_gate_passed=False,
        requires_source_and_collision_validation=True,iterations=[],target_count=len(targets))
    if len(targets)<3:return dict(result,reason='insufficient_observed_contact_targets')
    targets=np.unique(targets,axis=0)
    if np.linalg.matrix_rank(targets-targets.mean(0),tol=tolerance*.01)<2:
        return dict(result,reason='degenerate_contact_targets')
    vertices=new.reshape(-1,3);scale=float(np.linalg.norm(np.ptp(vertices,axis=0)))
    matrix=np.eye(4)
    for step in range(iterations):
        transformed=trimesh.transform_points(vertices,matrix).reshape(-1,3,3)
        matched,_,_=closest_points(mesh(transformed),targets)
        a,b=matched.mean(0),targets.mean(0)
        u,_,vt=np.linalg.svd((matched-a).T@(targets-b))
        correction=np.eye(3);correction[-1,-1]=np.linalg.det(vt.T@u.T)
        rotation=vt.T@correction@u.T
        delta=np.eye(4);delta[:3,:3]=rotation;delta[:3,3]=b-rotation@a
        proposed=delta@matrix
        angle=float(np.rad2deg(np.arccos(np.clip((np.trace(proposed[:3,:3])-1)/2,-1,1))))
        moved=trimesh.transform_points(vertices,proposed)
        motion=float(np.linalg.norm(moved-vertices,axis=1).max())
        record=dict(step=step,rotation_degrees=angle,maximum_vertex_motion=motion,motion_budget=scale*.08)
        result['iterations'].append(record)
        if angle>8 or motion>scale*.08:return dict(result,reason='rigid_motion_budget_exceeded')
        evidence=contact_context_screen(old,moved.reshape(-1,3,3),others,tolerance,samples=samples)
        record['contact_screen']=evidence
        if evidence['accepted']:
            return dict(result,proposed=True,transform=proposed.tolist(),reason='sampled_contacts_restored')
        matrix=proposed
    return dict(result,reason='contacts_not_restored_within_bounded_search')
