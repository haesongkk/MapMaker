"""Image-line orientation with a camera fitted to the shared pointmap.

Pixel projection is fitted with signed focal directions; SAM3D coordinates do
not use the usual positive-focal OpenCV convention. No object labels are read.
"""
import numpy as np
from PIL import Image


def fit_camera(points):
    h, w = points.shape[:2]
    step = max(1, int(np.ceil(max(h, w) / 100)))
    y, x = np.mgrid[:h:step, :w:step]
    p = np.asarray(points[::step, ::step], float)
    valid = np.isfinite(p).all(-1) & (abs(p[..., 2]) > 1e-8)
    if valid.sum() < 100:
        return dict(accepted=False, reason='insufficient_projection_samples')
    rays = p[valid] / p[valid, 2, None]
    pixels = np.stack([x[valid], y[valid]], -1)
    keep = np.ones(len(rays), bool)
    for _ in range(4):
        coef, _, rank, _ = np.linalg.lstsq(rays[keep], pixels[keep], rcond=None)
        error = np.linalg.norm(rays @ coef - pixels, axis=1)
        keep = error <= max(2., float(np.quantile(error, .8)))
    matrix = np.vstack([coef.T, [0., 0., 1.]])
    coverage = np.ptp(pixels[keep], axis=0) / [w, h]
    accepted = bool(rank == 3 and np.linalg.cond(matrix) < 1e6 and
                    min(coverage) > .6 and np.quantile(error, .9) < .01 * np.hypot(w, h))
    return dict(accepted=accepted, reason='pointmap_projection_fit' if accepted else 'inconsistent_camera_projection',
                matrix=matrix.tolist(), residual_p90=float(np.quantile(error, .9)),
                image_span=coverage.tolist())


def image_segments(image, *, maximum_size=320):
    """Bounded gradient-directed Hough extraction, requiring contiguous edges."""
    image = Image.fromarray(np.asarray(image, dtype=np.uint8)).convert('L')
    original = np.array(image.size, float)
    image.thumbnail((maximum_size, maximum_size))
    a = np.asarray(image, float)
    gy, gx = np.gradient(a)
    magnitude = np.hypot(gx, gy)
    strong = magnitude > max(12., float(np.quantile(magnitude, .9)))
    y, x = np.where(strong)
    if len(x) < 40:
        return np.empty((0, 2, 2))
    theta = np.mod(np.arctan2(gy[y, x], gx[y, x]), np.pi)
    bins = 180
    angles = np.arange(bins) * np.pi / bins
    radius = int(np.ceil(np.hypot(*a.shape)))
    accumulator = np.zeros((bins, radius * 2 + 1), int)
    direction = np.rint(theta / np.pi * bins).astype(int) % bins
    for offset in range(-2, 3):
        k = (direction + offset) % bins
        rho = np.rint(x * np.cos(angles[k]) + y * np.sin(angles[k])).astype(int) + radius
        np.add.at(accumulator, (k, rho), 1)
    segments = []
    for _ in range(64):
        k, r = np.unravel_index(accumulator.argmax(), accumulator.shape)
        if accumulator[k, r] < 16:
            break
        angle = angles[k]
        normal = np.array([np.cos(angle), np.sin(angle)])
        tangent = np.array([-normal[1], normal[0]])
        xy = np.stack([x, y], -1)
        on = abs(xy @ normal - (r - radius)) < 1.5
        on &= abs(np.cos(theta - angle)) > np.cos(np.deg2rad(12))
        t = np.sort(xy[on] @ tangent)
        if len(t):
            groups = np.split(t, np.flatnonzero(np.diff(t) > 4) + 1)
            for group in groups:
                if len(group) >= 16 and np.ptp(group) >= .12 * radius:
                    endpoints = (r - radius) * normal + np.array([group[0], group[-1]])[:, None] * tangent
                    segments.append(endpoints * (original / image.size))
        for dk in range(-4, 5):
            kk = (k + dk) % bins
            rr = r if 0 <= k + dk < bins else 2 * radius - r
            accumulator[kk, max(0, rr - 5):rr + 6] = 0
    return np.asarray(segments).reshape(-1, 2, 2)


def vanishing_up(segments, matrix, image_size):
    segments = np.asarray(segments, float)
    if len(segments) < 4:
        return dict(accepted=False, reason='insufficient_image_lines', lines=len(segments))
    rays = np.concatenate([segments, np.ones((*segments.shape[:2], 1))], -1) @ np.linalg.inv(matrix).T
    planes = np.cross(rays[:, 0], rays[:, 1])
    norms = np.linalg.norm(planes, axis=1)
    valid = norms > 1e-12
    planes, segments = planes[valid] / norms[valid, None], segments[valid]
    lengths = np.linalg.norm(np.diff(segments, axis=1)[:, 0], axis=1)
    candidates = []
    for i in range(len(planes)):
        cross = np.cross(planes[i], planes[i+1:])
        norm = np.linalg.norm(cross, axis=1)
        for vector in cross[norm > .03] / norm[norm > .03, None]:
            if abs(vector[1]) > np.cos(np.pi / 4):
                candidates.append(vector if vector[1] > 0 else -vector)
    if not candidates:
        return dict(accepted=False, reason='no_conditioned_vertical_intersection')
    candidates = np.asarray(candidates)
    hits = abs(planes @ candidates.T) < np.sin(np.deg2rad(1.5))
    best = int((lengths @ hits).argmax())
    inliers = hits[:, best]
    _, singular, vh = np.linalg.svd(planes[inliers] * np.sqrt(lengths[inliers, None]), full_matrices=False)
    up = vh[-1] * (1 if vh[-1, 1] >= 0 else -1)
    span = np.ptp(segments[inliers].reshape(-1, 2), axis=0) / image_size
    fraction = float(lengths[inliers].sum() / lengths.sum())
    conditioned = len(singular) == 3 and singular[1] > singular[0] * .08
    accepted = bool(inliers.sum() >= 4 and min(span) > .25 and fraction > .25 and
                    conditioned and up[1] > np.cos(np.pi / 4))
    return dict(accepted=accepted, reason='image_line_vanishing_consensus' if accepted else 'weak_line_distribution',
                up=up.tolist(), inlier_lines=int(inliers.sum()), lines=len(planes), image_span=span.tolist(),
                length_fraction=fraction, confidence_kind='evidence_not_calibrated_probability')


def reconcile_orientation(surface, lines):
    """Independent agreement is required to certify a line-supported up axis."""
    result = dict(surface, vanishing_point=lines)
    if not lines.get('accepted'):
        return result
    if 'up' not in surface:
        return dict(result, accepted=False, reason='lines_without_surface_corroboration')
    angle = float(np.rad2deg(np.arccos(np.clip(np.dot(surface['up'], lines['up']), -1, 1))))
    result['evidence_disagreement_degrees'] = angle
    if angle > 8:
        return dict(result, accepted=False, reason='surface_and_vanishing_disagree')
    if surface.get('orthogonal_fraction', 0) < .15:
        return dict(result, accepted=False, reason='missing_orthogonal_surface_evidence')
    return dict(result, accepted=True, up=lines['up'], reason='vanishing_and_surface_agreement')


def select_line_scale(reports):
    """Keep supported fine-scale lines; contradictory scales veto orientation.

    Image rescalings are correlated observations, not independent confidence.
    """
    accepted = [r for r in reports if r.get('accepted')]
    if not accepted:
        return dict(reports[0], scale_evidence=reports)
    disagreement = max((float(np.rad2deg(np.arccos(np.clip(np.dot(a['up'],b['up']),-1,1))))
        for i,a in enumerate(accepted) for b in accepted[i+1:]), default=0.)
    if disagreement > 8.:
        return dict(accepted=False, reason='vanishing_scales_disagree',
            scale_disagreement_degrees=disagreement, scale_evidence=reports)
    selected = max(accepted, key=lambda r: (r['inlier_lines']*r['length_fraction']*min(r['image_span']),
                                           -r['maximum_size']))
    return dict(selected, scale_evidence=reports, scale_disagreement_degrees=disagreement,
        scale_policy='strongest spatially distributed line support; contradictory scales veto; not independent probabilities')
