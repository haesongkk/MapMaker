from types import SimpleNamespace

import numpy as np
import pytest

from mapmaker.pointmap_guidance import additional_depth_guidance


class Reverse:
    training = False
    interval = (0., 1.)

    def __init__(self):
        self.calls = []

    def backbone(self, x, t, tokens, **kwargs):
        self.calls.append((tokens.copy(), dict(kwargs)))
        return x + (0. if kwargs.get('cfg') else tokens.sum())

    def _make_unconditional_args(self, args, kwargs):
        kwargs['cfg'] = True
        return args, kwargs

    def _cfg_step(self, conditional, unconditional, strength):
        return (1 + strength) * conditional - strength * unconditional

    def inner_forward(self, x, t, is_cond, strength, *args, **kwargs):
        conditional = self.backbone(x, t, *args, **kwargs)
        if is_cond:
            return conditional
        args, kwargs = self._make_unconditional_args(args, kwargs)
        return self._cfg_step(conditional, self.backbone(x, t, *args, **kwargs), strength)


class Pipeline:
    def __init__(self):
        self.reverse = Reverse()
        self.models = {'ss_generator': SimpleNamespace(reverse_fn=self.reverse)}
        self.embedder = SimpleNamespace(training=False, force_drop_modalities=[])
        self.condition_embedders = {'ss_condition_embedder': self.embedder}
        self.embeddings = 0

    def get_condition_input(self, embedder, data, mapping):
        self.embeddings += 1
        return (np.array([data['rgb'], 0. if embedder.force_drop_modalities else data['depth']]),), {}


def schedule(strength, interval, t):
    return strength if interval[0] <= t <= interval[1] else 0.


@pytest.mark.parametrize('strength,t,expected,calls', [(0., .5, 18., 2), (1., .5, 21., 3), (1., 2., 18., 2)])
def test_actual_prediction_and_mutating_unconditional_flag(strength, t, expected, calls):
    pipeline = Pipeline()
    with additional_depth_guidance(SimpleNamespace(_pipeline=pipeline), strength, schedule) as stats:
        args, kwargs = pipeline.get_condition_input(pipeline.embedder, {'rgb': 2., 'depth': 3.}, [])
        result = pipeline.reverse.inner_forward(np.array([8.]), t, False, 1., *args, **kwargs)
        assert result == expected
        assert len(pipeline.reverse.calls) == calls
        if calls == 3:
            assert pipeline.reverse.calls[-1][1] == {}
            assert stats['max_prediction_delta'] == 3.
            assert stats['max_condition_delta'] == 3.
        assert pipeline.embeddings == (1 if strength == 0 else 2)
    assert 'get_condition_input' not in pipeline.__dict__
    assert 'inner_forward' not in pipeline.reverse.__dict__
    assert pipeline.embedder.force_drop_modalities == []


def test_no_effect_rejected_and_methods_restored():
    pipeline = Pipeline()
    with pytest.raises(ValueError, match='did not change'):
        with additional_depth_guidance(SimpleNamespace(_pipeline=pipeline), 1., schedule):
            pipeline.get_condition_input(pipeline.embedder, {'rgb': 2., 'depth': 0.}, [])
    assert pipeline.embedder.force_drop_modalities == []
    assert 'get_condition_input' not in pipeline.__dict__
    assert 'inner_forward' not in pipeline.reverse.__dict__


def test_unrelated_embedder_is_untouched():
    pipeline = Pipeline()
    other = SimpleNamespace(force_drop_modalities=[])
    with additional_depth_guidance(SimpleNamespace(_pipeline=pipeline), 1., schedule) as stats:
        pipeline.get_condition_input(other, {'rgb': 2., 'depth': 3.}, [])
        assert stats['condition_pairs'] == 0
        assert pipeline.embeddings == 1
