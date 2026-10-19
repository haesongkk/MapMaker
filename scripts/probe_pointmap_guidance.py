"""Paired, development-only SAM3D regeneration from saved masks and pointmap.

Requires the existing GPU model runtime. Never changes the source run or the
production pipeline. Outputs require separate source/scene quality validation.
"""
import argparse
from contextlib import contextmanager, nullcontext
import math
import inspect
from pathlib import Path
import sys


@contextmanager
def temporary_guidance(model, strength):
    if not math.isfinite(strength) or strength < 0:
        raise ValueError('Guidance must be finite and nonnegative')
    pipeline = model._pipeline
    reverse = pipeline.models['ss_generator'].reverse_fn
    # The released checkpoint uses a different CFG class: assigning an arbitrary
    # strength_pm attribute succeeds there but does not change its forward pass.
    method = getattr(reverse, 'inner_forward', None)
    if method is None or 'strength_pm' not in inspect.signature(method).parameters:
        raise ValueError('Generator does not consume pointmap guidance; refusing a no-op experiment')
    previous = pipeline.ss_cfg_strength_pm
    reverse_previous = reverse.strength_pm
    try:
        pipeline.ss_cfg_strength_pm = strength
        yield
    finally:
        # The official sampler also writes the resident reverse function.
        pipeline.ss_cfg_strength_pm = previous
        reverse.strength_pm = reverse_previous


def main(source, output, strength, conditioning='depth_guidance', target_masks=None):
    if not math.isfinite(strength) or strength < 0:
        raise ValueError('Guidance must be finite and nonnegative')
    if conditioning not in ('depth_guidance','masked_rgb','seed_alternative','mask_expansion') or (conditioning!='depth_guidance' and strength!=0):
        raise ValueError('RGB comparison must preserve baseline guidance')
    source, output = source.resolve(strict=True), output.resolve()
    if output.is_relative_to(source):
        raise ValueError('Experiment output must be outside the source run')
    import numpy as np
    from PIL import Image
    import torch
    from mapmaker.scene_run import read, write, sha, SAM3D_REPO
    from mapmaker.runtime_paths import SAM3D_CHECKPOINT
    if not torch.cuda.is_available():
        raise RuntimeError('The existing SAM3D GPU runtime is required')
    meta = read(source/'scene_metadata.json')
    assert sha(SAM3D_CHECKPOINT) == meta['pipeline']['pipeline_sha256']
    import subprocess
    revision = subprocess.check_output(['git', '-C', str(SAM3D_REPO), 'rev-parse', 'HEAD'], text=True).strip()
    assert revision == meta['pipeline']['sam3d_source_revision']
    assert sha(source/meta['pointmap']['asset']) == meta['pointmap']['sha256']
    assert meta['pointmap']['frame'] == 'sam3d_pytorch3d_camera'
    assert sha(source/'scene.glb') == meta['placement']['scene_sha256']
    objects = sorted((o for o in meta['objects'] if o['status']=='generated'),
                     key=lambda o: o['mask_sha256'])
    if target_masks:
        requested=set(target_masks)
        if len(requested)!=len(target_masks) or not requested <= {o['mask_sha256'] for o in objects}:
            raise ValueError('Unknown or repeated diagnostic target mask')
        objects=[o for o in objects if o['mask_sha256'] in requested]
    for obj in objects:
        assert sha(source/obj['mask']) == obj['mask_sha256']
        assert sha(source/obj['asset']) == obj['asset_sha256']
        review = obj.get('reconstruction_review', {})
        if review.get('original_artifact'):
            original = review['original_artifact']
            assert sha(source/original['asset']) == original['sha256']
            assert sha(source/original['pose']) == original['pose_sha256']
        elif review.get('selected_seed', 42) != 42:
            raise ValueError('Missing seed-42 baseline artifact')
    output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(SAM3D_REPO/'notebook'))
    from inference import Inference, load_image
    from sam3d_objects.model.backbone.generator.classifier_free_guidance import get_strength
    from mapmaker.pointmap_guidance import additional_depth_guidance
    model = Inference(str(SAM3D_CHECKPOINT), compile=False)
    baseline_strength = float(model._pipeline.ss_cfg_strength_pm)
    if baseline_strength != 0.:
        raise ValueError('Saved baseline assumes additional pointmap guidance 0')
    image = load_image(str(source/meta['input_image']))
    with np.load(source/meta['pointmap']['asset'], allow_pickle=False) as archive:
        points = torch.from_numpy(archive['points'].copy()).to(model._pipeline.device)
    records = []
    report = dict(source=str(source), source_scene_sha256=sha(source/'scene.glb'),
        source_input_sha256=sha(source/meta['input_image']),
        pointmap_sha256=meta['pointmap']['sha256'], checkpoint_config_sha256=sha(SAM3D_CHECKPOINT),
        sam3d_source_revision=revision,
        seed=43 if conditioning=='seed_alternative' else 42, baseline_seed=42, baseline_additional_guidance=baseline_strength,
        candidate_additional_guidance=strength, objects=records, completed=False,
        guidance_backend=type(model._pipeline.models['ss_generator'].reverse_fn).__qualname__,
        guidance_method={'depth_guidance':'baseline_cfg_plus_depth_difference_v1','masked_rgb':'masked_rgb_context_v1','seed_alternative':'controlled_seed_alternative_v1','mask_expansion':'controlled_mask_expansion_v1'}[conditioning],
        target_masks=list(target_masks or []), conditioning_mode=conditioning,
        quality_passed=False, uses_object_names=False)
    write(output/'comparison.json', report)
    try:
        context=additional_depth_guidance(model,strength,get_strength) if conditioning=='depth_guidance' else nullcontext({})
        with context as guidance_stats:
            for index, obj in enumerate(objects):
                guidance_stats.update(condition_pairs=0, prediction_pairs=0,
                                      max_condition_delta=0., max_prediction_delta=0.)
                mask = np.asarray(Image.open(source/obj['mask']).convert('L')) > 0
                expansion_evidence = {}
                if conditioning == 'mask_expansion':
                    from mapmaker.mask_expansion import load_probe_mask
                    mask, expansion_evidence = load_probe_mask(source, obj['mask_sha256'], mask.shape)
                rgb_evidence={}
                if conditioning=='masked_rgb':
                    import hashlib
                    from mapmaker.reconstruction_conditioning import isolate_mask_rgb, observe_condition_change
                    isolated=isolate_mask_rgb(image,mask)
                    assert np.array_equal(isolated[mask],image[mask])
                    rgba=model.merge_mask_to_rgba(image,mask)
                    pipeline=model._pipeline
                    with torch.no_grad(), pipeline.device:
                        baseline_points=pipeline.compute_pointmap(rgba,points)['pointmap']
                        baseline_inputs=pipeline.preprocess_image(rgba,pipeline.ss_preprocessor,pointmap=baseline_points)
                    with observe_condition_change(model,baseline_inputs,
                            lambda a,b:torch.allclose(a,b,rtol=0,atol=0,equal_nan=True)) as rgb_stats:
                        result=model(isolated,mask,seed=42,pointmap=points)
                    if not rgb_stats['condition_pairs']:raise RuntimeError('No RGB conditioning measurement')
                    rgb_evidence=dict(rgb_stats, original_pixels_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
                        modified_pixels_sha256=hashlib.sha256(isolated.tobytes()).hexdigest(),
                        target_pixels_unchanged=True, background_value=127)
                    del baseline_inputs,baseline_points,isolated
                else:
                    result = model(image, mask, seed=43 if conditioning=='seed_alternative' else 42, pointmap=points)
                if strength > 0 and (guidance_stats['condition_pairs'] == 0 or
                        guidance_stats['prediction_pairs'] == 0 or
                        guidance_stats['max_prediction_delta'] <= 0):
                    raise RuntimeError('Depth guidance has no measured prediction effect')
                if result.get('glb') is None:
                    raise RuntimeError('No candidate mesh returned')
                asset = f'{index:03d}.glb'
                result['glb'].export(str(output/asset))
                pose = {key: result[key].detach().cpu().tolist()
                        for key in ('rotation', 'translation', 'scale')}
                review = obj.get('reconstruction_review', {})
                baseline = review.get('original_artifact')
                baseline_asset = baseline['asset'] if baseline else obj['asset']
                baseline_pose = read(source/baseline['pose']) if baseline else obj['pose']
                records.append(dict(object_id=obj['id'], mask_sha256=obj['mask_sha256'],
                    asset=asset, sha256=sha(output/asset), pose=pose,
                    baseline_asset=baseline_asset, baseline_sha256=sha(source/baseline_asset),
                    baseline_pose=baseline_pose, guidance_evidence=dict(guidance_stats),rgb_conditioning_evidence=rgb_evidence,
                    mask_expansion_evidence=expansion_evidence))
                write(output/'comparison.json', report)
                print(f'Generated {index+1}/{len(objects)}', flush=True)
                del result
                torch.cuda.empty_cache()
        report['completed'] = True
    finally:
        report['guidance_restored'] = model._pipeline.ss_cfg_strength_pm == baseline_strength
        report['source_scene_unchanged'] = sha(source/'scene.glb') == report['source_scene_sha256']
        write(output/'comparison.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--strength', type=float, default=1.)
    parser.add_argument('--conditioning',choices=['depth_guidance','masked_rgb','seed_alternative','mask_expansion'],default='depth_guidance')
    parser.add_argument('--mask-sha256',action='append')
    args = parser.parse_args()
    main(args.source, args.output, args.strength,args.conditioning,args.mask_sha256)
