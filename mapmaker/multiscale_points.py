"""Name-free zoomed point proposals with original-image area limits."""
import copy
import hashlib
import numpy as np
from .point_proposals import scan_small_instances
from .segmentation_regions import restore_crop_mask


def point_crop_boxes(image_size):
    width, height = image_size
    # Four overlapping views cover the full image, including both central seams.
    # No annotations, object names, detections or image-specific coordinates.
    cw, ch = (2 * width + 2) // 3, (2 * height + 2) // 3
    if min(cw, ch) < 128:
        return []
    return sorted(set((x, y, x+cw, y+ch)
                      for y in (0, height-ch) for x in (0, width-cw)))


def restore_point_record(record, mask, box, image_size):
    restored = restore_crop_mask(mask, box, image_size)
    if restored is None:
        return None
    rec = copy.deepcopy(record)
    offset = np.asarray(box[:2])
    rec['source_point'] = (np.asarray(rec['source_point']) + offset).tolist()
    rec['supporting_points'] = (np.asarray(rec['supporting_points']) + offset).tolist()
    for entry in rec.get('interior_confirmation', {}).get('evidence', []):
        entry['point'] = (np.asarray(entry['point']) + offset).tolist()
    y, x = np.where(restored)
    if not len(x):
        return None
    rec.update(source_crop=list(box), proposal_scale='overlapping_point_crop',
               area=int(restored.sum()),
               proposal_bbox=[int(x.min()), int(y.min()), int(x.max()+1), int(y.max()+1)],
               geometry_key=hashlib.sha256(np.packbits(restored).tobytes()).hexdigest())
    return rec, restored


def scan_point_crops(processor, image, *, side=16, batch_size=4, progress=None):
    """Run in the caller's inference/autocast context; return original pixel masks.

    Scores, stability and independent point confirmation are unchanged. Reject
    artificial crop-edge fragments before any proposal reaches mask selection.
    The caller retains responsibility for duplicate/recall and geometry review.
    """
    result, reports = [], []
    boxes = point_crop_boxes(image.size)
    for index, box in enumerate(boxes):
        crop = image.crop(box)
        state = processor.set_image(crop)
        def report(current, total):
            if progress:
                progress(index, len(boxes), current, total)
        masks, evidence = scan_small_instances(processor.model, state, crop.size,
            side=side, batch_size=batch_size, progress=report,
            reference_image_area=image.width*image.height)
        rejected = 0
        for rec, mask in masks:
            item = restore_point_record(rec, mask, box, image.size)
            if item is None:
                rejected += 1
            else:
                result.append(item)
        reports.append(dict(box=list(box), truncated_masks=rejected, **evidence))
    return result, dict(views=reports, retained_masks=len(result),
        uses_object_names=False, global_area_limits=True,
        scope='Additional point proposals, not measured recall or accepted objects')
