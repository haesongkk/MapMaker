"""Small-instance proposals from uniform point prompts, without object words."""
import hashlib
import numpy as np


def validate_interactive_weights(model, checkpoint_path):
    """Refuse an interactive decoder whose parameters were not in the checkpoint."""
    import torch
    checkpoint = torch.load(str(checkpoint_path), map_location='cpu', weights_only=True, mmap=True)
    checkpoint = checkpoint.get('model', checkpoint)
    prefix = 'inst_interactive_predictor.model.'
    expected = {name: value.shape for name, value in model.state_dict().items() if name.startswith(prefix)}
    if not expected:
        raise RuntimeError('SAM3 interactive decoder is unavailable')
    missing = [name for name, shape in expected.items()
               if 'tracker.'+name[len(prefix):] not in checkpoint
               or checkpoint['tracker.'+name[len(prefix):]].shape != shape]
    if missing:
        raise RuntimeError(f'SAM3 checkpoint does not cover {len(missing)} interactive parameters')
    return dict(interactive_parameter_tensors=len(expected), checkpoint_coverage='complete')


def point_grid(image_size, side=32):
    width, height = image_size
    axis = (np.arange(side, dtype=float)+.5)/side
    x, y = np.meshgrid(axis*width, axis*height)
    return np.stack([x.ravel(), y.ravel()], axis=1)


def scan_small_instances(model, state, image_size, *, side=32, batch_size=4, progress=None,
                         reference_image_area=None, prompt_points=None, observe_prediction=None):
    """Keep stable, high predicted-IoU masks agreed on by distinct point seeds.

    Predicted mask IoU is not object-presence probability. Score provenance is
    retained; a repeated texture can still require rejection by geometry review.
    """
    width, height = image_size
    reference_area = width * height if reference_image_area is None else reference_image_area
    if not np.isfinite(reference_area) or reference_area < width * height:
        raise ValueError('Reference image area must include the complete crop')
    points = point_grid(image_size, side) if prompt_points is None else np.asarray(prompt_points, float)
    if (points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all()
            or len(points) > 1024 or (points < 0).any()
            or (points >= [width, height]).any()):
        raise ValueError('Expected at most 1024 finite in-image prompt points')
    method = 'uniform_point_grid' if prompt_points is None else 'explicit_image_points'
    candidates = []
    by_digest = {}
    popcount = np.unpackbits(np.arange(256, dtype=np.uint8)[:, None], axis=1).sum(1)
    rejections = dict(predicted_iou=0, area_or_seed=0, stability=0, point_agreement=0)
    point_columns = ['predicted_iou', 'area_or_seed', 'stability', 'eligible_before_consensus']
    point_counts = np.zeros((len(points), len(point_columns)), dtype=np.int32)
    minimum = max(64, reference_area*.0005)
    for start in range(0, len(points), batch_size):
        seeds = points[start:start+batch_size]
        if progress:
            progress(start, len(points))
        masks, scores, logits = model.predict_inst(state,
            point_coords=seeds[:, None, :], point_labels=np.ones((len(seeds), 1), np.int32),
            multimask_output=True, normalize_coords=True)
        masks = np.asarray(masks).reshape(len(seeds), -1, height, width)
        scores = np.asarray(scores).reshape(len(seeds), -1)
        logits = np.asarray(logits).reshape(len(seeds), scores.shape[1], *np.asarray(logits).shape[-2:])
        for i, seed in enumerate(seeds):
            for j, score in enumerate(scores[i]):
                if observe_prediction is not None:
                    # Diagnostics receive copies and cannot alter decoder data,
                    # prompt positions or selection decisions.
                    observe_prediction(start+i, j, seed.copy(), float(score),
                                       (masks[i, j] > 0).copy(), logits[i, j].copy())
                if not np.isfinite(score) or score < .88:
                    rejections['predicted_iou'] += 1
                    point_counts[start+i, 0] += 1
                    continue
                mask = masks[i, j] > 0
                area = int(mask.sum())
                if not minimum <= area <= reference_area*.01 or not mask[int(seed[1]), int(seed[0])]:
                    rejections['area_or_seed'] += 1
                    point_counts[start+i, 1] += 1
                    continue
                low = logits[i, j]
                stability = float(np.count_nonzero(low > 1.)/max(1, np.count_nonzero(low > -1.)))
                if stability < .95:
                    rejections['stability'] += 1
                    point_counts[start+i, 2] += 1
                    continue
                point_counts[start+i, 3] += 1
                record = dict(name='object', confidence=float(score),
                    confidence_kind='predicted_mask_iou_not_object_presence',
                    proposal_method=method, source_point=seed.tolist(),
                    stability=stability, area=area,
                    geometry_key=hashlib.sha256(np.packbits(mask).tobytes()).hexdigest())
                # Merge exact repeats eagerly to bound original-resolution memory.
                previous = by_digest.get(record['geometry_key'])
                if previous is not None:
                    if seed.tolist() not in previous['supporting_points']:
                        previous['supporting_points'].append(seed.tolist())
                    previous['confidence'] = max(previous['confidence'], float(score))
                else:
                    record['supporting_points'] = [seed.tolist()]
                    y, x = np.where(mask)
                    record['proposal_bbox'] = [int(x.min()), int(y.min()), int(x.max()+1), int(y.max()+1)]
                    candidates.append((record, np.packbits(mask)))
                    by_digest[record['geometry_key']] = record
    retained = []
    confirmation = dict(maximum_candidates=32, attempted_candidates=0, points=0,
                        confirmed_candidates=0, records=[], uses_object_names=False)
    observed_seeds = {r['geometry_key']: tuple(map(tuple, r['supporting_points'])) for r, _ in candidates}
    for record, packed in sorted(candidates, key=lambda item: item[0]['geometry_key']):
        seeds = set(observed_seeds[record['geometry_key']])
        box = np.asarray(record['proposal_bbox'])
        for other, other_packed in candidates:
            if record is other:
                continue
            if min(record['area'], other['area']) < .8*max(record['area'], other['area']):
                continue
            obox = np.asarray(other['proposal_bbox'])
            if np.any(np.minimum(box[2:], obox[2:]) <= np.maximum(box[:2], obox[:2])):
                continue
            intersection = int(popcount[np.bitwise_and(packed, other_packed)].sum())
            if intersection/max(1, record['area']+other['area']-intersection) >= .8:
                seeds.update(observed_seeds[other['geometry_key']])
        if len(seeds) == 1 and confirmation['attempted_candidates'] < confirmation['maximum_candidates']:
            from .point_confirmation import confirm_single_mask
            mask = np.unpackbits(packed, count=width*height).reshape(height, width).astype(bool)
            extra, evidence = confirm_single_mask(model, state, mask, next(iter(seeds)))
            confirmation['attempted_candidates'] += 1
            confirmation['points'] += evidence['points']
            confirmation['records'].append(dict(geometry_key=record['geometry_key'], **evidence))
            if extra:
                seeds.update(map(tuple, extra))
                confirmation['confirmed_candidates'] += 1
                record['interior_confirmation'] = evidence
        if len(seeds) >= 2:
            record['supporting_points'] = [list(p) for p in sorted(seeds)]
            mask = np.unpackbits(packed, count=width*height).reshape(height, width).astype(bool)
            retained.append((record, mask))
        else:
            rejections['point_agreement'] += 1
    return retained, dict(points=len(points), retained_masks=len(retained),
        grid_side=side if prompt_points is None else None, batch_size=batch_size, minimum_predicted_iou=.88,
        minimum_stability=.95, minimum_agreeing_points=2,
        maximum_image_area_fraction=.01, reference_image_area=reference_area,
        uses_object_names=False, rejections=rejections,
        interior_confirmation=confirmation,
        point_diagnostics=dict(columns=point_columns, counts=point_counts.tolist(),
            point_order='point_grid row-major cell centers' if prompt_points is None else 'explicit input order',
            prompt_points=None if prompt_points is None else points.tolist(), image_size=[width, height],
            scope='Decoder outcomes per prompt; eligible is before cross-point consensus and final selection'),
        limitation='Point-grid candidates; not semantic object-presence probabilities or measured recall')
