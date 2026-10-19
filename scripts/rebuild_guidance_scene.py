"""Assemble a diagnostic candidate on CPU, then run normal scene constraints."""
import argparse
from pathlib import Path
import shutil
import tempfile
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_replay import rebuild_inference_scene
from mapmaker.scene_placement import finalize_scene
from scripts.evaluate_guidance_probe import compare


def build(source, probe, output, *, finalize=True, accepted_only=False):
    source, probe, output = [Path(p).resolve() for p in (source, probe, output)]
    if output.exists() or any(output.is_relative_to(p) for p in (source, probe)):
        raise ValueError('A new output outside the source artifacts is required')
    output.parent.mkdir(parents=True, exist_ok=True)
    comparison = compare(source, probe, progress=lambda report: write(
        output.parent/(output.name+'-comparison-progress.json'), report))
    report = read(probe/'logs/guidance_comparison.json')
    if accepted_only:
        from mapmaker.reconstruction_evidence import prefer_alternative
        allowed={r['object_id'] for r in comparison['records'] if prefer_alternative(r['baseline'],r['candidate'])}
        report['objects']=[item for item in report['objects'] if item['object_id'] in allowed]
        if not report['objects']:
            raise ValueError('No alternative passed source evidence; keep the baseline scene')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.guidance-stage-', dir=output.parent) as tmp:
        stage = Path(tmp)/'source'
        meta = rebuild_inference_scene(source, stage)
        by_id = {obj['id']:obj for obj in meta['objects']}
        if 'reconstruction_review' in meta:
            meta['baseline_reconstruction_review'] = meta.pop('reconstruction_review')
        for item in report['objects']:
            obj = by_id[item['object_id']]
            # Distinct paths avoid changing a shared baseline asset in the copy.
            path = item['asset']
            (stage/path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(probe/path, stage/path)
            if 'reconstruction_review' in obj:
                obj['baseline_reconstruction_review'] = obj.pop('reconstruction_review')
            if report['guidance_method'] == 'controlled_mask_expansion_v1':
                from PIL import Image
                import numpy as np
                from mapmaker.mask_expansion import load_probe_mask
                with Image.open(source/obj['mask']) as image:
                    expanded_mask, expanded = load_probe_mask(source, obj['mask_sha256'], image.size[::-1])
                if expanded != item['mask_expansion_evidence']:
                    raise ValueError('Candidate mask differs from the GPU conditioning mask')
                mask_path = 'masks/expanded_' + expanded['sha256'] + '.png'
                (stage/mask_path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source/expanded['asset'], stage/mask_path)
                obj['mask_expansion'] = dict(original_mask=obj['mask'],
                    original_sha256=obj['mask_sha256'], original_mask_area=obj.get('mask_area'),
                    original_bbox=obj.get('bbox'), evidence=expanded, quality_passed=False)
                y, x = np.where(expanded_mask)
                obj.update(mask=mask_path, mask_sha256=expanded['sha256'],
                           mask_area=int(expanded_mask.sum()),
                           bbox=[int(x.min()), int(y.min()), int(x.max())+1, int(y.max())+1])
            obj.update(asset=path, asset_sha256=item['sha256'], pose=item['pose'])
        meta['guidance_experiment'] = dict(source_run_id=comparison['source_run_id'],
            source_scene_sha256=comparison['source_scene_sha256'],
            comparison_sha256=sha(probe/'logs/guidance_comparison.json'),
            regenerated_object_ids=[item['object_id'] for item in report['objects']],
            additional_pointmap_guidance=report['candidate_additional_guidance'],
            conditioning_method=comparison['conditioning_method'],
            seed=report['seed'], quality_passed=False,
            accepted_only=accepted_only,
            scope='Regenerate previously selected objects; preserve other baseline assets for scene review')
        write(stage/'scene_metadata.json', meta)
        rebuild_inference_scene(stage, output)
        write(output/'logs/guidance_input_metadata.json', meta)
        provenance=read(output/'replay_provenance.json')
        provenance.update(source=str(output/'logs/guidance_input_metadata.json'),
            source_kind='derived_guidance_metadata', source_metadata_asset='logs/guidance_input_metadata.json')
        assert provenance['source_metadata_sha256']==sha(output/'logs/guidance_input_metadata.json')
        write(output/'replay_provenance.json',provenance)
    # Retain durable sources rather than relying on the temporary staging tree.
    write(output/'logs/guidance_scene_provenance.json', dict(source=str(source),probe=str(probe),
        source_scene_sha256=sha(source/'scene.glb'),
        comparison_sha256=sha(probe/'logs/guidance_comparison.json'),
        conditioning_method=comparison['conditioning_method'],
        regenerated_object_ids=meta['guidance_experiment']['regenerated_object_ids'],
        fresh_gpu_inference=False, quality_passed=False))
    write(output/'logs/guidance_source_comparison.json', comparison)
    if finalize:
        finalize_scene(output, render=False)
    return read(output/'scene_metadata.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('probe', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.probe, args.output)
