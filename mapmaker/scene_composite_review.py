"""Suppress a failed compound mesh only when independent masks retain its pixels."""
import hashlib
import numpy as np
from PIL import Image
from scipy.ndimage import label
from .scene_projection import silhouette_evidence


def compound_coverage(parent, children, valid):
    """Unexplained visible components, including small ones, veto suppression."""
    area = int(parent.sum())
    if area < 192 or np.count_nonzero(parent & valid) < .95*area or len(children) < 3:
        return None
    components, _ = label(parent, np.ones((3, 3)))
    sizes = np.bincount(components.ravel())[1:]
    major = sizes[sizes >= max(64, .02*area)]
    if len(major) < 3 or major.max() > .5*area:
        return None
    union = np.logical_or.reduce(list(children.values()))
    residual = parent & ~union
    remainder, _ = label(residual, np.ones((3, 3)))
    remaining_sizes = np.bincount(remainder.ravel())[1:]
    if residual.sum() > .01*area or (len(remaining_sizes) and remaining_sizes.max() >= 64):
        return None
    return dict(major_components=len(major), retained_fraction=float((parent & union).sum()/area),
        unrepresented_pixels=int(residual.sum()),
        largest_unrepresented_component=int(remaining_sizes.max()) if len(remaining_sizes) else 0)


def review_reconstructed_composites(run, scene, objects, points):
    from .scene_geometry import triangles
    from .scene_placement import remove_object_tree
    masks = {o['id']: np.asarray(Image.open(run/o['mask']).convert('L')) > 0 for o in objects}
    if not masks:
        return []
    shape = next(iter(masks.values())).shape
    if any(mask.shape != shape for mask in masks.values()):
        raise ValueError('Source masks have different resolutions')
    valid = np.isfinite(points).all(-1) & (np.linalg.norm(points, axis=-1) > 1e-6)
    valid = np.asarray(Image.fromarray(valid).resize(shape[::-1], Image.Resampling.NEAREST))
    ordered = sorted(objects, key=lambda o: (int(masks[o['id']].sum()),
        hashlib.sha256(np.packbits(masks[o['id']]).tobytes()).hexdigest()))
    decisions = []
    for obj in ordered:
        parent = masks[obj['id']]
        area = int(parent.sum())
        children = {other['id']: masks[other['id']] for other in ordered
            if other['status'] == 'generated' and other['id'] != obj['id']
            and 64 <= masks[other['id']].sum() < .8*area
            and np.count_nonzero(parent & masks[other['id']]) >= 64}
        coverage = compound_coverage(parent, children, valid)
        if coverage is None:
            continue
        projection = silhouette_evidence(triangles(scene, obj['id']), points, parent)
        if (not projection['accepted'] or projection['mask_covered_fraction'] >= .55
                or projection['silhouette_outside_mask_fraction'] < .8):
            continue
        child_projection = {key: silhouette_evidence(triangles(scene, key), points, mask)
                            for key, mask in children.items()}
        if any(not value['accepted'] or value['mask_covered_fraction'] < .7
               for value in child_projection.values()):
            continue
        # A well-fitting whole object is not removed merely because part masks
        # exist. Here the parent mesh fails to explain the visible input, and
        # already-generated children preserve every substantial visible region.
        obj.update(status='duplicate', duplicate_of=list(children))
        remove_object_tree(scene, obj['id'])
        decisions.append(dict(object_id=obj['id'], duplicate_of=list(children),
            reason='failed_compound_mesh_with_visible_regions_preserved',
            uses_object_names=False, coverage=coverage, projection=projection,
            child_projection=child_projection))
    return decisions
