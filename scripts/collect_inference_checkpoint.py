"""Recover committed inference evidence; never report a completed scene."""
import argparse
from pathlib import Path
import re
import tempfile

from mapmaker.scene_run import read, write, sha
from mapmaker.scene_transfer import ArtifactStore, MAX_ARCHIVE_BYTES, safe_name, unpack_run


def collect(run_id, output, *, expected_input, expected_release, store=None):
    if not re.fullmatch(r'[a-f0-9]{32}', run_id):
        raise ValueError('Invalid run ID')
    for digest in (expected_input, expected_release):
        if not re.fullmatch(r'[a-f0-9]{64}', digest):
            raise ValueError('Expected input/release hashes are required')
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    store = store or ArtifactStore()
    marker = store.get_json(run_id, 'inference-checkpoint.json')
    if (not isinstance(marker, dict) or marker.get('protocol') != 1
            or marker.get('run_id') != run_id or marker.get('scene_complete') is not False
            or marker.get('artifact_kind') != 'inference_checkpoint'
            or marker.get('input_sha256') != expected_input
            or (marker.get('deployment') or {}).get('application_sha256') != expected_release
            or not isinstance(marker.get('archive_bytes'), int)
            or not 0 < marker['archive_bytes'] <= MAX_ARCHIVE_BYTES
            or not re.fullmatch(r'[a-f0-9]{64}', str(marker.get('archive_sha256', '')))):
        raise ValueError('Missing or mismatched inference checkpoint commit')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.checkpoint-', dir=output.parent) as tmp:
        root = Path(tmp)
        archive = root / 'inference.zip'
        store.download_object(store.bucket, store.key(run_id, 'inference.zip'), archive,
                              limit=marker['archive_bytes'])
        if archive.stat().st_size != marker['archive_bytes'] or sha(archive) != marker['archive_sha256']:
            raise ValueError('Inference archive checksum/size mismatch')
        stage = root / 'run'
        stage.mkdir()
        unpack_run(archive, stage)
        meta = read(stage / 'scene_metadata.json')
        if (meta.get('run_id') != run_id or meta.get('input_sha256') != expected_input
                or meta.get('deployment') != marker['deployment']):
            raise ValueError('Inference metadata identity mismatch')
        assets = [(meta['input_image'], expected_input)]
        if meta.get('pointmap'):
            assets.append((meta['pointmap']['asset'], meta['pointmap']['sha256']))
        generated = 0
        for obj in meta['objects']:
            if obj.get('mask'):
                assets.append((obj['mask'], obj['mask_sha256']))
            if obj.get('asset'):
                assets.append((obj['asset'], obj['asset_sha256']))
            for name in ('original_artifact', 'alternative_artifact'):
                candidate = obj.get('reconstruction_review', {}).get(name)
                if candidate:
                    assets.extend([(candidate['asset'], candidate['sha256']),
                                   (candidate['pose'], candidate['pose_sha256'])])
            generated += obj.get('status') == 'generated'
        if generated != marker['generated_objects']:
            raise ValueError('Inference object count mismatch')
        for name, digest in assets:
            safe_name(name)
            if sha(stage / name) != digest:
                raise ValueError('Inference source asset checksum mismatch')
        write(stage / 'logs/checkpoint-collection.json', dict(
            **marker, verified_assets=len(assets), quality_passed=False,
            purpose='Recover inference for CPU geometry replay; not a final scene'))
        stage.rename(output)
    return dict(run_id=run_id, output=str(output), verified_assets=len(assets),
                generated_objects=generated, scene_complete=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_id')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--expected-input', required=True)
    parser.add_argument('--expected-release', required=True)
    args = parser.parse_args()
    print(collect(args.run_id, args.output, expected_input=args.expected_input,
                  expected_release=args.expected_release))
