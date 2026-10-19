"""Source-view geometry checks without object labels or semantic categories."""
import numpy as np
from PIL import Image, ImageDraw
from .scene_vanishing import fit_camera


def silhouette_evidence(faces, points, mask):
    camera = fit_camera(points)
    if not camera['accepted']:
        return dict(accepted=False, reason='camera_fit_rejected')
    h, w = points.shape[:2]
    ratio = min(1., 192/max(h, w))
    shape = (max(1, round(w*ratio)), max(1, round(h*ratio)))
    faces = np.asarray(faces, float)
    valid_depth = points[..., 2][np.isfinite(points).all(-1) & (abs(points[..., 2]) > 1e-6)]
    depth_sign = np.sign(np.median(valid_depth))
    valid = np.isfinite(faces).all((1, 2)) & (faces[..., 2]*depth_sign > 1e-6).all(1)
    faces = faces[valid]
    if not len(faces):
        return dict(accepted=False, reason='no_faces_in_observed_camera_halfspace')
    uv = (faces/faces[..., 2, None]) @ np.asarray(camera['matrix']).T
    uv = uv[..., :2]*ratio
    valid = (uv.max(1) >= 0).all(1) & (uv.min(1) < np.array(shape)).all(1)
    valid &= (abs(uv) < 1e6).all((1, 2))
    canvas = Image.new('1', shape)
    draw = ImageDraw.Draw(canvas)
    for face in uv[valid]:
        draw.polygon([tuple(point) for point in face], fill=1)
    predicted = np.asarray(canvas, bool)
    observed = np.asarray(Image.fromarray(np.asarray(mask, np.uint8)*255).resize(shape, Image.Resampling.NEAREST)) > 0
    intersection = int((predicted & observed).sum())
    return dict(accepted=True, mask_pixels=int(observed.sum()), silhouette_pixels=int(predicted.sum()),
        mask_covered_fraction=intersection/max(1, int(observed.sum())),
        silhouette_outside_mask_fraction=int((predicted & ~observed).sum())/max(1, int(predicted.sum())),
        silhouette_iou=intersection/max(1, int((predicted | observed).sum())),
        limitation='Includes occluded and hidden geometry; insufficient alone to reject an object')


def inconsistent_spanning_context(mask, points, faces, *, region_evidence=None):
    from .mask_geometry import structural_mask_evidence
    evidence = region_evidence if region_evidence is not None else structural_mask_evidence(mask, points, minimum_borders=2)
    if evidence is None:
        return None
    projection = silhouette_evidence(faces, points, mask)
    # Sparse, image-spanning, independently observed planes AND gross source-view
    # overcompletion are required together. A large/occluded object alone is not
    # a room, and the replacement is explicitly unclassified observed context.
    if (not projection['accepted'] or projection['mask_covered_fraction'] < .7
            or projection['silhouette_outside_mask_fraction'] < .8):
        return None
    return dict(evidence, observed_context=True, projection=projection,
        reason='multiplane_spanning_mask_with_gross_mesh_overcompletion',
        limitation='Visible surfaces only; hidden completion discarded, room category unknown')


def route_inconsistent_context(run, scene, objects, points):
    from .scene_geometry import triangles
    from .mask_geometry import structural_mask_evidence
    from .scene_placement import remove_object_tree
    h, w = points.shape[:2]
    proposals = []
    for obj in objects:
        mask = np.asarray(Image.open(run/obj['mask']).convert('L').resize((w, h), Image.Resampling.NEAREST)) > 0
        region = structural_mask_evidence(mask, points, minimum_borders=2)
        if region is None:
            continue
        evidence = inconsistent_spanning_context(mask, points, triangles(scene, obj['id']), region_evidence=region)
        if evidence is not None:
            proposals.append((obj, evidence))
    if len(proposals) == len(objects):
        return []  # Current pipeline requires at least one verified object root.
    for obj, evidence in proposals:
        obj.update(status='structural', structural_evidence=evidence)
        remove_object_tree(scene, obj['id'])
    return [obj['id'] for obj, _ in proposals]
