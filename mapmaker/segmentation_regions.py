"""Use detector-localized image crops for unresolved small instances."""
import numpy as np


def crop_queries(prompts, regions, tags_by_view, aliases, full_masks, image_area):
    # Words only connect a detector proposal to its segmentation prompt.
    # No semantic categories, allowlists or object-specific thresholds.
    queries = []
    for region in regions:
        x0, y0, x1, y1 = region['box']
        # A detected instance elsewhere cannot explain a tag in this crop.
        # Count only mask evidence inside the actual region, using the same
        # area threshold as before. Words associate detector queries only.
        supported = {record['name'] for record, mask in full_masks
                     if np.count_nonzero(mask[y0:y1, x0:x1]) >= image_area * .003}
        unresolved = set(prompts) - supported
        tags = {aliases.get(tag, tag) for tag in tags_by_view.get(region['image'], [])}
        selected = [prompt for prompt in prompts if prompt in unresolved & tags]
        if selected:
            queries.append(dict(box=region['box'], prompts=selected))
    return queries


def restore_crop_mask(mask, box, image_size):
    """Reject crop-truncated fragments; preserve source-edge objects."""
    width, height = image_size
    x0, y0, x1, y1 = box
    mask = np.asarray(mask, dtype=bool)
    if mask.shape != (y1-y0, x1-x0):
        raise ValueError('Crop mask resolution differs from crop')
    if ((x0 > 0 and mask[:, 0].any()) or (x1 < width and mask[:, -1].any())
            or (y0 > 0 and mask[0].any()) or (y1 < height and mask[-1].any())):
        return None
    restored = np.zeros((height, width), dtype=bool)
    restored[y0:y1, x0:x1] = mask
    return restored
