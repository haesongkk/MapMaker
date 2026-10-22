"""Recover mode-1 scenes from hash-verified saved inference, without GPU reruns."""
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mapmaker.scene_run import read, write, sha, status, now
from mapmaker.scene_transfer import ArtifactStore, unpack_run
from mapmaker.baseline_assembly import read_header
from mapmaker.scene_export import finish_mode
from scripts.compare_baseline import POLICY

WORK = ROOT / '.runtime/minimal-baseline'


def recover(name, record, checkpoint, expected_input):
    store = ArtifactStore()
    rid = record['payload']['run_id']
    assert checkpoint['run_id'] == rid
    size = checkpoint['archive_bytes']
    assert 0 < size < 32 * 1024**3
    archive = WORK / f'{name}-verified-inference.zip'
    if not archive.exists() or archive.stat().st_size != size or sha(archive) != checkpoint['archive_sha256']:
        print(f'Downloading {name}: {size:,} bytes', flush=True)
        store.download_object(store.bucket, store.key(rid, 'inference.zip'), archive, limit=size)
    assert archive.stat().st_size == size and sha(archive) == checkpoint['archive_sha256']
    folder = WORK / 'recovered' / rid
    folder.mkdir(parents=True, exist_ok=True)
    unpack_run(archive, folder)
    meta = read(folder / 'scene_metadata.json')
    assert meta['run_id'] == rid
    assert meta['input_sha256'] == checkpoint['input_sha256'] == expected_input
    assert sha(folder / meta['input_image']) == expected_input
    assert meta['deployment'] == checkpoint['deployment']
    assert meta['execution']['mode'] == 1 and meta['execution']['baseline_policy'] == POLICY
    assert meta['execution'].get('tagger', 'ram++') != 'qwen2.5-vl-7b'
    assert 'ram' in meta['object_extraction']['model'].lower()
    header, _, _ = read_header(folder / 'scene.glb')
    nodes = {n.get('name'): n for n in header['nodes']}
    generated = 0
    for obj in meta['objects']:
        assert sha(folder / obj['mask']) == obj['mask_sha256']
        assert obj['status'] in ('generated', 'failed')
        if obj['status'] != 'generated':
            continue
        generated += 1
        assert sha(folder / obj['asset']) == obj['asset_sha256']
        read_header(folder / obj['asset'])
        node = nodes[obj['id']]
        np.testing.assert_allclose(np.array(node['matrix']).reshape(4, 4).T,
                                   obj['transform']['matrix'], atol=1e-6)
    assert generated == checkpoint['generated_objects']
    digest = sha(folder / 'scene.glb')
    finish_mode(folder)
    assert sha(folder / 'scene.glb') == digest
    meta = read(folder / 'scene_metadata.json')
    meta['recovery'] = dict(kind='verified_inference_checkpoint', finalized_at=now(),
        archive_sha256=checkpoint['archive_sha256'], scene_sha256=digest,
        note='Original scene, masks, object assets and official transforms verified and preserved; mode-1 finalization only.')
    write(folder / 'scene_metadata.json', meta)
    status(folder, 'done', 'Verified checkpoint recovered; original scene preserved',
           current=len(meta['objects']), total=len(meta['objects']))
    return dict(path=folder.relative_to(ROOT).as_posix(), status='complete',
                scene_sha256=digest, recovery=meta['recovery'])


if __name__ == '__main__':
    state = read(WORK / 'comparison.json')
    audit = read(WORK / 'storage-audit.json')
    qwen = read(ROOT / '.runtime/qwen-baseline-v2/comparison.json')['samples']
    write(WORK / 'comparison-before-recovery.json', state)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = {}
        for name, record in state['samples'].items():
            if record['status'] == 'complete':
                continue
            expected = read(ROOT / qwen[name]['path'] / 'scene_metadata.json')['input_sha256']
            checkpoint = audit[name]['inference-checkpoint.json']
            if not checkpoint:
                raise RuntimeError(f'{name}: no verified checkpoint; new inference required')
            pending[pool.submit(recover, name, record, checkpoint, expected)] = name
        for future in as_completed(pending):
            name = pending[future]
            state['samples'][name].update(future.result())
            write(WORK / 'comparison.json', state)
            print(f'Verified and finalized {name}', flush=True)
