"""Rejected development experiment: appearance-region box coverage is inadequate.

These are prompts, not object detections. SAM masks and the ordinary geometric
selection checks must validate them before reconstruction.
"""
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, find_objects
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components


def region_boxes(image, *, limit=96, max_resolution=384):
    image = Image.fromarray(np.asarray(image, np.uint8)).convert('RGB')
    original = np.asarray(image.size, float)
    image.thumbnail((max_resolution, max_resolution))
    rgb = gaussian_filter(np.asarray(image, float), sigma=(.7, .7, 0))
    h, w = rgb.shape[:2]
    if min(h, w) < 8:
        return []
    index = np.arange(h*w).reshape(h, w)
    left = np.concatenate([index[:, :-1].ravel(), index[:-1].ravel()])
    right = np.concatenate([index[:, 1:].ravel(), index[1:].ravel()])
    differences = np.linalg.norm(rgb.reshape(-1, 3)[left]-rgb.reshape(-1, 3)[right], axis=1)
    candidates = []
    for threshold in (6., 12., 24., 36.):
        keep = differences <= threshold
        graph = coo_matrix((np.ones(int(keep.sum()), bool), (left[keep], right[keep])), shape=(h*w, h*w)).tocsr()
        count, labels = connected_components(graph, directed=False)
        labels = labels.reshape(h, w)
        sizes = np.bincount(labels.ravel(), minlength=count)
        boundaries = np.zeros(count, float)
        boundary_counts = np.zeros(count, int)
        flat = labels.ravel()
        cross = flat[left] != flat[right]
        for ends in (left, right):
            np.add.at(boundaries, flat[ends[cross]], differences[cross])
            np.add.at(boundary_counts, flat[ends[cross]], 1)
        for label_id, bounds in enumerate(find_objects(labels+1)):
            area = int(sizes[label_id])
            if bounds is None or not max(12, h*w*.0005) <= area <= h*w*.15:
                continue
            ys, xs = bounds
            bw, bh = xs.stop-xs.start, ys.stop-ys.start
            occupancy = area/(bw*bh)
            if min(bw, bh) < 3 or occupancy < .2 or max(bw/w, bh/h) > .65:
                continue
            contrast = boundaries[label_id]/max(1, boundary_counts[label_id])
            box = np.array([xs.start/w, ys.start/h, xs.stop/w, ys.stop/h])
            candidates.append(dict(box=box, quality=float(contrast*min(occupancy, .8)),
                threshold=threshold, occupancy=occupancy, region_pixels=area))
    candidates.sort(key=lambda p: (-p['quality'], *p['box']))
    distinct = []
    for candidate in candidates:
        box = candidate['box']
        area = np.prod(box[2:]-box[:2])
        duplicate = False
        for other in distinct:
            obox = other['box']
            intersection = np.maximum(0, np.minimum(box[2:], obox[2:])-np.maximum(box[:2], obox[:2])).prod()
            union = area+np.prod(obox[2:]-obox[:2])-intersection
            if intersection/union > .8:
                duplicate = True
                break
        if duplicate:
            continue
        distinct.append(candidate)
    # Round-robin image cells prevent a textured corner consuming the budget.
    bins = {}
    for candidate in distinct:
        center = (candidate['box'][:2]+candidate['box'][2:])/2
        cell = tuple(np.minimum((center*4).astype(int), 3))
        bins.setdefault(cell, []).append(candidate)
    selected = []
    while bins and len(selected) < limit:
        for cell in sorted(list(bins)):
            if len(selected) == limit:
                break
            selected.append(bins[cell].pop(0))
            if not bins[cell]:
                del bins[cell]
    for candidate in selected:
        box = candidate.pop('box')
        candidate['box_xyxy_normalized'] = box.tolist()
        candidate['box_xyxy'] = (box*np.tile(original, 2)).tolist()
        candidate['uses_object_names'] = False
    return selected
