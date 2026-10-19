"""Geometry-only contact pose proposals; callers must certify source and collisions."""
import numpy as np
import trimesh
from .scene_geometry import contact_footprint, HorizontalSurface, support_translation


def contact_pose_candidates(vertices, support_faces, limit, tolerance, *, max_angle=8., diagnostics=None):
    """Try actual bottom contacts first, then a wider band for tilted objects."""
    for footprint_angle in (0.,max_angle):
        yield from _contact_pose_candidates(vertices,support_faces,limit,tolerance,
            max_angle=max_angle,footprint_angle=footprint_angle,diagnostics=diagnostics)


def _contact_pose_candidates(vertices, support_faces, limit, tolerance, *, max_angle, footprint_angle, diagnostics):
    """Fit a small tilt to observed foot/surface gaps, without modifying geometry.

    This is a proposal, not permission to move: stable foot contact alone cannot
    prove a collision-free body or agreement with the source image.
    """
    vertices=np.asarray(vertices,float)
    if vertices.ndim!=2 or vertices.shape[1]!=3 or not np.isfinite(vertices).all():
        raise ValueError('Expected finite vertices')
    if limit<=0 or tolerance<=0 or not 0<max_angle<=8:
        raise ValueError('Expected positive contact bounds and angle at most 8 degrees')
    samples=contact_footprint(vertices,max_tilt_degrees=footprint_angle)
    surface=HorizontalSurface(support_faces)
    heights=[surface.height(p[[0,2]],maximum=vertices[:,1].min()+limit) for p in samples]
    known=np.array([h is not None for h in heights])
    def record(reason, **details):
        if diagnostics is not None:diagnostics.append(dict(reason=reason,footprint_angle=footprint_angle,**details))
    if known.sum()<3:
        record('insufficient_observed_foot_samples',known=int(known.sum()));return
    feet=samples[known];target=np.asarray([h for h in heights if h is not None])
    center=(vertices.min(0)+vertices.max(0))/2
    design=np.column_stack([feet[:,0]-center[0],feet[:,2]-center[2],np.ones(len(feet))])
    if np.linalg.matrix_rank(design)<3:
        record('degenerate_foot_samples');return
    slopes=np.linalg.lstsq(design,target-feet[:,1],rcond=None)[0][:2]
    axis=np.array([-slopes[1],0.,slopes[0]])
    angle=float(np.arctan(np.linalg.norm(axis)))
    if angle<1e-8:
        record('no_tilt',rotation_degrees=float(np.rad2deg(angle)));return
    if np.rad2deg(angle)>max_angle:
        record('fit_exceeds_rotation_budget',rotation_degrees=float(np.rad2deg(angle)))
        angle=float(np.deg2rad(max_angle))
    axis/=np.linalg.norm(axis)
    scale=float(np.linalg.norm(np.ptp(vertices,axis=0)))
    for fraction in (1.,.75,.5,.25):
        transform=trimesh.transformations.rotation_matrix(angle*fraction,axis,point=center)
        rotated=trimesh.transform_points(vertices,transform)
        delta,evidence=support_translation(rotated,support_faces,limit,tolerance,surface=surface)
        if delta is None:
            record('contact_rejected',fraction=fraction,contact=evidence);continue
        transform[:3,3]+=delta
        maximum_motion=float(np.linalg.norm(trimesh.transform_points(vertices,transform)-vertices,axis=1).max())
        if maximum_motion>scale*.08:
            record('vertex_motion_budget',fraction=fraction,maximum_vertex_motion=maximum_motion,motion_budget=scale*.08);continue
        yield transform,dict(method='foot_surface_gap_tilt',rotation_degrees=float(np.rad2deg(angle*fraction)),
            footprint_angle=footprint_angle,
            maximum_vertex_motion=maximum_motion,motion_budget=scale*.08,contact=evidence,
            requires_source_and_collision_validation=True,uses_object_names=False)
