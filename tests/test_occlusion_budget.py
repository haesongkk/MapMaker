import itertools
import numpy as np
import pytest
from mapmaker.occlusion_budget import select_components


def test_allocation_matches_exhaustive_feasible_choices():
    rng=np.random.default_rng(219)
    for _ in range(40):
        sizes=rng.integers(1,10,8);values=rng.random(8)*sizes;budget=int(rng.integers(0,30))
        chosen=select_components(sizes,values,budget)
        feasible=[np.array(c,bool) for c in itertools.product((False,True),repeat=8) if np.dot(c,sizes)<=budget]
        assert np.dot(chosen,sizes)<=budget
        assert np.dot(chosen,values)==pytest.approx(max(np.dot(c,values) for c in feasible))


def test_entire_patch_selection_beats_greedy_density():
    np.testing.assert_array_equal(select_components([3,4,4],[5.,6.,6.],8),[False,True,True])
    np.testing.assert_array_equal(select_components([3,4],[5.,6.],2),[False,False])


def test_budget_does_not_force_zero_evidence_completion():
    assert not select_components([3,4],[0.,0.],7).any()
    with pytest.raises(ValueError):select_components([1],[float('nan')],4)
