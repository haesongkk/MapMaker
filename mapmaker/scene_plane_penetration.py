"""Finite observed-plane evidence for correcting an already intersecting pose."""
import numpy as np
from .scene_proximity import closest_points


def planar_penetration_evidence(fixed, moving, end, normal, tolerance):
    normal=np.asarray(normal,float)
    if normal.shape!=(3,) or not np.isfinite(normal).all() or not np.isclose(np.linalg.norm(normal),1) or tolerance<=0:
        raise ValueError('Expected a finite unit normal and positive tolerance')
    vertices=fixed.mesh.vertices;center=vertices.mean(0)
    numerical=max(float(np.linalg.norm(fixed.mesh.extents))*1e-6,1e-9)
    error=float(np.abs((vertices-center)@normal).max())
    result=dict(penetration_confirmed=False,penetration_method='finite_planar_halfspace_witness',
        planarity_error=error,numerical_tolerance=numerical,requires_confirmed_initial_finite_intersection=True)
    if error>numerical:return dict(result,reason='nonplanar_surface')
    before=np.asarray(moving).reshape(-1,3);after=np.asarray(end).reshape(-1,3)
    distance=(before-center)@normal;final=(after-center)@normal
    result.update(minimum_before=float(distance.min()),minimum_after=float(final.min()))
    if final.min()<=numerical:return dict(result,reason='final_halfspace_not_clear')
    if distance.max()<=tolerance:return dict(result,reason='no_straddling_initial_body')
    below=np.flatnonzero(distance < -tolerance)
    if not len(below):return dict(result,reason='no_finite_depth_intrusion')
    below=below[np.linspace(0,len(below)-1,min(256,len(below))).astype(int)]
    projected=before[below]-distance[below,None]*normal
    _,separation,_=closest_points(fixed.mesh,projected)
    witnesses=int(np.count_nonzero(separation<=numerical))
    return dict(result,penetration_confirmed=witnesses>0,finite_patch_witnesses=witnesses,
        reason='measured_finite_plane_intrusion' if witnesses else 'no_finite_patch_witness')
