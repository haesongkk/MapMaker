"""Experimental local plane support for explicitly foreground-occluded pixels."""
import numpy as np
from scipy.spatial import cKDTree, ConvexHull, QhullError
from scipy.spatial.distance import pdist
from scipy.ndimage import label
import trimesh
from .scene_geometry import inside_support_polygon


def locally_enclosed_points(world, observed, excluded, camera, center, normal, *, component_budget=False, optimal_budget=False, local_evidence_only=False, enclosed_evidence_only=False):
    world=np.asarray(world,float);observed=np.asarray(observed,bool);excluded=np.asarray(excluded,bool)
    camera=np.asarray(camera,float);center=np.asarray(center,float);normal=np.asarray(normal,float)
    if (world.ndim!=3 or world.shape[-1]!=3 or observed.shape!=world.shape[:2]
            or excluded.shape!=observed.shape or any(v.shape!=(3,) or not np.isfinite(v).all() for v in (camera,center,normal))
            or not np.isclose(np.linalg.norm(normal),1)):
        raise ValueError('Expected matching observations and a finite unit-normal plane')
    ray=world-camera;denominator=ray@normal
    factor=np.divide(np.dot(center-camera,normal),denominator,
        out=np.full(denominator.shape,np.nan),where=abs(denominator)>1e-9)
    projected=camera+ray*factor[...,None]
    finite=np.isfinite(world).all(-1)&np.isfinite(projected).all(-1)
    candidates=excluded & ~observed & finite & (factor>1.01)&(factor<4)
    candidates[[0,-1],:]=False;candidates[:,[0,-1]]=False
    inferred=np.zeros_like(observed)
    observed=observed & finite
    evidence=dict(method='local_observed_plane_hull_and_foreground_depth',
        candidate_pixels=int(candidates.sum()),observed_points=int(observed.sum()),
        radius_fraction=.125,maximum_inferred_fraction=.25,confidence_kind='geometric_evidence_not_probability')
    if observed.sum()<8:
        return inferred,projected,dict(evidence,reason='insufficient_observed_support')
    rotation=trimesh.geometry.align_vectors(normal,[0,1,0])
    local=trimesh.transform_points(world[observed],rotation)[:,[0,2]]
    try:
        hull=ConvexHull(local)
        boundary=local[hull.vertices]
    except QhullError:
        return inferred,projected,dict(evidence,reason='degenerate_support_extent')
    # A true diameter, rather than an axis-aligned bounding-box diagonal,
    # keeps the locality bound invariant under a rigid change of frame.
    radius=float(pdist(boundary).max()*.125)
    if radius<=1e-9:
        return inferred,projected,dict(evidence,reason='degenerate_support_extent')
    tree=cKDTree(local);flat=np.flatnonzero(candidates)
    targets=trimesh.transform_points(projected.reshape(-1,3)[flat],rotation)[:,[0,2]]
    if enclosed_evidence_only:
        # Interpolate only inside the measured plane boundary. This is a
        # separate experimental policy, not a relaxation of local support.
        # Foreground-depth and finite-ray checks above remain mandatory.
        enclosed=np.all(targets@hull.equations[:,:2].T+hull.equations[:,2] <= -radius*.01,axis=1)
        inferred.ravel()[flat[enclosed]]=True
        return inferred,projected,dict(evidence,
            method='measured_plane_hull_and_foreground_depth',radius_fraction=None,
            maximum_inferred_fraction=None,budget_policy='interior_plane_interpolation',
            inferred_pixels=int(inferred.sum()),reason='enclosed_foreground_occlusion',
            boundary_margin=radius*.01,extrapolation_outside_observed_hull=False)
    for index,target in zip(flat,targets):
        neighbors=tree.query_ball_point(target,radius)
        if len(neighbors)>=8 and inside_support_polygon(local[neighbors],target,margin=radius*.01):
            inferred.flat[index]=True
    accepted=int(inferred.sum());budget_exceeded=accepted>observed.sum()*.25
    components, count = label(inferred)
    sizes = np.bincount(components.ravel())[1:]
    evidence.update(enclosed_components=int(count),
                    enclosed_component_sizes=sorted((int(s) for s in sizes), reverse=True))
    if local_evidence_only:
        evidence.update(budget_policy='independent_local_observation_support',maximum_inferred_fraction=None)
    if budget_exceeded and not local_evidence_only:
        inferred[:]=False
        if component_budget:
            # Keep complete connected patches, prioritizing the worst distance
            # to an actual observation. Never fill a patch partly to meet quota.
            # This is geometric evidence ranking, not an object/category rule.
            distances=np.full(observed.shape,np.inf)
            distances.ravel()[flat]=tree.query(targets,k=1)[0]
            ranked=[]
            for component in range(1,count+1):
                region=components==component
                ranked.append((float(distances[region].max()),component,int(region.sum())))
            remaining=int(observed.sum()*.25)
            decisions=[]
            selected=None
            if optimal_budget:
                from .occlusion_budget import select_components
                values=[float(np.maximum(0,1-distances[components==component]/radius).sum())
                        for _,component,_ in ranked]
                selected=select_components([size for _,_,size in ranked],values,remaining)
            for distance,component,size in sorted(ranked):
                keep=bool(selected[component-1]) if selected is not None else size<=remaining
                if keep:
                    inferred[components==component]=True
                    remaining-=size
                decisions.append(dict(component=component,pixels=size,
                    maximum_observation_distance=distance,accepted=keep))
            evidence.update(budget_policy='whole_components_nearest_observation',components=decisions)
            if optimal_budget:
                evidence.update(budget_policy='maximum_total_observation_proximity',component_values=values)
    evidence.update(radius=radius,enclosed_pixels=accepted,inferred_pixels=int(inferred.sum()),
                    budget_exceeded=bool(budget_exceeded),reason='bounded_local_support' if local_evidence_only else 'component_budget_applied' if budget_exceeded and component_budget else 'budget_exceeded' if budget_exceeded else 'bounded_local_support')
    return inferred,projected,evidence
