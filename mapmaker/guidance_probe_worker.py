"""Isolated diagnostic worker; deliberately not wired into the production handler."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import traceback

from .scene_run import ROOT, read, write, sha, status
from .scene_transfer import ArtifactStore, pack_run, unpack_run, safe_name
from .model_cache import prepare_models
from .gpu_measurement import GpuMeasurement

LOCK = threading.Lock()
PROTOCOL = 'mapmaker-pointmap-guidance-v1'


def execute_probe(source, output, result, options=None):
    options=options or {}
    mode=options.get('conditioning_mode','depth_guidance')
    command=['bash',str(ROOT/'scripts/run_guidance_probe.sh'),str(source),
             '--output',str(output),'--strength','1' if mode=='depth_guidance' else '0',
             '--conditioning',mode]
    for mask in options.get('target_masks',[]):command.extend(['--mask-sha256',mask])
    with (result/'logs/probe.log').open('w') as log:
        subprocess.run(command,
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)


def validate_source(source, payload):
    meta = read(source/'scene_metadata.json')
    if meta['input_image'] != 'input/source_image.png':
        raise ValueError('Unexpected source image path')
    paths = [meta['pointmap']['asset']]
    for obj in meta['objects']:
        paths.extend(obj[k] for k in ('mask', 'asset') if obj.get(k))
        for key in ('original_artifact', 'alternative_artifact'):
            artifact = obj.get('reconstruction_review', {}).get(key)
            if artifact:
                paths.extend([artifact['asset'], artifact['pose']])
    for path in paths:
        safe_name(path)
    if sha(source/meta['input_image']) != meta['input_sha256']:
        raise ValueError('Source image checksum mismatch')
    if sha(source/'scene.glb') != payload['source_scene_sha256']:
        raise ValueError('Source scene checksum mismatch')
    if payload.get('conditioning_mode') == 'mask_expansion':
        from PIL import Image
        from .mask_expansion import load_probe_mask
        targets = payload.get('target_masks', [])
        available = {o['mask_sha256']: o for o in meta['objects'] if o.get('status') == 'generated'}
        if not targets or not set(targets) <= set(available):
            raise ValueError('Mask expansion requires known explicit targets')
        for digest in targets:
            obj = available[digest]
            if sha(source/obj['mask']) != digest:
                raise ValueError('Baseline mask checksum mismatch')
            with Image.open(source/obj['mask']) as image:
                load_probe_mask(source, digest, image.size[::-1])
    return meta


def handler(job):
    payload = job['input']
    if payload.get('conditioning_mode','depth_guidance') not in ('depth_guidance','masked_rgb','seed_alternative','mask_expansion'):
        raise ValueError('Invalid conditioning mode')
    targets=payload.get('target_masks',[])
    if (not isinstance(targets,list) or len(targets)>3
            or any(not isinstance(m,str) or not re.fullmatch(r'[a-f0-9]{64}',m) for m in targets)
            or len(set(targets))!=len(targets)):
        raise ValueError('Invalid target mask subset')
    if (payload.get('protocol') != PROTOCOL or
        not re.fullmatch(r'[a-f0-9]{32}', payload.get('run_id', '')) or
        any(not re.fullmatch(r'[a-f0-9]{64}', payload.get(k, ''))
            for k in ('input_sha256', 'source_scene_sha256'))):
        raise ValueError('Invalid guidance diagnostic job')
    scratch = Path(os.environ.get('MAPMAKER_SCRATCH', '/tmp/mapmaker-jobs'))
    scratch.mkdir(parents=True, exist_ok=True)
    with LOCK, tempfile.TemporaryDirectory(dir=scratch) as tmp:
        root = Path(tmp); store = ArtifactStore()
        archive = root/'input.zip'
        store.download_input(payload['run_id'], archive)
        if sha(archive) != payload['input_sha256']:
            raise ValueError('Input bundle checksum mismatch')
        source = root/'source'; source.mkdir()
        unpack_run(archive, source)
        original = validate_source(source, payload)
        result = root/payload['run_id']
        for name in ('input', 'objects/guidance', 'logs'):
            (result/name).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source/original['input_image'], result/'input/source_image.png')
        write(result/'scene_metadata.json', dict(run_id=payload['run_id'],
            input_image='input/source_image.png', input_sha256=original['input_sha256'],
            source_run_id=original['run_id'], source_scene_sha256=payload['source_scene_sha256'],
            artifact_kind='guidance_comparison', scene_asset=None, objects=[], quality_passed=False))
        probe = root/'probe'
        success = False
        try:
            prepare_models(store, result)
            status(result, 'reconstructing', 'Running isolated depth-conditioning comparison')
            with GpuMeasurement(result):
                if 'conditioning_mode' in payload or targets:
                    execute_probe(source,probe,result,payload)
                else:
                    execute_probe(source, probe, result)
            comparison = read(probe/'comparison.json')
            if not all(comparison.get(k) for k in ('completed', 'guidance_restored', 'source_scene_unchanged')):
                raise ValueError('Incomplete guidance diagnostic')
            success = True
        except Exception:
            (result/'logs/error.log').write_text(traceback.format_exc())
        if (probe/'comparison.json').is_file():
            comparison = read(probe/'comparison.json')
            for obj in comparison['objects']:
                name = obj['asset']
                if not re.fullmatch(r'[0-9]{3,}\.glb', name) or sha(probe/name) != obj['sha256']:
                    raise ValueError('Invalid candidate artifact')
                shutil.copyfile(probe/name, result/'objects/guidance'/name)
                obj['asset'] = 'objects/guidance/'+name
            comparison.update(source_run_id=original['run_id'], quality_passed=False)
            write(result/'logs/guidance_comparison.json', comparison)
        status(result, 'done' if success else 'failed',
               'Comparison artifacts ready; scene quality unverified' if success else 'Guidance diagnostic failed')
        archive = root/'result.zip'; pack_run(result, archive)
        store.upload_result(payload['run_id'], archive)
        return dict(protocol=PROTOCOL, run_id=payload['run_id'], success=success,
                    quality_passed=False, artifact_kind='guidance_comparison',
                    archive_sha256=sha(archive), archive_bytes=archive.stat().st_size)


def main():
    import runpod
    runpod.serverless.start({'handler': handler})


if __name__ == '__main__':
    main()
