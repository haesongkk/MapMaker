import numpy as np
import pytest

from mapmaker.analysis_regions import analysis_boxes, rank_candidates


@pytest.mark.parametrize('size', [(2048, 1332), (1332, 2048), (1200, 400)])
def test_fine_views_cover_image_and_stay_in_bounds(size):
    w, h = size
    boxes = analysis_boxes(w, h)
    assert len(boxes) <= 14
    fine_coverage = np.zeros((h, w), bool)
    for x0, y0, x1, y1 in boxes:
        assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h
        if x1 - x0 < w * .4:
            fine_coverage[y0:y1, x0:x1] = True
    assert fine_coverage.all()


def test_small_images_do_not_generate_tiny_analysis_crops():
    assert analysis_boxes(640, 480) == []


def test_local_candidates_survive_many_globally_repeated_tags():
    common = [f'common_{i}' for i in range(45)]
    local = [f'local_{i}' for i in range(10)]
    views = {'full': common, 'crop_a': common + local, 'crop_b': common}
    selected, votes, overflow = rank_candidates(common + local, views, 'full', {}, limit=40)
    assert len(selected) == 40 and len(set(selected)) == 40
    assert sum(name in local for name in selected) == 8
    assert set(selected + overflow) == set(common + local)
    reordered = rank_candidates(list(reversed(common + local)), dict(reversed(list(views.items()))), 'full', {}, limit=40)
    assert reordered == (selected, votes, overflow)


def test_default_policy_does_not_discard_rare_local_detections():
    frequent = [f'frequent_{i}' for i in range(150)]
    rare = [f'rare_{i}' for i in range(20)]
    views = {'full': frequent, 'crop_a': frequent + rare, 'crop_b': frequent}
    selected, _, overflow = rank_candidates(frequent + rare, views, 'full', {})
    assert set(selected) == set(frequent + rare)
    assert len(selected) == 170 and not overflow
