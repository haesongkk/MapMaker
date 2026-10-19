"""Experimental image-feature prompts; no object labels or mask edits.

These points only request segmentation. Texture can produce features too, so
the caller must retain decoder quality and independent confirmation checks.
"""
import numpy as np
from scipy.ndimage import gaussian_laplace


def uncovered_feature_points(image, covered, *, side=16):
    rgb = np.asarray(image, dtype=float)
    covered = np.asarray(covered, dtype=bool)
    if rgb.ndim != 3 or rgb.shape[2] != 3 or covered.shape != rgb.shape[:2]:
        raise ValueError('Expected RGB image and same-size coverage mask')
    if not np.isfinite(rgb).all() or side < 1 or side > 32:
        raise ValueError('Expected finite pixels and bounded grid side')
    height, width = covered.shape
    gray = rgb @ np.array([.2126, .7152, .0722])
    # Both bright and dark narrow features. A response is not evidence of an
    # object or a physical support, and never directly expands a mask.
    # Remove DC before the finite-support derivative kernel: its tiny nonzero
    # sum otherwise produces false features even in a constant image.
    response = abs(gaussian_laplace(gray-gray.mean(), sigma=1.))
    response[covered] = 0
    threshold = max(float(response.max()) * .01, 1e-9)
    result = []
    for y0, y1 in zip(np.linspace(0, height, side+1, dtype=int)[:-1],
                      np.linspace(0, height, side+1, dtype=int)[1:]):
        for x0, x1 in zip(np.linspace(0, width, side+1, dtype=int)[:-1],
                          np.linspace(0, width, side+1, dtype=int)[1:]):
            block = response[y0:y1, x0:x1]
            if not block.size or block.max() <= threshold:
                continue
            y, x = np.unravel_index(np.argmax(block), block.shape)
            result.append([x0+x+.5, y0+y+.5])
    return np.asarray(result, dtype=float).reshape(-1, 2)
