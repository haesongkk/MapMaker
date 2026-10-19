import numpy as np
from PIL import Image

from mapmaker.scene_run import read, sha
from mapmaker.scene_transfer import pack_run, unpack_run
from mapmaker.scene_vision import save_mask_candidates
from mapmaker.scene_vision import finish_segmentation
from mapmaker.mask_selection import MAX_RECONSTRUCTION_OBJECTS
import time


def test_all_candidate_masks_and_manifest_survive_worker_transfer(tmp_path):
    run = tmp_path / 'worker'
    raw = []
    count = MAX_RECONSTRUCTION_OBJECTS + 8
    for i in range(count):
        mask = np.zeros((20, 20), dtype=bool)
        mask.flat[i:i+10] = True
        raw.append((dict(geometry_key=f'{i:064x}', confidence=.9), mask))
    metadata = save_mask_candidates(run, raw, count)
    archive = tmp_path / 'result.zip'
    pack_run(run, archive)
    target = tmp_path / 'download'
    unpack_run(archive, target)
    records = read(target / metadata['asset'])
    assert len(records) == count > metadata['reconstruction_limit']
    for record, (_, expected) in zip(records, raw):
        assert sha(target / record['mask']) == record['mask_sha256']
        assert np.array_equal(np.asarray(Image.open(target / record['mask'])) > 0, expected)


def test_segmentation_finishes_metadata_preview_logs_and_transfer(tmp_path):
    run = tmp_path / 'worker'
    for folder in ('masks', 'logs', 'previews'):
        (run / folder).mkdir(parents=True)
    image = Image.new('RGB', (200, 200), 'white')
    raw = []
    for i in range(20):
        mask = np.zeros((200, 200), dtype=bool)
        y, x = divmod(i, 5)
        mask[y*40:y*40+25, x*40:x*40+25] = True
        raw.append((dict(name=f'item_{i}', confidence=.95), mask))
    meta = dict(objects=[], timing={}, pipeline={})
    finish_segmentation(run, image, raw, [r for r, _ in raw], meta, time.monotonic(), 'fixture')
    assert read(run / 'status.json')['stage'] == 'segmented'
    assert len(read(run / 'scene_metadata.json')['objects']) == 20
    assert read(run / 'logs/segmentation.json')['retained_candidate_masks'] == 20
    assert (run / 'previews/masks.png').exists()
    pack_run(run, tmp_path / 'full-result.zip')
    unpack_run(tmp_path / 'full-result.zip', tmp_path / 'download')
    assert read(tmp_path / 'download/scene_metadata.json') == meta


def test_corroborated_small_observations_survive_transfer_with_honest_scores(tmp_path):
    run = tmp_path / 'worker'
    for folder in ('masks', 'logs', 'previews'):
        (run / folder).mkdir(parents=True)
    image = Image.new('RGB', (400, 400), 'white')
    weak = np.zeros((400, 400), bool)
    weak[100:115, 100:115] = True
    large = np.zeros_like(weak)
    large[200:300, 200:300] = True
    raw = [(dict(name='unknown', confidence=.7, source_crop=[0, 0, 200, 200]), weak),
           (dict(name='', confidence=.75, source_crop=[50, 50, 250, 250]), weak.copy()),
           (dict(name='large', confidence=.95), large)]
    meta = dict(objects=[], timing={}, pipeline={})
    finish_segmentation(run, image, raw, [r for r, _ in raw], meta, time.monotonic(), 'fixture')
    assert len(meta['objects']) == 2
    recovered = next(o for o in meta['objects'] if o['confidence'] < .8)
    assert recovered['confidence'] == .75
    assert recovered['selection_evidence']['distinct_views'] == 2
    logs = read(run / 'logs/segmentation.json')
    assert len(logs['cross_view_evidence']) == 2
    assert logs['cross_view_selection_enabled'] is True
    pack_run(run, tmp_path / 'result.zip')
    unpack_run(tmp_path / 'result.zip', tmp_path / 'download')
    records = read(tmp_path / 'download/masks/candidates.json')
    assert len(records) == 3
    assert [r['confidence'] for r in records[:2]] == [.7, .75]
    for record in records[:2]:
        assert np.array_equal(np.asarray(Image.open(tmp_path / 'download' / record['mask'])) > 0, weak)
