"""Bounded development-only boundary audit, separate from production handler."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import traceback

from .runtime_paths import ROOT, VISION_PYTHON, SAM3_CHECKPOINT
from .scene_run import read, write, sha, status
from .scene_transfer import ArtifactStore, unpack_run, pack_run

PROTOCOL = 'mapmaker-boundary-audit-v1'
LOCK = threading.Lock()


def validate_payload(payload):
    if (payload.get('protocol') != PROTOCOL
            or not re.fullmatch(r'[a-f0-9]{32}', str(payload.get('run_id', '')))
            or not re.fullmatch(r'[a-f0-9]{64}', str(payload.get('input_sha256', '')))):
        raise ValueError('Invalid boundary audit payload')


def validate_cases(bundle):
    cases = read(bundle / 'scene_metadata.json').get('cases')
    if not isinstance(cases, list) or not 1 <= len(cases) <= 3:
        raise ValueError('Boundary audit requires one to three development cases')
    ids = [case.get('source_run_id') for case in cases]
    if (any(not isinstance(rid, str) or not re.fullmatch(r'[a-f0-9]{32}', rid) for rid in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError('Invalid/repeated source IDs')
    for case in cases:
        path = bundle / 'input' / case['source_run_id'] / 'scene_metadata.json'
        if sha(path) != case.get('metadata_sha256'):
            raise ValueError('Source metadata hash mismatch')
    return cases


def prepare_checkpoint(store):
    manifest = read(ROOT / 'configs/serverless/model-storage.json')
    entries = [item for item in manifest['files'] if item['path'] == 'sam3/sam3.pt']
    if len(entries) != 1:
        raise ValueError('Expected one frozen SAM3 checkpoint')
    item = entries[0]
    if SAM3_CHECKPOINT.is_file() and sha(SAM3_CHECKPOINT) == item['sha256']:
        return
    SAM3_CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    partial = SAM3_CHECKPOINT.with_suffix('.part')
    store.download_object(manifest['source_volume'], item['key'], partial, limit=item['bytes'])
    if partial.stat().st_size != item['bytes'] or sha(partial) != item['sha256']:
        raise ValueError('SAM3 checkpoint checksum mismatch')
    partial.replace(SAM3_CHECKPOINT)


def handler(job):
    payload = job['input']
    validate_payload(payload)
    scratch = Path(os.environ.get('MAPMAKER_SCRATCH', '/tmp/mapmaker-jobs'))
    scratch.mkdir(parents=True, exist_ok=True)
    with LOCK, tempfile.TemporaryDirectory(dir=scratch) as tmp:
        root = Path(tmp)
        store = ArtifactStore()
        archive = root / 'input.zip'
        store.download_input(payload['run_id'], archive)
        if sha(archive) != payload['input_sha256']:
            raise ValueError('Input bundle checksum mismatch')
        bundle = root / 'source'
        bundle.mkdir()
        unpack_run(archive, bundle)
        cases = validate_cases(bundle)
        result = root / payload['run_id']
        (result / 'logs').mkdir(parents=True)
        (result / 'masks').mkdir()
        completed = []
        success = False
        try:
            status(result, 'loading', 'Preparing frozen SAM3 checkpoint for boundary audit')
            prepare_checkpoint(store)
            env = os.environ.copy()
            env['PYTHONPATH'] = str(ROOT) + os.pathsep + env.get('PYTHONPATH', '')
            for case in cases:
                rid = case['source_run_id']
                source = bundle / 'input' / rid
                output = result / 'masks' / rid
                status(result, 'segmenting', f'Boundary audit source {len(completed)+1}/{len(cases)}')
                with (result / 'logs' / f'{rid}.log').open('w') as log:
                    subprocess.run([str(VISION_PYTHON), '-m', 'scripts.probe_instance_boundaries',
                                    str(source), '--output', str(output)], cwd=ROOT, env=env,
                                   stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900)
                if not read(output / 'boundary-audit.json').get('completed'):
                    raise ValueError('Incomplete boundary audit')
                completed.append(rid)
            success = True
        except Exception:
            (result / 'logs' / 'error.log').write_text(traceback.format_exc())
        write(result / 'scene_metadata.json', dict(run_id=payload['run_id'],
              artifact_kind='boundary_audit_only', success=success, completed_sources=completed,
              source_cases=cases, objects=[], quality_passed=False))
        status(result, 'done' if success else 'failed', 'Boundary audit artifacts ready')
        archive = root / 'result.zip'
        pack_run(result, archive)
        store.upload_result(payload['run_id'], archive)
        return dict(protocol=PROTOCOL, run_id=payload['run_id'], success=success,
                    quality_passed=False, archive_sha256=sha(archive), archive_bytes=archive.stat().st_size)


if __name__ == '__main__':
    import runpod
    runpod.serverless.start({'handler': handler})
