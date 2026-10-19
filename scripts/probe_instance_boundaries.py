"""Read-only SAM3 point-prompt audit of saved instance boundaries.

This diagnostic never replaces/deletes masks or regenerates objects. Agreement
is evidence about a boundary, not proof that a mask is a complete object.
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

from mapmaker.point_confirmation import interior_confirmation_points
from mapmaker.scene_run import read, write, sha, SAM3_CHECKPOINT


def audit_points(mask):
    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        return None
    y, x = np.unravel_index(np.argmax(distance_transform_edt(mask)), mask.shape)
    first = np.array([x + .5, y + .5])
    others = interior_confirmation_points(mask, first)
    return None if others is None else np.vstack([first, others])


def boundary_metrics(reference, candidate):
    intersection = int(np.count_nonzero(reference & candidate))
    area = int(candidate.sum())
    return dict(area=area, reference_coverage=intersection / max(1, int(reference.sum())),
                candidate_inside_reference=intersection / max(1, area),
                mask_iou=intersection / max(1, int(np.count_nonzero(reference | candidate))))


def main(source, output):
    source, output = source.resolve(strict=True), output.resolve()
    if output == source or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('Diagnostic output must be separate from source')
    if output.exists():
        raise FileExistsError(output)
    meta = read(source / 'scene_metadata.json')
    image_path = (source / meta['input_image']).resolve(strict=True)
    if not image_path.is_relative_to(source):
        raise ValueError('Source image escapes source directory')
    if sha(image_path) != meta['input_sha256']:
        raise ValueError('Source image hash mismatch')
    image = Image.open(image_path).convert('RGB')
    width, height = image.size
    selected = []
    for obj in meta['objects']:
        if obj.get('status') != 'generated':
            continue
        path = (source / obj['mask']).resolve(strict=True)
        if not path.is_relative_to(source) or sha(path) != obj['mask_sha256']:
            raise ValueError('Source mask path/hash mismatch')
        mask = np.asarray(Image.open(path).convert('L')) > 0
        if mask.shape != (height, width):
            raise ValueError('Source mask dimensions mismatch')
        # The existing small-instance scan already covers masks below 1%.
        if mask.sum() >= width * height * .01:
            selected.append((obj['mask_sha256'], mask))
    selected = sorted({key: mask for key, mask in selected}.items())
    if len(selected) > 32:
        raise ValueError('Diagnostic exceeds the current 32-object scene bound')
    import torch
    from sam3.model_builder import build_sam3_image_model
    from sam3.model.sam3_image_processor import Sam3Processor
    from mapmaker.point_proposals import validate_interactive_weights
    if not torch.cuda.is_available():
        raise RuntimeError('Existing SAM3 GPU runtime required')
    processor = Sam3Processor(build_sam3_image_model(
        checkpoint_path=str(SAM3_CHECKPOINT), load_from_HF=False, enable_inst_interactivity=True))
    weights = validate_interactive_weights(processor.model, SAM3_CHECKPOINT)
    output.mkdir(parents=True)
    report = dict(source_image_sha256=sha(image_path), checkpoint_sha256=sha(SAM3_CHECKPOINT),
                  interactive_weights=weights, uses_object_names=False, changes_source=False,
                  selected_count=len(selected), maximum_point_prompts=96, records=[], completed=False,
                  limitation='Point consistency does not establish semantic completeness or authorize mask replacement')
    torch.manual_seed(42)
    with torch.inference_mode(), torch.autocast('cuda', dtype=torch.bfloat16):
        state = processor.set_image(image)
        for key, reference in selected:
            points = audit_points(reference)
            record = dict(mask_sha256=key, area=int(reference.sum()), queries=[])
            report['records'].append(record)
            if points is None:
                record['abstained'] = 'insufficient_separated_interior'
                continue
            masks, scores, logits = processor.model.predict_inst(state,
                point_coords=points[:, None, :], point_labels=np.ones((3, 1), np.int32),
                multimask_output=True, normalize_coords=True)
            scores = np.asarray(scores).reshape(3, -1)
            masks = np.asarray(masks).reshape(3, -1, height, width)
            logits = np.asarray(logits).reshape(3, scores.shape[1], *np.asarray(logits).shape[-2:])
            directory = output / key
            directory.mkdir()
            for i, point in enumerate(points):
                query = dict(point=point.tolist(), candidates=[])
                record['queries'].append(query)
                for j, score in enumerate(scores[i]):
                    candidate = masks[i, j] > 0
                    low = logits[i, j]
                    stability = float(np.count_nonzero(low > 1.) / max(1, np.count_nonzero(low > -1.)))
                    metrics = boundary_metrics(reference, candidate)
                    asset = directory / f'{i}-{j}.png'
                    Image.fromarray(candidate.astype('uint8') * 255).save(asset)
                    finite = bool(np.isfinite(score))
                    seed_inside = bool(candidate[int(point[1]), int(point[0])])
                    query['candidates'].append(dict(**metrics, predicted_iou=float(score) if finite else None,
                        stability=stability, seed_inside=seed_inside,
                        passes_existing_decoder_filters=bool(finite and score >= .88 and stability >= .95 and seed_inside),
                        mask=asset.relative_to(output).as_posix(), mask_sha256=sha(asset)))
            write(output / 'boundary-audit.json', report)
            print(dict(completed=len(report['records']), total=len(selected)), flush=True)
    report['completed'] = True
    write(output / 'boundary-audit.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    main(args.source, args.output)
