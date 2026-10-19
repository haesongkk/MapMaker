import numpy as np
from mapmaker.point_proposals import point_grid, scan_small_instances


class Predictor:
    def __init__(self, *, stable=True, score=.95, single=False):
        self.stable, self.score, self.single = stable, score, single

    def predict_inst(self, state, *, point_coords, point_labels, **kwargs):
        count = len(point_coords)
        masks = np.zeros((count, 3, 400, 400), bool)
        scores = np.zeros((count, 3))
        logits = np.full((count, 3, 16, 16), -5.)
        for i, seed in enumerate(point_coords[:, 0]):
            if 180 <= seed[0] < 220 and 180 <= seed[1] < 220:
                if self.single and (seed[0] > 200 or seed[1] > 200):
                    continue
                masks[i, 0, 180:220, 180:220] = True
                scores[i, 0] = self.score
                logits[i, 0, 5:11, 5:11] = 5. if self.stable else .2
            # A confident whole-image answer must not become a small object.
            masks[i, 1] = True
            scores[i, 1] = .99
            logits[i, 1] = 5.
        return masks, scores, logits


def test_uniform_grid_is_inside_image_and_covers_every_cell():
    points = point_grid((640, 480), 16)
    assert points.shape == (256, 2)
    assert (points > 0).all() and (points < [640, 480]).all()
    assert len(set(map(tuple, (points/[640, 480]*16).astype(int)))) == 256


def test_point_consensus_proposes_unknown_small_object_without_text():
    masks, report = scan_small_instances(Predictor(), {}, (400, 400), side=16, batch_size=3)
    assert len(masks) == 1 and masks[0][1].sum() == 1600
    assert len(masks[0][0]['supporting_points']) == 4
    assert masks[0][0]['confidence_kind'] == 'predicted_mask_iou_not_object_presence'
    assert report['uses_object_names'] is False
    diagnostic = report['point_diagnostics']
    counts = np.asarray(diagnostic['counts'])
    assert counts.shape == (256, 4)
    np.testing.assert_array_equal(counts.sum(1), np.full(256, 3))
    for column, key in enumerate(diagnostic['columns'][:3]):
        assert counts[:, column].sum() == report['rejections'][key]
    points = point_grid((400, 400), 16)
    eligible = counts[:, 3] > 0
    assert eligible.sum() == 4
    assert ((points[eligible] >= 180) & (points[eligible] < 220)).all()


def test_unstable_or_low_quality_predictions_do_not_create_objects():
    for predictor in (Predictor(stable=False), Predictor(score=.7), Predictor(single=True)):
        masks, _ = scan_small_instances(predictor, {}, (400, 400), side=16)
        assert masks == []


def test_checkpoint_guard_refuses_uninitialized_interactive_weights(monkeypatch):
    import sys
    import types
    import pytest
    from mapmaker.point_proposals import validate_interactive_weights
    parameter = types.SimpleNamespace(shape=(2, 3))
    model = types.SimpleNamespace(state_dict=lambda: {'inst_interactive_predictor.model.decoder.weight': parameter})
    checkpoint = {'tracker.decoder.weight': parameter}
    monkeypatch.setitem(sys.modules, 'torch', types.SimpleNamespace(load=lambda *a, **k: checkpoint))
    assert validate_interactive_weights(model, 'unused')['checkpoint_coverage'] == 'complete'
    checkpoint.clear()
    with pytest.raises(RuntimeError, match='does not cover'):
        validate_interactive_weights(model, 'unused')
