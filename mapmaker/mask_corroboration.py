"""Label-independent cross-view evidence; does not inflate model confidence."""
import numpy as np


def corroborate(raw, image_area):
    """Record matching detections from distinct crops, independent of labels.

    Repeated model outputs are correlated evidence, not independent probability.
    This evidence route still needs fresh GPU quality validation; agreement can
    repeat a systematic detector error and is not proof of a real object.
    """
    boxes = []
    for record, mask in raw:
        y, x = np.where(mask)
        boxes.append((int(x.min()), int(y.min()), int(x.max()), int(y.max())) if len(x) else None)
    reports = []
    for i, (record, mask) in enumerate(raw):
        area = int(mask.sum())
        if (boxes[i] is None or not max(64, image_area*.0005) <= area < image_area*.003
                or not .6 <= record['confidence'] < .8):
            continue
        source = tuple(record.get('source_crop', ()))
        views = set()
        evidence = []
        for j, (other, other_mask) in enumerate(raw):
            view = tuple(other.get('source_crop', ()))
            if i == j or view == source or boxes[j] is None or other['confidence'] < .6:
                continue
            a, b = boxes[i], boxes[j]
            if min(a[2], b[2]) < max(a[0], b[0]) or min(a[3], b[3]) < max(a[1], b[1]):
                continue
            intersection = int((mask & other_mask).sum())
            union = int((mask | other_mask).sum())
            iou = intersection/max(1, union)
            if iou >= .8:
                views.add(view)
                evidence.append(dict(view=list(view), iou=iou, confidence=other['confidence']))
        if views:
            reports.append(dict(candidate_index=i, source_view=list(source),
                distinct_views=1+len(views), supporting_views=sorted([list(v) for v in views]),
                evidence=evidence, original_confidence=record['confidence'],
                uses_object_names=False,
                limitation='Correlated cross-view observations; not a calibrated probability'))
    return reports
