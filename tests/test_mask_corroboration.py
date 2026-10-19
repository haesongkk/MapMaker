import numpy as np
from mapmaker.mask_corroboration import corroborate


def item(name, view, confidence=.7, offset=0):
    mask = np.zeros((400, 400), bool)
    mask[100:115, 100+offset:115+offset] = True
    return dict(name=name, confidence=confidence, source_crop=view), mask


def test_distinct_view_agreement_preserves_confidence_and_ignores_names():
    raw = [item('a', [0, 0, 200, 200]), item('b', [50, 50, 250, 250], .75)]
    result = corroborate(raw, 160000)
    assert len(result) == 2 and all(r['distinct_views'] == 2 for r in result)
    assert raw[0][0]['confidence'] == .7 and raw[1][0]['confidence'] == .75
    for record, _ in raw: record['name'] = 'renamed'
    assert corroborate(raw, 160000) == result


def test_aliases_in_same_crop_and_disagreeing_masks_are_not_corroboration():
    raw = [item('a', [0, 0, 200, 200]), item('b', [0, 0, 200, 200])]
    assert corroborate(raw, 160000) == []
    raw[1] = item('b', [50, 50, 250, 250], offset=10)
    assert corroborate(raw, 160000) == []


def test_low_confidence_or_too_small_proposals_are_not_promoted():
    assert corroborate([item('a', [0, 0, 200, 200], .5),
        item('a', [50, 50, 250, 250], .5)], 160000) == []
    assert corroborate([item('a', [0, 0, 200, 200]),
        item('a', [50, 50, 250, 250])], 1000000) == []


def test_selection_requires_agreeing_distinct_views_and_ignores_labels_and_order():
    import copy
    from mapmaker.mask_selection import select_masks
    raw = [item('a', [0, 0, 200, 200]), item('b', [50, 50, 250, 250], .75)]
    assert select_masks(copy.deepcopy(raw), 160000) == []
    selected = select_masks(copy.deepcopy(raw), 160000, cross_view_small=True)
    assert len(selected) == 1 and selected[0][0]['confidence'] == .75
    renamed = copy.deepcopy(raw[::-1])
    for record, _ in renamed:
        record['name'] = ''
    result = select_masks(renamed, 160000, cross_view_small=True)
    assert result[0][0]['geometry_key'] == selected[0][0]['geometry_key']
    for bad in ([item('a', [0, 0, 200, 200]), item('b', [0, 0, 200, 200])],
                [item('a', [0, 0, 200, 200]), item('b', [50, 50, 250, 250], offset=10)]):
        assert select_masks(bad, 160000, cross_view_small=True) == []
