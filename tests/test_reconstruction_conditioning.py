import numpy as np
import pytest
from mapmaker.reconstruction_conditioning import isolate_mask_rgb


@pytest.mark.parametrize('channels',[3,4])
def test_only_outside_rgb_changes_without_mutating_image_or_alpha(channels):
    image=np.arange(8*10*channels,dtype=np.uint8).reshape(8,10,channels)
    original=image.copy();mask=np.zeros((8,10),bool);mask[2:6,3:8]=True
    result=isolate_mask_rgb(image,mask)
    np.testing.assert_array_equal(image,original)
    np.testing.assert_array_equal(result[mask],original[mask])
    assert (result[~mask,:3]==127).all()
    if channels==4:np.testing.assert_array_equal(result[...,3],original[...,3])


def test_invalid_mask_cannot_silently_blank_the_target():
    with pytest.raises(ValueError):isolate_mask_rgb(np.zeros((8,10,3),np.uint8),np.zeros((8,10),bool))
    with pytest.raises(ValueError):isolate_mask_rgb(np.zeros((8,10,3),np.uint8),np.ones((8,10),np.uint8))


@pytest.mark.parametrize('change_depth',[False,True])
def test_actual_condition_tokens_measured_and_geometry_change_rejected(change_depth):
    from types import SimpleNamespace
    from mapmaker.reconstruction_conditioning import observe_condition_change
    class Pipeline:
        def __init__(self):self.condition_embedders={'ss_condition_embedder':object()}
        def get_condition_input(self,embedder,data,mapping):
            return (data['image']+data['pointmap'],),{}
    pipeline=Pipeline();model=SimpleNamespace(_pipeline=pipeline)
    baseline={'image':np.array([1.]),'pointmap':np.array([3.])}
    current={'image':np.array([2.]),'pointmap':np.array([4. if change_depth else 3.])}
    try:
        with observe_condition_change(model,baseline,np.array_equal) as stats:
            tokens,_=pipeline.get_condition_input(pipeline.condition_embedders['ss_condition_embedder'],current,[])
            assert not change_depth
            assert tokens[0]==5. and stats['max_condition_delta']==1.
    except ValueError:
        assert change_depth
    assert 'get_condition_input' not in pipeline.__dict__
