"""Geometry-only supported similarity proposals; never mutate a scene."""
import numpy as np
import trimesh
from .scene_geometry import support_translation
from .scene_tangent_registration import propose_tangent_pose


def supported_pose_candidates(mesh, initial, observed, support_faces, normal, point, tolerance):
    """Fit source tangentially across bounded uniform scales, preserving contact.

    The caller must validate visible first-surface evidence, all object/space
    collisions and pre-existing valid contacts before applying any proposal.
    """
    vertices=np.asarray(mesh.vertices);normal=np.asarray(normal,float);point=np.asarray(point,float)
    if normal.shape!=(3,) or point.shape!=(3,) or not np.isfinite(normal).all() or not np.isfinite(point).all() or not np.isclose(np.linalg.norm(normal),1) or tolerance<=0:
        raise ValueError('Expected finite observed plane and positive tolerance')
    initial=np.asarray(initial,float)
    if initial.shape!=(4,4) or not np.isfinite(initial).all() or not np.allclose(initial[3],[0,0,0,1]) or not np.allclose(initial[:3,:3].T@initial[:3,:3],np.eye(3)) or not np.isclose(np.linalg.det(initial[:3,:3]),1):
        raise ValueError('Expected rigid initial contact pose')
    # Bounds center avoids weighting the anchor by arbitrary mesh tessellation.
    moved=trimesh.transform_points(vertices,initial);center=(moved.min(0)+moved.max(0))/2
    anchor=center-normal*np.dot(center-point,normal)
    budget=float(np.linalg.norm(mesh.extents)*.08)
    def certificate(transform):
        moved=trimesh.transform_points(vertices,transform)
        factor=float(np.cbrt(np.linalg.det(transform[:3,:3])))
        angle=float(np.rad2deg(np.arccos(np.clip((np.trace(transform[:3,:3]/factor)-1)/2,-1,1))))
        motion=float(np.linalg.norm(moved-vertices,axis=1).max())
        if motion>budget or angle>8:return False,dict(reason='motion_bound',motion=motion,angle=angle)
        shift,evidence=support_translation(moved,support_faces,budget,tolerance)
        valid=shift is not None and np.linalg.norm(shift)<=tolerance
        return valid,dict(reason='finite_contact' if valid else 'contact_rejected',contact=evidence,motion=motion,angle=angle)
    for factor in (1.,.95,.9,1.05,1.1):
        scale=np.eye(4);scale[:3,:3]*=factor;scale[:3,3]=anchor*(1-factor)
        seed=scale@initial
        valid,_=certificate(seed)
        if not valid:continue
        scaled=trimesh.Trimesh(trimesh.transform_points(vertices,seed),mesh.faces,process=False)
        delta,fit=propose_tangent_pose(scaled,np.eye(4),observed,normal,
            candidate_filter=lambda t:certificate(t@seed)[0])
        transform=seed if delta is None else delta@seed
        moved=trimesh.transform_points(vertices,transform)
        clearance=max(0.,tolerance*.1-float(((moved-point)@normal).min()))
        transform=transform.copy();transform[:3,3]+=normal*clearance
        valid,evidence=certificate(transform)
        if valid:
            yield transform,dict(uniform_scale=factor,normal_clearance=clearance,fit=fit,
                final=evidence,motion_budget=budget,requires_source_and_collision_validation=True,
                uses_object_names=False)
