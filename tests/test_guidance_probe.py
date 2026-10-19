from types import SimpleNamespace
import pytest
from scripts.probe_pointmap_guidance import temporary_guidance


@pytest.mark.parametrize('failure', [False, True])
def test_resident_guidance_is_restored_after_success_or_failed_inference(failure):
    class SupportedReverse:
        strength_pm = .25
        def inner_forward(self, x, t, is_cond, strength, strength_pm):
            return x + strength_pm
    reverse = SupportedReverse()
    pipeline = SimpleNamespace(ss_cfg_strength_pm=0.,
                               models={'ss_generator': SimpleNamespace(reverse_fn=reverse)})
    model = SimpleNamespace(_pipeline=pipeline)
    try:
        with temporary_guidance(model, 1.):
            assert pipeline.ss_cfg_strength_pm == 1.
            reverse.strength_pm = pipeline.ss_cfg_strength_pm
            if failure:
                raise RuntimeError('simulated inference failure')
    except RuntimeError:
        assert failure
    assert pipeline.ss_cfg_strength_pm == 0.
    assert reverse.strength_pm == .25


@pytest.mark.parametrize('strength', [-1., float('nan'), float('inf')])
def test_invalid_guidance_is_rejected_before_model_access(strength):
    with pytest.raises(ValueError):
        with temporary_guidance(None, strength):
            pytest.fail('Invalid setting entered inference')


def test_existing_attribute_does_not_prove_guidance_is_used():
    class LegacyReverse:
        strength_pm = 0.
        def inner_forward(self, x, t, is_cond, strength, *args, **kwargs):
            return x
    reverse = LegacyReverse()
    pipeline = SimpleNamespace(ss_cfg_strength_pm=0.,
        models={'ss_generator': SimpleNamespace(reverse_fn=reverse)})
    with pytest.raises(ValueError, match='no-op'):
        with temporary_guidance(SimpleNamespace(_pipeline=pipeline), 1.):
            pytest.fail('Unsupported generator entered inference')
    assert pipeline.ss_cfg_strength_pm == reverse.strength_pm == 0.
