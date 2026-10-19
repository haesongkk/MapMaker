"""Source evidence for comparing reconstructions; no semantic object rules.

These measurements can request another reconstruction, never delete an object.
They do not establish unseen shape quality or metric ground truth.
"""
import numpy as np
import trimesh

from .scene_projection import silhouette_evidence
from .scene_proximity import closest_points


def candidate_faces(asset, matrix):
    """Use the same root and child transforms as the exported scene assembly."""
    if isinstance(asset, trimesh.Trimesh):
        asset = trimesh.Scene(asset)
    faces = []
    for node in asset.graph.nodes_geometry:
        transform, name = asset.graph[node]
        mesh = asset.geometry[name]
        vertices = trimesh.transform_points(mesh.vertices, np.asarray(matrix)@transform)
        faces.append(vertices[mesh.faces])
    if not faces:
        raise ValueError('Reconstruction has no mesh geometry')
    result = np.concatenate(faces)
    if not len(result) or not np.isfinite(result).all():
        raise ValueError('Reconstruction has no finite triangles')
    return result


def assess(faces, points, mask, *, visible_depth=False):
    return _assess(faces, points, mask, visible_depth=visible_depth,
        mesh_factory=lambda: _evidence_mesh(faces))


def _evidence_mesh(faces):
    return trimesh.Trimesh(np.asarray(faces).reshape(-1,3),
        np.arange(len(faces)*3).reshape(-1,3), process=False)


def assess_masks(faces, points, masks, *, visible_depth=False):
    """Assess named masks against one geometry, reusing its spatial indexes.

    The cache lasts only for this call. Transformed candidates must make a new
    call; no mesh or evidence is shared between candidates. Rejected depth or
    projection evidence does not allocate a mesh.
    """
    mesh = None
    def mesh_factory():
        nonlocal mesh
        if mesh is None:
            mesh = _evidence_mesh(faces)
        return mesh
    return {label: _assess(faces, points, mask, visible_depth=visible_depth,
        mesh_factory=mesh_factory) for label, mask in masks.items()}


def _assess(faces, points, mask, *, visible_depth, mesh_factory):
    mask = np.asarray(mask, bool)
    if mask.shape != points.shape[:2]:
        raise ValueError('Mask must match the shared pointmap')
    observed = points[mask]
    valid = np.isfinite(observed).all(-1) & (np.linalg.norm(observed, axis=-1)>1e-6)
    if valid.sum()<64 or valid.mean()<.95:
        return dict(accepted=False, reason='insufficient_reliable_depth')
    cloud = observed[valid]
    scale = float(np.linalg.norm(np.quantile(cloud,.95,axis=0)-np.quantile(cloud,.05,axis=0)))
    if scale < 1e-8:
        return dict(accepted=False, reason='degenerate_observed_extent')
    projection = silhouette_evidence(faces, points, mask)
    if not projection['accepted'] or projection['mask_pixels']<16:
        return dict(accepted=False, reason='insufficient_projected_mask', projection=projection)
    ids = np.linspace(0, len(cloud)-1, min(256,len(cloud))).astype(int)
    mesh = mesh_factory()
    _, distances, _ = closest_points(mesh, cloud[ids])
    median = float(np.median(distances)/scale)
    p90 = float(np.quantile(distances,.9)/scale)
    # Missing the visible mask AND its observed depth identifies gross source
    # mismatch; projecting hidden geometry outside a mask alone does not.
    retry = projection['mask_covered_fraction']<.25 and median>.1
    result = dict(accepted=True, projection=projection, observed_scale=scale,
        normalized_depth_median=median, normalized_depth_p90=p90,
        depth_samples=len(ids), retry_recommended=retry,
        reason='gross_visible_source_mismatch' if retry else 'no_gross_mismatch_trigger',
        limitation='Estimated visible depth only; no unseen-shape or support certification')
    if visible_depth:
        from .scene_visible_depth import visible_depth_evidence
        result['visible_depth']=visible_depth_evidence(mesh,cloud,scale)
        ray=result['visible_depth']
        if (ray.get('available') and ray.get('matched_rays',0)>=64
                and ray.get('hit_fraction',0)>=.5 and ray.get('normalized_median') is not None
                and ray['normalized_median']>.1):
            result.update(retry_recommended=True,reason='visible_first_surface_depth_mismatch')
    return result


def prefer_alternative(original, alternative):
    """Require agreement gains in both modalities, without degrading their tails."""
    if not original.get('accepted') or not alternative.get('accepted'):
        return False
    a, b = original['projection'], alternative['projection']
    legacy = bool(b['mask_covered_fraction']>=a['mask_covered_fraction']+.05
        and b['silhouette_iou']>=a['silhouette_iou']
        and alternative['normalized_depth_median']<=original['normalized_depth_median']*.8
        and alternative['normalized_depth_p90']<=original['normalized_depth_p90'])
    if 'visible_depth' not in original and 'visible_depth' not in alternative:
        return legacy
    rays=[item.get('visible_depth',{}) for item in (original,alternative)]
    for ray in rays:
        if (not ray.get('available') or ray.get('matched_rays',0)<64
                or ray.get('hit_fraction',0)<.5
                or any(ray.get(k) is None or not np.isfinite(ray[k]) for k in ('normalized_median','normalized_p90'))):
            return False
    before,after=rays
    preserved=(after['hit_fraction']>=before['hit_fraction']
        and after['normalized_median']<=before['normalized_median']
        and after['normalized_p90']<=before['normalized_p90'])
    ray_gain=(before['normalized_median']>0
        and after['normalized_median']<=before['normalized_median']*.8
        and b['mask_covered_fraction']>=a['mask_covered_fraction']
        and b['silhouette_iou']>=a['silhouette_iou']
        and alternative['normalized_depth_median']<=original['normalized_depth_median']
        and alternative['normalized_depth_p90']<=original['normalized_depth_p90'])
    return bool(preserved and (legacy or ray_gain))
