"""Reuse SAM3 image features for identical image batches, without resizing them."""
import torch


def infer_with_vision_cache(model, inputs, cache):
    """Cache only within a scene/view. Preserve batch shape and exact pixel values.

    Call under no_grad/inference_mode with an eval model. Changing text does not
    invalidate visual features; changing any image pixel does. Keeping the same
    batch shape avoids introducing single-image/batched numerical differences.
    """
    if model.training:
        raise ValueError('Vision feature caching requires an eval model')
    kwargs = dict(inputs)
    pixels = kwargs.pop('pixel_values')
    key = (tuple(pixels.shape), pixels.dtype, pixels.device)
    entry = cache.get(key)
    if entry is None or not torch.equal(entry[0], pixels):
        entry = (pixels.clone(), model.get_vision_features(pixel_values=pixels))
        cache[key] = entry
    return model(vision_embeds=entry[1], **kwargs)
