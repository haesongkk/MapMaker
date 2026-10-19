"""Bounded geometric confirmation of stable masks seen at only one grid point."""
import numpy as np
from scipy.ndimage import distance_transform_edt


def interior_confirmation_points(mask, original):
    """Two separated interior points, also separated from the original prompt."""
    mask = np.asarray(mask, bool)
    distance = distance_transform_edt(mask)
    y, x = np.where(mask & (distance >= max(1., float(distance.max()) * .25)))
    if len(x) < 2:
        return None
    points = np.column_stack([x + .5, y + .5])
    span = float(np.linalg.norm(np.ptp(points, axis=0)))
    if span <= 0:
        return None
    selected = [np.asarray(original, float)]
    result = []
    for _ in range(2):
        separation = np.min(np.linalg.norm(points[:, None] - np.asarray(selected)[None], axis=-1), axis=1)
        index = int(np.argmax(separation))
        if separation[index] < span * .25:
            return None
        result.append(points[index])
        selected.append(points[index])
    return np.asarray(result)


def confirm_single_mask(model, state, mask, original):
    points = interior_confirmation_points(mask, original)
    if points is None:
        return [], dict(reason='insufficient_separated_interior', points=0)
    height, width = mask.shape
    masks, scores, logits = model.predict_inst(state,
        point_coords=points[:, None, :], point_labels=np.ones((2, 1), np.int32),
        multimask_output=True, normalize_coords=True)
    masks = np.asarray(masks).reshape(2, -1, height, width)
    scores = np.asarray(scores).reshape(2, -1)
    logits = np.asarray(logits).reshape(2, scores.shape[1], *np.asarray(logits).shape[-2:])
    confirmed = []
    evidence = []
    for i, point in enumerate(points):
        best = None
        for j, score in enumerate(scores[i]):
            candidate = masks[i, j] > 0
            if not np.isfinite(score) or score < .88 or not candidate[int(point[1]), int(point[0])]:
                continue
            low = logits[i, j]
            stability = float(np.count_nonzero(low > 1.) / max(1, np.count_nonzero(low > -1.)))
            iou = float(np.count_nonzero(mask & candidate) / max(1, np.count_nonzero(mask | candidate)))
            if stability >= .95 and iou >= .8 and (best is None or iou > best['mask_iou']):
                best = dict(point=point.tolist(), mask_iou=iou, stability=stability, predicted_iou=float(score))
        if best is not None:
            confirmed.append(point.tolist())
            evidence.append(best)
    # Both independent interior queries must agree; a single repeat is not enough.
    return (confirmed if len(confirmed) == 2 else []), dict(
        reason='two_interior_queries_agree' if len(confirmed) == 2 else 'interior_queries_disagree',
        points=2, evidence=evidence)
