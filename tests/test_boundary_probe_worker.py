import shutil
import subprocess

import pytest

from mapmaker import boundary_probe_worker as worker
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_transfer import pack_run, unpack_run


@pytest.mark.parametrize('fail', [False, True])
def test_nested_audit_transfer_and_failure_preserve_evidence(tmp_path, monkeypatch, fail):
    bundle = tmp_path / 'bundle'
    source = bundle / 'input' / ('a' * 32)
    source.mkdir(parents=True)
    write(source / 'scene_metadata.json', dict(objects=[]))
    write(bundle / 'scene_metadata.json', dict(cases=[dict(source_run_id='a' * 32,
          metadata_sha256=sha(source / 'scene_metadata.json'))]))
    archive = tmp_path / 'input.zip'
    pack_run(bundle, archive)
    result_zip = tmp_path / 'result.zip'

    class Store:
        def download_input(self, rid, target):
            shutil.copyfile(archive, target)

        def upload_result(self, rid, target):
            shutil.copyfile(target, result_zip)

    def execute(command, **kwargs):
        output = worker.Path(command[-1])
        output.mkdir()
        (output / '0.png').write_bytes(b'diagnostic mask')
        write(output / 'boundary-audit.json', dict(completed=not fail))
        if fail:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(worker, 'ArtifactStore', Store)
    monkeypatch.setattr(worker, 'prepare_checkpoint', lambda store: None)
    monkeypatch.setattr(worker.subprocess, 'run', execute)
    monkeypatch.setenv('MAPMAKER_SCRATCH', str(tmp_path / 'scratch'))
    result = worker.handler(dict(input=dict(protocol=worker.PROTOCOL, run_id='b' * 32,
                            input_sha256=sha(archive))))
    assert result['success'] is not fail
    assert result['quality_passed'] is False
    assert result['archive_sha256'] == sha(result_zip)
    received = tmp_path / 'received'
    received.mkdir()
    unpack_run(result_zip, received)
    assert (received / 'masks' / ('a' * 32) / '0.png').read_bytes() == b'diagnostic mask'
    assert not (received / 'scene.glb').exists()
    assert read(received / 'scene_metadata.json')['completed_sources'] == ([] if fail else ['a' * 32])
    assert (received / 'logs/error.log').exists() is fail


def test_wrong_protocol_rejected_before_storage():
    with pytest.raises(ValueError, match='Invalid boundary'):
        worker.handler(dict(input=dict(protocol=1, run_id='a' * 32, input_sha256='b' * 64)))


def test_case_path_escape_rejected(tmp_path):
    write(tmp_path / 'scene_metadata.json', dict(cases=[dict(source_run_id='../escape')]))
    with pytest.raises(ValueError, match='Invalid/repeated'):
        worker.validate_cases(tmp_path)
