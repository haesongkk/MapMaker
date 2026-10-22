import io
import json
from pathlib import Path

import pytest
from PIL import Image

from mapmaker.scene_pipeline import Pipeline, create_run
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_transfer import ArtifactStore, pack_run, unpack_run


class MemoryClient:
    def __init__(self, fail=False):
        self.data = {}
        self.fail = fail

    def upload_file(self, path, bucket, key):
        if self.fail:
            raise RuntimeError('upload interrupted')
        self.data[key] = Path(path).read_bytes()

    def head_object(self, *, Bucket, Key):
        return dict(ContentLength=len(self.data[Key]))

    def put_object(self, *, Bucket, Key, Body, **kwargs):
        self.data[Key] = Body

    def get_object(self, *, Bucket, Key):
        return dict(Body=io.BytesIO(self.data[Key]))


def test_inference_is_recoverable_when_geometry_fails(tmp_path, monkeypatch):
    from mapmaker import scene_placement
    from mapmaker.scene_reconstruct import finish_scene
    image = io.BytesIO()
    Image.new('RGB', (8, 8)).save(image, format='PNG')
    run = create_run(image.getvalue(), tmp_path / ('a' * 32))
    store = ArtifactStore.__new__(ArtifactStore)
    store.client = MemoryClient()
    store.bucket = 'test'

    def reconstruct(run):
        (run / 'objects/0.glb').write_bytes(b'frozen inference')
        meta = read(run / 'scene_metadata.json')
        meta['objects'] = [dict(status='generated', asset='objects/0.glb',
                                asset_sha256=sha(run / 'objects/0.glb'))]
        meta['deployment'] = dict(application_sha256='c' * 64)
        write(run / 'scene_metadata.json', meta)

    def fail_geometry(*args, **kwargs):
        assert store.key(run.name, 'inference-checkpoint.json') in store.client.data
        raise RuntimeError('geometry failed after inference')

    reconstruct(run)
    monkeypatch.setattr(scene_placement, 'finalize_scene', fail_geometry)
    with pytest.raises(RuntimeError, match='geometry failed'):
        finish_scene(run, inference_checkpoint=True, store=store)
    marker = json.loads(store.client.data[store.key(run.name, 'inference-checkpoint.json')])
    assert marker['scene_complete'] is False and marker['generated_objects'] == 1
    archive = tmp_path / 'recovered.zip'
    archive.write_bytes(store.client.data[store.key(run.name, 'inference.zip')])
    recovered = tmp_path / 'recovered'
    recovered.mkdir()
    unpack_run(archive, recovered)
    assert (recovered / 'objects/0.glb').read_bytes() == b'frozen inference'
    assert not (recovered / 'scene.glb').exists()
    assert not any(k.endswith(('completion.json', 'result.zip')) for k in store.client.data)
    from scripts.collect_inference_checkpoint import collect
    verified = tmp_path / 'verified'
    report = collect(run.name, verified, expected_input=marker['input_sha256'],
                     expected_release='c' * 64, store=store)
    assert report['scene_complete'] is False and report['verified_assets'] == 2
    assert (verified / 'objects/0.glb').read_bytes() == b'frozen inference'
    key = store.key(run.name, 'inference.zip')
    data = store.client.data[key]
    store.client.data[key] = bytes([data[0] ^ 1]) + data[1:]
    with pytest.raises(ValueError, match='checksum/size'):
        collect(run.name, tmp_path / 'corrupted', expected_input=marker['input_sha256'],
                expected_release='c' * 64, store=store)
    assert not (tmp_path / 'corrupted').exists()


def test_interrupted_checkpoint_upload_does_not_commit(tmp_path, monkeypatch):
    monkeypatch.setattr('time.sleep', lambda _: None)
    store = ArtifactStore.__new__(ArtifactStore)
    store.client = MemoryClient(fail=True)
    store.bucket = 'test'
    archive = tmp_path / 'archive.zip'
    archive.write_bytes(b'archive')
    with pytest.raises(RuntimeError, match='upload interrupted'):
        store.upload_inference_checkpoint('a' * 32, archive, dict(input_sha256='b' * 64, objects=[]))
    assert store.key('a'*32, 'inference-checkpoint.json') not in store.client.data
    diagnostic=json.loads(store.client.data[store.key('a'*32,'inference.zip.upload-error.json')])
    assert diagnostic['attempt']==3 and diagnostic['archive_bytes']==7
    assert 'upload interrupted' in diagnostic['error']


def test_archive_retry_recovers_without_regenerating_inference(tmp_path,monkeypatch):
    monkeypatch.setattr('time.sleep',lambda _:None)
    store=ArtifactStore.__new__(ArtifactStore);store.bucket='test'
    class TransientClient(MemoryClient):
        attempts=0
        def upload_file(self,*args):
            self.attempts+=1
            if self.attempts==1:raise RuntimeError('temporary upload failure')
            super().upload_file(*args)
    store.client=TransientClient();archive=tmp_path/'archive.zip';archive.write_bytes(b'original inference')
    store.upload_inference_checkpoint('a'*32,archive,dict(input_sha256='b'*64,objects=[]))
    assert store.client.attempts==2
    assert store.client.data[store.key('a'*32,'inference.zip')]==b'original inference'
    marker=json.loads(store.client.data[store.key('a'*32,'inference-checkpoint.json')])
    assert marker['archive_sha256']==sha(archive)


def test_checkpoint_request_reaches_reconstruction_process(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from mapmaker import scene_reconstruct
    run = tmp_path / ('a' * 32)
    (run / 'logs').mkdir(parents=True)
    write(run / 'logs/reconstruction_result.json', dict(ok=True))
    pipeline = Pipeline(inference_checkpoint=True)
    stream = io.StringIO()
    pipeline.worker = SimpleNamespace(stdin=stream, poll=lambda: None)
    pipeline.reconstruct(run)
    pipeline.worker = None
    request = json.loads(stream.getvalue())
    assert request['inference_checkpoint'] is True
    calls = []
    monkeypatch.setattr(scene_reconstruct.sys, 'stdin', io.StringIO(json.dumps(request) + '\n'))
    monkeypatch.setattr(scene_reconstruct, 'run_scene',
                        lambda path, **options: calls.append((path, options)))
    scene_reconstruct.serve()
    assert calls == [(run.resolve(), dict(inference_checkpoint=True))]
