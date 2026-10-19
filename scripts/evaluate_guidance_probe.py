"""Compare paired diagnostic meshes on CPU without declaring scene quality."""
import argparse
from pathlib import Path
import numpy as np
from PIL import Image
import trimesh
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_transfer import safe_name
from mapmaker.scene_replay import pose_matrix
from mapmaker.reconstruction_evidence import candidate_faces, assess


def compare(source, probe, *, progress=None):
    source, probe = Path(source), Path(probe)
    meta = read(source/'scene_metadata.json')
    report = read(probe/'logs/guidance_comparison.json')
    if not all(report.get(k) for k in ('completed', 'guidance_restored', 'source_scene_unchanged')):
        raise ValueError('A complete diagnostic result is required')
    method=report.get('guidance_method')
    if method not in ('baseline_cfg_plus_depth_difference_v1','masked_rgb_context_v1','controlled_seed_alternative_v1','controlled_mask_expansion_v1'):
        raise ValueError('Diagnostic did not prove an active guidance implementation')
    if method=='controlled_seed_alternative_v1':
        assert report['seed']==43 and report['baseline_seed']==42
        assert report['candidate_additional_guidance']==0.
        assert report['conditioning_mode']=='seed_alternative'
    elif method=='controlled_mask_expansion_v1':
        assert report['seed'] == 42 and report['candidate_additional_guidance'] == 0.
        assert report['conditioning_mode'] == 'mask_expansion'
    elif method=='masked_rgb_context_v1':
        assert report['candidate_additional_guidance']==0.
        for item in report['objects']:
            evidence=item.get('rgb_conditioning_evidence',{})
            if (not evidence.get('geometry_inputs_unchanged') or not evidence.get('target_pixels_unchanged')
                    or evidence.get('condition_pairs',0)<=0 or evidence.get('max_condition_delta',0)<=0
                    or evidence.get('original_pixels_sha256')==evidence.get('modified_pixels_sha256')):
                raise ValueError('Missing measured RGB-only conditioning effect')
    elif report['candidate_additional_guidance'] > 0:
        for item in report['objects']:
            evidence = item.get('guidance_evidence', {})
            if not all(evidence.get(k, 0) > 0 for k in
                       ('condition_pairs', 'prediction_pairs', 'max_condition_delta', 'max_prediction_delta')):
                raise ValueError('Missing measured guidance effect')
    assert report['seed'] == (43 if method=='controlled_seed_alternative_v1' else 42) and report['baseline_additional_guidance'] == 0.
    assert report['source_scene_sha256'] == sha(source/'scene.glb')
    assert report['source_input_sha256'] == meta['input_sha256'] == sha(source/meta['input_image'])
    assert report['pointmap_sha256'] == meta['pointmap']['sha256'] == sha(source/meta['pointmap']['asset'])
    objects = {o['id']:o for o in meta['objects'] if o['status']=='generated'}
    if report.get('target_masks'):
        requested=set(report['target_masks'])
        assert requested <= {o['mask_sha256'] for o in objects.values()}
        objects={k:o for k,o in objects.items() if o['mask_sha256'] in requested}
    assert len(report['objects']) == len(objects)
    assert {o['object_id'] for o in report['objects']} == set(objects)
    with np.load(source/meta['pointmap']['asset'], allow_pickle=False) as archive:
        points = archive['points']
    records = []
    for item in report['objects']:
        obj = objects[item['object_id']]
        original = obj.get('reconstruction_review', {}).get('original_artifact')
        baseline_asset = original['asset'] if original else obj['asset']
        baseline_pose = read(source/original['pose']) if original else obj['pose']
        baseline_hash = original['sha256'] if original else obj['asset_sha256']
        assert item['baseline_asset'] == baseline_asset
        assert item['baseline_sha256'] == baseline_hash == sha(source/baseline_asset)
        assert item['baseline_pose'] == baseline_pose
        assert item['mask_sha256'] == obj['mask_sha256'] == sha(source/obj['mask'])
        if method=='masked_rgb_context_v1':
            import hashlib
            from mapmaker.reconstruction_conditioning import isolate_mask_rgb
            original=np.asarray(Image.open(source/meta['input_image']),dtype=np.uint8)
            original_mask=np.asarray(Image.open(source/obj['mask']).convert('L'))>0
            modified=isolate_mask_rgb(original,original_mask)
            rgb=item['rgb_conditioning_evidence']
            assert hashlib.sha256(original.tobytes()).hexdigest()==rgb['original_pixels_sha256']
            assert hashlib.sha256(modified.tobytes()).hexdigest()==rgb['modified_pixels_sha256']
        safe_name(item['asset'])
        assert sha(probe/item['asset']) == item['sha256']
        mask = np.asarray(Image.open(source/obj['mask']).convert('L').resize(
            points.shape[1::-1], Image.Resampling.NEAREST)) > 0
        expansion_mask = None
        if method == 'controlled_mask_expansion_v1':
            from mapmaker.mask_expansion import load_probe_mask
            original_shape = np.asarray(Image.open(source/obj['mask'])).shape[:2]
            expanded, provenance = load_probe_mask(source, obj['mask_sha256'], original_shape)
            assert item['mask_expansion_evidence'] == provenance
            expansion_mask = np.asarray(Image.fromarray(expanded).resize(
                points.shape[1::-1], Image.Resampling.NEAREST)) > 0
        evidence = []
        expanded_evidence = []
        for path, pose in ((source/baseline_asset, baseline_pose), (probe/item['asset'], item['pose'])):
            matrix = pose_matrix(pose)
            if not np.isfinite(matrix).all():
                raise ValueError('Nonfinite candidate transform')
            asset = trimesh.load(path, force='scene', process=False)
            faces = candidate_faces(asset, matrix)
            evidence.append(assess(faces, points, mask,visible_depth=method in ('controlled_seed_alternative_v1','controlled_mask_expansion_v1')))
            if expansion_mask is not None:
                expanded_evidence.append(assess(faces, points, expansion_mask, visible_depth=True))
        record = dict(object_id=obj['id'], baseline=evidence[0], candidate=evidence[1])
        if expanded_evidence:
            record['expanded_mask_comparison'] = dict(baseline=expanded_evidence[0], candidate=expanded_evidence[1])
        records.append(record)
        if progress is not None:
            progress(dict(source_run_id=meta['run_id'], completed_objects=len(records),
                total_objects=len(report['objects']), records=list(records),
                comparison_sha256=sha(probe/'logs/guidance_comparison.json'),
                completed=False, quality_passed=False))
    return dict(source_run_id=meta['run_id'], paired_objects=len(records), records=records,
        additional_pointmap_guidance=report['candidate_additional_guidance'],
        conditioning_method=method,
        source_scene_sha256=report['source_scene_sha256'], uses_object_names=False,
        quality_passed=False, scope='Raw reconstruction source evidence before scene correction',
        limitation='Visible agreement cannot certify hidden shape, support, intersections, or scene quality')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('probe', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if any(args.output.resolve().is_relative_to(p.resolve()) for p in (args.source, args.probe)):
        raise ValueError('Comparison output must be outside the source and probe artifacts')
    write(args.output, compare(args.source, args.probe))
