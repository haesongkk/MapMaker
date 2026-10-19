"""Measured local planes for object support proposals, never collision certificates."""
import numpy as np
from .scene_geometry import HorizontalSurface, contact_footprint, inside_support_polygon


def measured_support_plane(vertices, faces, limit, tolerance):
    """Fit only finite triangle hits beneath actual low object geometry.

    A generated object's whole bounds or semantic label cannot establish a
    support plane. The caller must still validate contact, source and body path.
    """
    feet = contact_footprint(vertices, max_tilt_degrees=8.)
    query = HorizontalSurface(faces)
    bottom = float(vertices[:, 1].min())
    hits = []
    for foot in feet:
        height = query.height(foot[[0, 2]], maximum=bottom+limit)
        if height is not None and abs(height-foot[1]) <= limit:
            hits.append([foot[0], height, foot[2]])
    evidence = dict(method='finite_object_triangle_hits', queries=len(feet), hits=len(hits))
    if len(hits) < 3:
        return None, dict(evidence, reason='insufficient_triangle_hits')
    hits = np.asarray(hits)
    center = (vertices.min(0)+vertices.max(0))/2
    if not inside_support_polygon(hits[:, [0, 2]], center[[0, 2]]):
        return None, dict(evidence, reason='support_does_not_enclose_center')
    anchor = hits.mean(0)
    design = np.column_stack([hits[:, 0]-anchor[0], hits[:, 2]-anchor[2], np.ones(len(hits))])
    if np.linalg.matrix_rank(design) < 3:
        return None, dict(evidence, reason='degenerate_triangle_hits')
    fit = np.linalg.lstsq(design, hits[:, 1]-anchor[1], rcond=None)[0]
    residual = float(np.max(np.abs(design@fit-(hits[:, 1]-anchor[1]))))
    normal = np.array([-fit[0], 1., -fit[1]])
    normal /= np.linalg.norm(normal)
    evidence.update(max_residual=residual, tolerance=float(tolerance))
    if residual > tolerance or normal[1] <= .96:
        return None, dict(evidence, reason='nonplanar_or_steep_support')
    anchor[1] += fit[2]
    return dict(normal=normal.tolist(), point=anchor.tolist()), dict(evidence,
        reason='measured_local_support_plane', requires_source_contact_collision_checks=True)
