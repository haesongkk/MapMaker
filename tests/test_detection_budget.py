import numpy as np
from mapmaker.mask_selection import select_masks, MAX_RECONSTRUCTION_OBJECTS


def detections(count):
    values = []
    for i in range(count):
        mask = np.zeros((240, 240), bool)
        y, x = divmod(i, 8)
        mask[y*30:y*30+20, x*30:x*30+20] = True
        values.append((dict(name=f'object_{i}', confidence=.95), mask))
    return values


def test_valid_objects_beyond_legacy_twelve_are_preserved():
    raw = detections(20)
    selected = select_masks(raw, 240*240, limit=MAX_RECONSTRUCTION_OBJECTS)
    assert len(selected) == 20


def test_unlimited_candidate_stage_retains_masks_beyond_generation_budget():
    count = MAX_RECONSTRUCTION_OBJECTS + 8
    raw = detections(count)
    candidates = select_masks(raw, 240*240, limit=None)
    assert len(candidates) == count
    selected = select_masks(candidates, 240*240, limit=MAX_RECONSTRUCTION_OBJECTS)
    assert len(selected) == MAX_RECONSTRUCTION_OBJECTS
    assert sum(str(rec.get('rejected_reason', '')).startswith('object limit') for rec, _ in candidates) == 8
    renamed = [(dict(name='renamed', confidence=rec['confidence']), mask) for rec, mask in reversed(raw)]
    assert [rec['geometry_key'] for rec, _ in selected] == [rec['geometry_key'] for rec, _ in select_masks(renamed, 240*240, limit=MAX_RECONSTRUCTION_OBJECTS)]


def test_independent_objects_beyond_thirty_two_reach_generation():
    raw = detections(40)
    selected = select_masks(raw, 240*240, limit=MAX_RECONSTRUCTION_OBJECTS)
    assert len(selected) == 40
    assert all('rejected_reason' not in rec for rec, _ in selected)
