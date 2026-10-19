"""Label-free mask budget with small-object slots and visible-region coverage."""
import hashlib
import numpy as np

MIN_AREA_FRACTION = .0005
SMALL_AREA_FRACTION = .003
SMALL_CONFIDENCE = .8
# Keep a bounded generation budget while allowing dense scenes to retain
# independent small regions beyond the previous 32-object ceiling.
MAX_RECONSTRUCTION_OBJECTS = 48
BASE_RECONSTRUCTION_BUDGET = 32


def rejection_reason(rec, image_area):
    threshold = SMALL_CONFIDENCE if rec['area'] < image_area * SMALL_AREA_FRACTION else .6
    if rec['area'] < max(64, image_area * MIN_AREA_FRACTION):
        return 'below small-object area floor'
    if rec['confidence'] < threshold:
        return f'mask confidence < {threshold}'
    return None


def select_masks(raw, image_area, limit=12, *, cross_view_small=False):
    # Agreement is a separate evidence route, never an inflated model score.
    from .mask_corroboration import corroborate
    evidence = {r['candidate_index']: r for r in corroborate(raw, image_area)} if cross_view_small else {}
    eligible = []
    for index, (rec, mask) in enumerate(raw):
        rec['area'] = int(mask.sum())
        rec.pop('rejected_reason', None)
        rec.pop('selection_evidence', None)
        reason = rejection_reason(rec, image_area)
        if reason == 'mask confidence < 0.8' and index in evidence:
            reason = None
            rec['selection_evidence'] = dict(route='cross_view_small_mask_agreement', **evidence[index])
        if reason is None and rec.get('proposal_method') == 'uniform_point_grid':
            rec['selection_evidence'] = dict(route='stable_point_mask_agreement',
                supporting_points=rec['supporting_points'], stability=rec['stability'],
                confidence_kind=rec['confidence_kind'])
        if reason:
            rec['rejected_reason'] = reason
        else:
            eligible.append((rec, mask))
    # The geometry digest breaks ties without consulting labels or prompt order.
    for rec, mask in eligible:
        rec['geometry_key'] = hashlib.sha256(np.packbits(mask).tobytes()).hexdigest()
    rank = lambda item: (-item[0]['confidence'], -item[0]['area'], item[0]['geometry_key'])
    small = sorted([x for x in eligible if x[0]['area'] < image_area*SMALL_AREA_FRACTION], key=rank)
    large = sorted([x for x in eligible if x[0]['area'] >= image_area*SMALL_AREA_FRACTION],
                   key=lambda x: (-x[0]['area'], *rank(x)))
    selected = []
    # Canonicalize aliases before budgeting, so aliases cannot consume reserved
    # slots and changing the budget does not change which mask represents them.
    reserved = 3
    order = small[:reserved] + large + small[reserved:]
    for rec, mask in order:
        duplicate = False
        for previous, other in selected:
            intersection = np.count_nonzero(mask & other)
            union = rec['area'] + previous['area'] - intersection
            containment = intersection / max(1, min(rec['area'], previous['area']))
            if intersection/max(1, union) > .8:
                duplicate = True
                break
            # Cross-label near-identical regions are aliases, not extra objects.
            if containment > .9 and min(rec['area'], previous['area'])/max(rec['area'], previous['area']) > .5:
                duplicate = True
                break
        if duplicate:
            rec['rejected_reason'] = 'duplicate mask'
        else:
            selected.append((rec, mask))
    if limit is not None and len(selected) > min(limit, BASE_RECONSTRUCTION_BUDGET):
        distinct_small = sorted([x for x in selected if x[0]['area'] < image_area*SMALL_AREA_FRACTION], key=rank)
        reserved = min(3, limit)
        budgeted = distinct_small[:reserved]
        pending = ([x for x in selected if x[0]['area'] >= image_area*SMALL_AREA_FRACTION]
                   + distinct_small[reserved:])
        covered = np.zeros(selected[0][1].shape, dtype=bool)
        for _, mask in budgeted:
            covered |= mask
        # Prefer unexplained visible pixels over more parts of an already
        # represented region, including small candidates beyond the reserved
        # slots. Size must not force a covered part ahead of new visible pixels.
        # This is budget allocation, not proof of duplication:
        # unselected masks remain recorded and no confidence threshold changes.
        while pending and len(budgeted) < limit:
            index = min(range(len(pending)), key=lambda i: (
                -int(np.count_nonzero(pending[i][1] & ~covered)), *rank(pending[i])))
            # Extra slots need as much new visible evidence as an independently
            # eligible small mask. Do not refill a larger budget with covered
            # parts that the coverage ranking had already moved behind objects.
            # This is allocation, not a declaration that nested masks are false.
            if (len(budgeted) >= BASE_RECONSTRUCTION_BUDGET
                    and np.count_nonzero(pending[index][1] & ~covered)
                    < max(64, image_area * MIN_AREA_FRACTION)):
                break
            item = pending.pop(index)
            budgeted.append(item)
            covered |= item[1]
        kept = {rec['geometry_key'] for rec, _ in budgeted}
        for rec, _ in selected:
            if rec['geometry_key'] not in kept:
                rec['rejected_reason'] = (f'object limit {limit}' if len(budgeted) >= limit
                    else 'additional budget requires new visible area above small-object floor')
        selected = budgeted
    return sorted(selected, key=lambda x: (-x[0]['area'], *rank(x)))
