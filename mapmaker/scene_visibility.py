"""Observed-ray depth consistency, independent of object names and hidden shape.

This is diagnostic evidence, not permission to delete or clip a reconstruction.
Use original camera-frame meshes and the shared pointmap before scene alignment.
"""
import numpy as np
from scipy.ndimage import distance_transform_edt


def ray_depth(faces, rays, *, depth_sign=1., max_pairs=4_000_000):
    """Nearest positive camera depth at exact pointmap rays, using triangle hits.

    Index projected triangle bounds, then evaluate barycentric coordinates and
    perspective-correct depth. A query budget exhaustion is explicitly unknown.
    Camera-crossing triangles are excluded and reported rather than projected
    across the camera singularity.
    """
    from rtree import index
    faces, rays = np.asarray(faces, float), np.asarray(rays, float)
    if faces.ndim != 3 or faces.shape[1:] != (3, 3) or rays.ndim != 2 or rays.shape[1] != 3:
        raise ValueError('Expected triangle faces and Nx3 rays')
    if depth_sign not in (-1., 1.) or max_pairs < 1:
        raise ValueError('Invalid depth convention or query budget')
    valid_faces = np.isfinite(faces).all((1, 2)) & (faces[..., 2]*depth_sign > 1e-8).all(1)
    selected = faces[valid_faces]
    result = np.full(len(rays), np.nan)
    evidence = dict(completed=True, tested_pairs=0, excluded_triangles=int((~valid_faces).sum()))
    if not len(selected):
        return result, evidence
    uv = selected[..., :2]/selected[..., 2, None]
    depth = selected[..., 2]*depth_sign
    v0, v1 = uv[:, 1]-uv[:, 0], uv[:, 2]-uv[:, 0]
    determinant = v0[:, 0]*v1[:, 1]-v0[:, 1]*v1[:, 0]
    good = abs(determinant) > 1e-14
    uv, depth, v0, v1, determinant = [a[good] for a in (uv, depth, v0, v1, determinant)]
    if not len(uv):
        return result, evidence
    lower, upper = uv.min(1), uv.max(1)
    tree = index.Index((i, (*lo, *hi), None) for i, (lo, hi) in enumerate(zip(lower, upper)))
    valid_rays = np.isfinite(rays).all(1) & (rays[:, 2]*depth_sign > 1e-8)
    try:
        for row in np.flatnonzero(valid_rays):
            point = rays[row, :2]/rays[row, 2]
            ids = np.fromiter(tree.intersection((*point, *point)), dtype=np.int64)
            evidence['tested_pairs'] += len(ids)
            if evidence['tested_pairs'] > max_pairs:
                evidence.update(completed=False, reason='triangle_query_budget_exhausted')
                return result, evidence
            if not len(ids):
                continue
            offset = point-uv[ids, 0]
            b = (offset[:, 0]*v1[ids, 1]-offset[:, 1]*v1[ids, 0])/determinant[ids]
            c = (v0[ids, 0]*offset[:, 1]-v0[ids, 1]*offset[:, 0])/determinant[ids]
            a = 1-b-c
            inside = (a >= -1e-9) & (b >= -1e-9) & (c >= -1e-9)
            if inside.any():
                inverse = a/depth[ids, 0]+b/depth[ids, 1]+c/depth[ids, 2]
                result[row] = (1/inverse[inside]).min()
    finally:
        tree.close()
    return result, evidence


def visibility_evidence(faces, points, mask, *, maximum_size=192, relative_tolerance=.02):
    """Distinguish visible disagreement from geometry behind observed occluders.

    The tolerance is an explicit scale-relative diagnostic parameter, not a
    calibrated depth uncertainty. No automatic repair or quality pass follows.
    """
    points, mask = np.asarray(points, float), np.asarray(mask, bool)
    if points.shape != (*mask.shape, 3) or mask.ndim != 2:
        raise ValueError('Expected matching pointmap and mask')
    if not 16 <= maximum_size <= 1024 or not np.isfinite(relative_tolerance) or relative_tolerance <= 0:
        raise ValueError('Invalid diagnostic sampling parameters')
    valid = np.isfinite(points).all(-1) & (np.linalg.norm(points, axis=-1) > 1e-6)
    cloud = points[valid & mask]
    if len(cloud) < 64:
        return dict(accepted=False, reason='insufficient_object_depth')
    scale = float(np.linalg.norm(np.quantile(cloud, .95, axis=0)-np.quantile(cloud, .05, axis=0)))
    if scale < 1e-8:
        return dict(accepted=False, reason='degenerate_object_depth')
    sign = float(np.sign(np.median(cloud[:, 2])))
    if sign == 0:
        return dict(accepted=False, reason='ambiguous_camera_halfspace')
    step = max(1, int(np.ceil(max(mask.shape)/maximum_size)))
    sampled = points[::step, ::step]
    predicted, query = ray_depth(faces, sampled.reshape(-1, 3), depth_sign=sign)
    if not query['completed']:
        return dict(accepted=False, reason=query['reason'], query=query)
    predicted = predicted.reshape(sampled.shape[:2])
    observed = sampled[..., 2]*sign
    reliable = valid[::step, ::step] & (observed > 1e-8)
    inside = mask[::step, ::step] & reliable
    # Ignore the silhouette neighborhood: pixel alignment and boundaries are
    # not sufficiently precise to interpret a one-pixel rim as invented shape.
    outside = (distance_transform_edt(~mask)[::step, ::step] > step*1.5) & reliable
    hit = np.isfinite(predicted)
    tolerance = scale*relative_tolerance
    residual = predicted-observed
    outside_hit = outside & hit
    front = outside_hit & (residual < -tolerance)
    hidden = outside_hit & (residual > tolerance)
    same_depth = outside_hit & (abs(residual) <= tolerance)
    matched = inside & hit
    return dict(accepted=True, sampled_object_pixels=int(inside.sum()),
        object_hit_pixels=int(matched.sum()), outside_hit_pixels=int(outside_hit.sum()),
        outside_front_pixels=int(front.sum()), outside_hidden_pixels=int(hidden.sum()),
        outside_same_depth_pixels=int(same_depth.sum()),
        outside_front_fraction=float(front.sum()/max(1, outside_hit.sum())),
        object_normalized_depth_median=float(np.median(abs(residual[matched]))/scale) if matched.any() else None,
        object_normalized_depth_p90=float(np.quantile(abs(residual[matched]), .9)/scale) if matched.any() else None,
        observed_scale=scale, depth_tolerance=tolerance, relative_tolerance=relative_tolerance,
        sampling_step=step, query=query, uses_object_names=False, quality_passed=False,
        limitation='Estimated single-view depth; transparent/reflective regions can violate depth assumptions; hidden geometry is not certified')
