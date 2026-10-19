"""Disjoint observed target regions for fitting ambiguous composite meshes.

Smaller masks retain their observations. Parent fitting uses the residual;
all generated meshes, including their hidden shape, remain intact.
"""
import hashlib
import numpy as np


def composite_residuals(masks, points):
    valid = np.isfinite(points).all(-1) & (np.linalg.norm(points,axis=-1)>1e-6)
    order = sorted(masks, key=lambda key:(int(masks[key].sum()),
        hashlib.sha256(np.packbits(masks[key]).tobytes()).hexdigest()))
    result={}
    for parent in order:
        mask=masks[parent];area=int(mask.sum())
        if area < mask.size*.05 or np.count_nonzero(mask & valid) < area*.95:
            continue
        children=[key for key in order if key!=parent and 64 <= masks[key].sum() < area*.5
                  and np.count_nonzero(mask & masks[key]) >= masks[key].sum()*.7]
        if len(children)<2:
            continue
        owned=np.logical_or.reduce([masks[key] for key in children]) & mask
        coverage=float(owned.sum()/area)
        residual=mask & ~owned
        if coverage < .2 or residual.sum() < max(128,area*.1):
            continue
        result[parent]=(residual,dict(child_ids=children,child_coverage=coverage,
            residual_pixels=int(residual.sum()),original_pixels=area,
            reason='overlapping_composite_visible_surface_ownership',
            hidden_shape='unknown',uses_object_names=False))
    return result
