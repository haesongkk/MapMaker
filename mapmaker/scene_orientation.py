"""Bounded, label-free orientation evidence from observed pointmap normals."""
import numpy as np


def estimate_up(points, image=None, *, line_sizes=(320,640,960)):
    surface = surface_up(points)
    if image is None:
        return surface
    from .scene_vanishing import fit_camera, image_segments, vanishing_up, reconcile_orientation, select_line_scale
    from PIL import Image
    # Shared pointmap and image may have different resolutions.
    h, w = points.shape[:2]
    image = np.asarray(Image.fromarray(np.asarray(image, np.uint8)).resize((w, h)))
    camera = fit_camera(points)
    if not line_sizes or any(not isinstance(size,int) or not 32 <= size <= 1920 for size in line_sizes):
        raise ValueError('Expected bounded image-line resolutions')
    reports = [dict(vanishing_up(image_segments(image,maximum_size=size), camera['matrix'], [w,h]),
                    maximum_size=size, actual_maximum_size=min(size,max(w,h))) for size in line_sizes] if camera['accepted'] else []
    lines = select_line_scale(reports) if reports else dict(accepted=False,reason='camera_fit_rejected')
    lines['camera'] = camera
    if lines['reason'] == 'vanishing_scales_disagree':
        return dict(surface, accepted=False, reason='vanishing_scales_disagree',vanishing_point=lines)
    if not surface.get('accepted') and lines.get('accepted'):
        walls = vertical_plane_up(points)
        if walls.get('accepted'):
            result = reconcile_orientation(walls, lines)
            result['horizontal_normal_evidence'] = surface
            result['vertical_plane_evidence'] = walls
            return result
        corroborated = corroborate_line_with_wall(surface, lines, walls)
        if corroborated is not None:
            return corroborated
    result = reconcile_orientation(surface, lines)
    result['limitation'] = 'Monocular orientation evidence with explicit camera-up prior; confidence is not calibrated'
    return result


def corroborate_line_with_wall(surface, lines, walls):
    """Use a supported image axis with an independently observed wall normal.

    A wall alone does not determine up. Require consistent accepted image-line
    estimates at multiple resolutions, and never override a supported horizontal
    normal cluster. The plane supplies a parallelism check, not a second up axis.
    """
    if surface.get('accepted') or surface.get('support_fraction', 0) >= .08:
        return None
    supported = [r for r in lines.get('scale_evidence', []) if r.get('accepted')]
    resolutions={r.get('actual_maximum_size',r.get('maximum_size')) for r in supported}
    resolutions.discard(None)
    if not lines.get('accepted') or len(resolutions) < 2:
        return None
    families = walls.get('families', [])
    if not families:
        return None
    up = np.asarray(lines['up'], float)
    agreements = []
    for family in families:
        angle = float(np.degrees(np.arcsin(np.clip(abs(np.dot(family['normal'], up)), 0, 1))))
        if angle <= 8 and family['fraction'] >= .15 and max(family['image_span']) >= .5:
            agreements.append(dict(family, axis_to_plane_degrees=angle))
    if not agreements:
        return None
    return dict(surface, accepted=True, up=up.tolist(), reason='multiscale_lines_with_wall_parallelism',
        vanishing_point=lines, horizontal_normal_evidence=surface,
        vertical_plane_evidence=walls, supporting_wall_families=agreements,
        confidence_kind='conjunctive_geometric_evidence_not_probability',
        limitation='Image lines supply up under the camera-up prior; wall normals check parallelism but do not independently determine gravity')


def vertical_plane_up(points):
    """Two independent vertical surface-normal families constrain their up axis.

    A single wall leaves an entire circle of possible directions; never infer
    up from its orthogonality score alone. The caller also requires image lines.
    """
    step = max(1, int(np.ceil(max(points.shape[:2])/128)))
    p = np.asarray(points[::step, ::step], float)
    valid = np.isfinite(p).all(-1) & (np.linalg.norm(p, axis=-1) > 1e-6)
    dx, dy = p[:-1, 1:] - p[:-1, :-1], p[1:, :-1] - p[:-1, :-1]
    normal = np.cross(dx, dy)
    length = np.linalg.norm(normal, axis=-1)
    edges = np.maximum(np.linalg.norm(dx, axis=-1), np.linalg.norm(dy, axis=-1))
    good = valid[:-1, :-1] & valid[:-1, 1:] & valid[1:, :-1] & (length > 1e-12)
    if good.sum() < 100:
        return dict(accepted=False, reason='insufficient_vertical_normals')
    good &= edges <= np.median(edges[good]) * 4
    normals = normal[good] / length[good, None]
    ys, xs = np.where(good)
    available = abs(normals[:, 1]) < np.sin(np.pi/4)
    families = []
    for _ in range(2):
        candidates = normals[available]
        if len(candidates) < 80:
            break
        candidates = candidates[::max(1, len(candidates)//128)][:128]
        scores = ((abs(normals @ candidates.T) > np.cos(np.deg2rad(8))) & available[:, None]).sum(0)
        direction = candidates[scores.argmax()]
        hit = (abs(normals @ direction) > np.cos(np.deg2rad(8))) & available
        if hit.mean() < .1:
            break
        _, _, vh = np.linalg.svd(normals[hit], full_matrices=False)
        direction = vh[0]
        spread = [float(np.ptp(xs[hit])/max(1,p.shape[1]-1)), float(np.ptp(ys[hit])/max(1,p.shape[0]-1))]
        if max(spread) < .5:
            break
        families.append(dict(normal=direction.tolist(), fraction=float(hit.mean()), image_span=spread))
        available &= abs(normals @ direction) < .8
    if len(families) != 2:
        return dict(accepted=False, reason='fewer_than_two_independent_vertical_families', families=families)
    up = np.cross(families[0]['normal'], families[1]['normal'])
    up /= np.linalg.norm(up)
    if up[1] < 0:
        up *= -1
    accepted = bool(up[1] > np.cos(np.pi/4))
    return dict(accepted=accepted, reason='two_vertical_surface_normal_families', up=up.tolist(),
                families=families, orthogonal_fraction=sum(f['fraction'] for f in families),
                confidence_kind='evidence_fractions_not_calibrated_probability')


def surface_up(points):
    step = max(1, int(np.ceil(max(points.shape[:2])/128)))
    p = np.asarray(points[::step, ::step], float)
    valid = np.isfinite(p).all(axis=-1) & (np.linalg.norm(p, axis=-1) > 1e-6)
    dx, dy = p[:-1, 1:]-p[:-1, :-1], p[1:, :-1]-p[:-1, :-1]
    n = np.cross(dx, dy)
    length = np.linalg.norm(n, axis=-1)
    edges = np.maximum(np.linalg.norm(dx, axis=-1), np.linalg.norm(dy, axis=-1))
    good = valid[:-1, :-1] & valid[:-1, 1:] & valid[1:, :-1] & (length > 1e-12)
    if good.sum() < 100:
        return dict(accepted=False, reason='insufficient_local_surface_normals')
    # Depth jumps are not surface orientation observations.
    good &= edges <= np.median(edges[good])*4
    normals = n[good]/length[good, None]
    normals[normals[:, 1] < 0] *= -1
    # Camera +Y supplies only sign and an explicit <=45 degree roll/pitch prior.
    candidates = normals[normals[:, 1] > np.cos(np.pi/4)]
    if len(candidates) < max(80, len(normals)*.05):
        return dict(accepted=False, reason='no_supported_up_cluster', normals=len(normals))
    candidates = candidates[::max(1, len(candidates)//128)][:128]
    scores = (normals @ candidates.T > np.cos(np.deg2rad(8))).sum(axis=0)
    up = candidates[int(scores.argmax())]
    consensus = normals @ up > np.cos(np.deg2rad(8))
    _, _, vh = np.linalg.svd(normals[consensus], full_matrices=False)
    up = vh[0] * (1 if vh[0, 1] >= 0 else -1)
    orthogonal = abs(normals @ up) < np.sin(np.deg2rad(8))
    ys, xs = np.where(good)
    spread = [float(np.ptp(xs[consensus])/max(1, p.shape[1]-1)),
              float(np.ptp(ys[consensus])/max(1, p.shape[0]-1))]
    accepted = bool(consensus.mean() >= .08 and orthogonal.mean() >= .15 and max(spread) >= .5)
    return dict(accepted=accepted, reason='surface_normal_consensus' if accepted else 'insufficient_spatial_or_orthogonal_evidence',
                up=up.tolist(), normals=len(normals), support_fraction=float(consensus.mean()),
                orthogonal_fraction=float(orthogonal.mean()), image_span=spread,
                confidence_kind='evidence_fractions_not_calibrated_probability',
                prior='camera +Y within 45 degrees; no semantic object pose',
                limitation='No independent image-line vanishing-point verification')
