"""Controlled RGB context intervention for paired reconstruction experiments."""
import numpy as np
from contextlib import contextmanager


def isolate_mask_rgb(image, mask, *, background=127):
    """Preserve selected pixels and dimensions, replace only unselected RGB.

    This is an experimental input transform, not a production quality policy.
    Original pointmap, mask, seed and camera frame must be kept by the caller.
    """
    image, mask = np.asarray(image), np.asarray(mask)
    if image.ndim != 3 or image.shape[2] not in (3,4) or image.dtype != np.uint8:
        raise ValueError('Expected uint8 RGB or RGBA image')
    if mask.dtype != bool or mask.shape != image.shape[:2] or not mask.any():
        raise ValueError('Expected matching nonempty Boolean mask')
    if not isinstance(background,int) or not 0 <= background <= 255:
        raise ValueError('Expected byte-valued neutral background')
    result=image.copy()
    result[~mask,:3]=background
    return result


@contextmanager
def observe_condition_change(model, baseline_inputs, equal):
    """Verify changed RGB tokens on the actual inference conditioning path."""
    from .pointmap_guidance import max_delta
    pipeline=model._pipeline
    embedder=pipeline.condition_embedders['ss_condition_embedder']
    original=pipeline.get_condition_input
    sentinel=object()
    saved=pipeline.__dict__.get('get_condition_input',sentinel)
    stats=dict(condition_pairs=0,max_condition_delta=0.,geometry_inputs_unchanged=True)
    def condition_input(condition_embedder,input_dict,input_mapping):
        current=original(condition_embedder,input_dict,input_mapping)
        if condition_embedder is not embedder:return current
        for key in baseline_inputs:
            if key not in ('image','rgb_image') and not equal(baseline_inputs[key],input_dict[key]):
                stats['geometry_inputs_unchanged']=False
                raise ValueError('RGB intervention changed non-RGB conditioning: '+key)
        baseline=original(condition_embedder,baseline_inputs,input_mapping)
        delta=max_delta(current[0],baseline[0])
        if delta<=0:raise ValueError('RGB intervention did not change condition tokens')
        stats['condition_pairs']+=1
        stats['max_condition_delta']=max(stats['max_condition_delta'],delta)
        return current
    try:
        pipeline.get_condition_input=condition_input
        yield stats
    finally:
        if saved is sentinel:del pipeline.get_condition_input
        else:pipeline.get_condition_input=saved
