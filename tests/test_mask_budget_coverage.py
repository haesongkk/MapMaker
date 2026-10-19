import copy
import numpy as np
from mapmaker.mask_selection import select_masks


def box(x0, y0, x1, y1):
    mask = np.zeros((400, 400), bool)
    mask[y0:y1, x0:x1] = True
    return mask


def raw(masks):
    return [(dict(name=f'label{i}', confidence=.95), mask) for i, mask in enumerate(masks)]


def keys(items):
    return [r['geometry_key'] for r, _ in items]


def test_independent_region_is_not_displaced_by_contained_parts():
    whole = box(0, 0, 200, 200)
    part = box(0, 0, 200, 70)
    independent = box(250, 250, 280, 280)
    candidates = raw([whole, part, independent])
    result = select_masks(candidates, whole.size, limit=2)
    assert any(np.array_equal(m, independent) for _, m in result)
    assert any(np.array_equal(m, whole) for _, m in result)
    assert candidates[1][0]['rejected_reason'] == 'object limit 2'
    assert np.array_equal(candidates[1][1], part)


def test_small_aliases_cannot_consume_reserved_slots():
    small = [box(20+i*30, 20, 30+i*30, 30) for i in range(3)]
    large = [box(0, 100+i*60, 100, 150+i*60) for i in range(4)]
    candidates = raw([small[0], small[0].copy(), small[0].copy(), *small[1:], *large])
    result = select_masks(candidates, 160000, limit=4)
    for mask in small:
        assert sum(np.array_equal(m, mask) for _, m in result) == 1
    assert len(result) == 4


def test_names_and_input_order_do_not_change_coverage_budget():
    candidates = raw([box(0, 0, 200, 200), box(0, 0, 200, 70), box(250, 250, 280, 280), box(300, 300, 330, 330)])
    expected = keys(select_masks(copy.deepcopy(candidates), 160000, limit=2))
    for order in [list(reversed(candidates)), candidates[2:]+candidates[:2]]:
        renamed = [(dict(confidence=r['confidence']), m.copy()) for r, m in order]
        assert keys(select_masks(renamed, 160000, limit=2)) == expected


def test_no_budget_pressure_preserves_all_distinct_masks_and_thresholds():
    candidates = raw([box(0, 0, 200, 200), box(0, 0, 200, 70), box(250, 250, 280, 280)])
    assert keys(select_masks(copy.deepcopy(candidates), 160000, limit=32)) == keys(select_masks(copy.deepcopy(candidates), 160000, limit=None))
    tiny = box(350, 350, 360, 360)
    candidates.append((dict(confidence=.7), tiny))
    result = select_masks(candidates, 160000, limit=2)
    assert not any(np.array_equal(m, tiny) for _, m in result)
    assert candidates[-1][0]['rejected_reason'] == 'mask confidence < 0.8'


def test_fourth_small_region_beats_already_covered_large_part():
    small=[box(220+i*30,20,230+i*30,30) for i in range(4)]
    whole=box(0,100,200,300)
    part=box(0,100,200,170)
    candidates=raw([whole,part,*small])
    result=select_masks(copy.deepcopy(candidates),160000,limit=5)
    assert any(np.array_equal(m,whole) for _,m in result)
    assert all(any(np.array_equal(m,tiny) for _,m in result) for tiny in small)
    assert not any(np.array_equal(m,part) for _,m in result)
    renamed=[(dict(confidence=r['confidence']),m.copy()) for r,m in reversed(candidates)]
    assert keys(select_masks(renamed,160000,limit=5))==keys(result)


def test_extra_capacity_preserves_new_small_regions_without_refilling_covered_parts():
    small = [box(210+(i%6)*30, 10+(i//6)*30, 220+(i%6)*30, 20+(i//6)*30)
             for i in range(32)]
    whole = box(0, 0, 200, 300)
    part = box(0, 0, 200, 100)
    candidates = raw([whole, part, *small])
    result = select_masks(candidates, 160000, limit=48)
    assert len(result) == 33
    assert all(any(np.array_equal(m, tiny) for _, m in result) for tiny in small)
    assert not any(np.array_equal(m, part) for _, m in result)
    assert candidates[1][0]['rejected_reason'].startswith('additional budget')
    assert np.array_equal(candidates[1][1], part)
    renamed = [(dict(confidence=r['confidence']), m.copy()) for r, m in reversed(candidates)]
    assert keys(select_masks(renamed, 160000, limit=48)) == keys(result)
