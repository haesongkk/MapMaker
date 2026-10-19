import numpy as np
import pytest
from mapmaker.mask_expansion import expansion_evidence


def example():
    base = np.zeros((30, 30), bool)
    base[5:15, 5:15] = True
    full = base.copy()
    full[15:25, 5:7] = True
    return base, full, np.zeros_like(base), [[6., 7.], [9., 9.], [6., 20.]]


def test_thin_support_can_enter_probe_without_mutating_input():
    b, c, o, p = example()
    copies = [v.copy() for v in (b, c, o)]
    r = expansion_evidence(b, c, o, p)
    assert r['eligible_for_reconstruction_probe']
    assert not r['quality_gate_passed'] and not r['production_enabled']
    assert all(np.array_equal(a, v) for a, v in zip(copies, (b, c, o)))


def test_repeated_seed_cannot_fake_independent_support():
    b, c, o, p = example()
    assert 'insufficient_prompt_support' in expansion_evidence(b, c, o, [p[0]]*5)['reasons']


def test_small_other_object_is_preserved():
    b, c, o, p = example()
    o[18:20, 5:7] = True
    assert 'other_object_intrusion' in expansion_evidence(b, c, o, p)['reasons']


def test_original_loss_rejected_even_if_candidate_is_larger():
    b, c, o, p = example()
    c[5, 5:10] = False
    assert 'original_mask_loss' in expansion_evidence(b, c, o, p)['reasons']


def test_point_order_and_duplicates_do_not_change_evidence():
    b, c, o, p = example()
    assert expansion_evidence(b, c, o, p) == expansion_evidence(b, c, o, p[::-1]+p)


@pytest.mark.parametrize('points', [[[float('nan'), 0]], [[30, 0]], [[-1, 2]]])
def test_invalid_points_fail_closed(points):
    b, c, o, _ = example()
    with pytest.raises(ValueError):
        expansion_evidence(b, c, o, points)


def test_probe_mask_is_hash_checked_and_baseline_is_unchanged(tmp_path):
    from PIL import Image
    from mapmaker.mask_expansion import load_probe_mask
    from mapmaker.scene_run import write, sha
    (tmp_path/'input').mkdir()
    b, c, _, _ = example()
    path = tmp_path/'input/expanded.png'
    Image.fromarray(c.astype('uint8')*255).save(path)
    row = dict(original_sha256='a'*64, asset='input/expanded.png', sha256=sha(path))
    write(tmp_path/'input/mask_expansions.json', dict(masks=[row]))
    loaded, _ = load_probe_mask(tmp_path, 'a'*64, b.shape)
    assert np.array_equal(loaded, c)
    Image.fromarray(b.astype('uint8')*255).save(path)
    with pytest.raises(ValueError, match='checksum'):
        load_probe_mask(tmp_path, 'a'*64, b.shape)
