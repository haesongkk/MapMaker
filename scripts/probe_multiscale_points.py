"""Compare zoomed point proposals with saved masks; never run 3D reconstruction."""
import argparse
import copy
import hashlib
from pathlib import Path
import numpy as np
from PIL import Image
from mapmaker.scene_run import read, write, sha, SAM3_CHECKPOINT
from mapmaker.mask_selection import select_masks, MAX_RECONSTRUCTION_OBJECTS


def verified_inputs(source, *, fresh_points=False):
    source = Path(source).resolve(strict=True)
    meta = read(source/'scene_metadata.json')
    def checked(name, digest):
        path = (source/name).resolve(strict=True)
        if not path.is_relative_to(source) or sha(path) != digest:
            raise ValueError('Source path/hash mismatch')
        return path
    image = Image.open(checked(meta['input_image'],meta['input_sha256'])).convert('RGB')
    if fresh_points:
        return image, [], [], meta
    raw = []
    for record in read(source/'masks/candidates.json'):
        mask = np.asarray(Image.open(checked(record['mask'],record['mask_sha256'])).convert('L')) > 0
        if mask.shape != (image.height,image.width):
            raise ValueError('Mask size mismatch')
        key = hashlib.sha256(np.packbits(mask).tobytes()).hexdigest()
        if key != record['geometry_key']:
            raise ValueError('Mask geometry digest mismatch')
        raw.append((copy.deepcopy(record),mask))
    baseline = select_masks(copy.deepcopy(raw),image.width*image.height,
                            limit=MAX_RECONSTRUCTION_OBJECTS,cross_view_small=True)
    expected = set()
    for obj in meta['objects']:
        if obj.get('mask'):
            mask=np.asarray(Image.open(checked(obj['mask'],obj['mask_sha256'])).convert('L'))>0
            expected.add(hashlib.sha256(np.packbits(mask).tobytes()).hexdigest())
    if {r['geometry_key'] for r,_ in baseline} != expected:
        raise ValueError('Current selection does not reproduce saved baseline masks')
    return image, raw, baseline, meta


def main(source, output=None, *, fresh_points=False, feature_points=False):
    source=Path(source).resolve(strict=True)
    image,raw,baseline,meta=verified_inputs(source,fresh_points=fresh_points)
    if output is None:
        return dict(verified_candidates=len(raw),baseline_selected=len(baseline),gpu_calls=0,
                    baseline_requires_gpu=fresh_points)
    output=Path(output).resolve()
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('Expected new separate output directory')
    import torch
    from sam3.model_builder import build_sam3_image_model
    from sam3.model.sam3_image_processor import Sam3Processor
    from mapmaker.point_proposals import validate_interactive_weights, scan_small_instances
    from mapmaker.multiscale_points import scan_point_crops
    if not torch.cuda.is_available():
        raise RuntimeError('Existing SAM3 GPU runtime required')
    processor=Sam3Processor(build_sam3_image_model(checkpoint_path=str(SAM3_CHECKPOINT),
        load_from_HF=False,enable_inst_interactivity=True))
    weights=validate_interactive_weights(processor.model,SAM3_CHECKPOINT)
    torch.manual_seed(42)
    baseline_evidence=None
    from mapmaker.decoder_audit import DecoderAudit
    audit = DecoderAudit() if feature_points else None
    with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
        if fresh_points:
            raw,baseline_evidence=scan_small_instances(processor.model,
                processor.set_image(image),image.size)
            baseline=select_masks(copy.deepcopy(raw),image.width*image.height,
                limit=MAX_RECONSTRUCTION_OBJECTS,cross_view_small=True)
        if feature_points:
            from mapmaker.feature_points import uncovered_feature_points
            covered = np.zeros((image.height, image.width), bool)
            for _, mask in baseline:
                covered |= mask
            points = uncovered_feature_points(np.asarray(image), covered)
            additions,evidence=scan_small_instances(processor.model,
                processor.set_image(image), image.size, prompt_points=points,
                observe_prediction=audit)
            evidence.update(strategy='uncovered_image_features',
                covered_pixels=int(covered.sum()), experimental=True)
        else:
            additions,evidence=scan_point_crops(processor,image)
    selected=select_masks(raw+additions,image.width*image.height,
                          limit=MAX_RECONSTRUCTION_OBJECTS,cross_view_small=True)
    output.mkdir(parents=True)
    audit_report = audit.save(output/'decoder-audit') if audit is not None else None
    baseline_records=[]
    for rec,mask in baseline:
        filename=rec['geometry_key']+'.png'
        Image.fromarray(mask.astype('uint8')*255).save(output/filename)
        baseline_records.append(dict(rec,mask=filename,mask_sha256=sha(output/filename)))
    records=[]
    for rec,mask in selected:
        filename=rec['geometry_key']+'.png'
        Image.fromarray(mask.astype('uint8')*255).save(output/filename)
        records.append(dict(rec,mask=filename,mask_sha256=sha(output/filename)))
    proposals=[]
    for rec,mask in additions:
        filename=rec['geometry_key']+'.png'
        Image.fromarray(mask.astype('uint8')*255).save(output/filename)
        proposals.append(dict(rec,mask=filename,mask_sha256=sha(output/filename)))
    report=dict(complete=True,source_image_sha256=meta['input_sha256'],
        source_candidates_sha256=None if fresh_points else sha(source/'masks/candidates.json'),
        checkpoint_sha256=sha(SAM3_CHECKPOINT),interactive_weights=weights,
        baseline_keys=sorted(r['geometry_key'] for r,_ in baseline),baseline=baseline_records,
        baseline_point_evidence=baseline_evidence,selected=records,
        additional_proposals=len(additions),proposals=proposals,point_crops=evidence,
        proposal_strategy='uncovered_image_features' if feature_points else 'multiscale_points',
        decoder_audit=audit_report,
        uses_object_names=False,source_unchanged=True,scene_complete=False,
        quality_gate_passed=False,
        comparison_mode='point_component_only' if fresh_points else 'saved_full_selection_plus_point_crops',
        scope='Mask proposal ablation only; fresh point baseline excludes text proposals and is not a full pipeline baseline; no 3D generation or quality acceptance')
    write(output/'report.json',report)
    return dict(additional_proposals=len(additions),selected=len(selected),scene_complete=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output',type=Path)
    group.add_argument('--verify-only',action='store_true')
    parser.add_argument('--fresh-points',action='store_true',
        help='Generate both baseline and zoomed point proposals; excludes text proposals')
    parser.add_argument('--feature-points',action='store_true',
        help='Compare uncovered feature prompts instead of zoomed grids')
    args=parser.parse_args()
    print(main(args.source,args.output,fresh_points=args.fresh_points,feature_points=args.feature_points))
