import numpy as np
import pytest
from mapmaker.feature_points import uncovered_feature_points
from mapmaker.point_proposals import point_grid, scan_small_instances
from test_point_proposals import Predictor


def test_thin_feature_missed_by_uniform_grid_gets_prompt_without_mask_edit():
    image = np.full((128, 128, 3), 180, np.uint8)
    image[:, 18:20] = 10
    covered = np.zeros((128, 128), bool)
    before = covered.copy()
    points = uncovered_feature_points(image, covered, side=8)
    uniform = point_grid((128, 128), 8)
    assert not ((uniform[:, 0] >= 18) & (uniform[:, 0] < 20)).any()
    assert ((points[:, 0] >= 18) & (points[:, 0] < 20)).any()
    np.testing.assert_array_equal(covered, before)
    assert len(points) <= 64
    assert len(uncovered_feature_points(image, np.ones_like(covered), side=8)) == 0
    assert len(uncovered_feature_points(np.full_like(image, 180), covered, side=8)) == 0


def test_explicit_prompts_keep_decoder_rejection_and_confirmation():
    points = np.array([[190., 190.], [210., 210.]])
    masks, report = scan_small_instances(Predictor(), {}, (400, 400), prompt_points=points)
    assert len(masks) == 1
    assert report['point_diagnostics']['prompt_points'] == points.tolist()
    for model in (Predictor(score=.7), Predictor(stable=False)):
        masks, _ = scan_small_instances(model, {}, (400, 400), prompt_points=points)
        assert not masks
    with pytest.raises(ValueError):
        scan_small_instances(Predictor(), {}, (400, 400), prompt_points=[[400., 2.]])
