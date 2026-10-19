"""Experimental mask-expansion evidence, isolated from production selection.

Repeated prompts are correlated observations, not calibrated confidence.
The development thresholds below require held-out validation before promotion.
Only geometry enters this API; labels and object identifiers cannot affect it.
"""
import hashlib
import numpy as np


def load_probe_mask(source, original_sha, expected_shape):
    """Load a hash-verified experimental mask without modifying the baseline."""
    from PIL import Image
    from .scene_run import read, sha
    from .scene_transfer import safe_name
    manifest = read(source/'input/mask_expansions.json')
    rows = [r for r in manifest['masks'] if r['original_sha256'] == original_sha]
    if len(rows) != 1:
        raise ValueError('Expected one expansion for requested baseline mask')
    row = rows[0]
    safe_name(row['asset'])
    if sha(source/row['asset']) != row['sha256']:
        raise ValueError('Expansion mask checksum mismatch')
    mask = np.asarray(Image.open(source/row['asset']).convert('L')) > 0
    if mask.shape != tuple(expected_shape) or not mask.any():
        raise ValueError('Invalid expansion mask shape or empty mask')
    return mask, row


def expansion_evidence(original, candidate, occupied, supporting_points):
    masks = [np.asarray(x) for x in (original, candidate, occupied)]
    if any(x.dtype != bool or x.ndim != 2 for x in masks) or any(
            x.shape != masks[0].shape for x in masks):
        raise ValueError('Expected equally sized 2D boolean masks')
    original, candidate, occupied = masks
    points = np.asarray(supporting_points, dtype=float)
    if (points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all()
            or (points < 0).any() or (points >= original.shape[::-1]).any()):
        raise ValueError('Expected finite in-image supporting points')
    # A repeated coordinate is not additional evidence. All supporting seeds
    # must actually belong to this candidate.
    points = np.unique(points, axis=0)
    seed_inside = bool(len(points) and candidate[
        points[:, 1].astype(int), points[:, 0].astype(int)].all())
    area = int(original.sum())
    added = candidate & ~original
    coverage = float((original & candidate).sum() / max(1, area))
    ratio = float(candidate.sum() / max(1, area))
    intrusion = float((added & occupied).sum() / max(1, int(added.sum())))
    reasons = []
    if not area or not added.any():
        reasons.append('no_expansion')
    if len(points) < 3 or not seed_inside:
        reasons.append('insufficient_prompt_support')
    if coverage < .99:
        reasons.append('original_mask_loss')
    if not 1.1 <= ratio <= 2.:
        reasons.append('expansion_size')
    if intrusion > .01:
        reasons.append('other_object_intrusion')
    return dict(eligible_for_reconstruction_probe=not reasons, reasons=reasons,
                original_coverage=coverage, area_ratio=ratio,
                added_pixels=int(added.sum()), other_object_fraction=intrusion,
                distinct_points=len(points), seeds_inside=seed_inside,
                geometry_key=hashlib.sha256(np.packbits(candidate).tobytes()).hexdigest(),
                quality_gate_passed=False, production_enabled=False)
