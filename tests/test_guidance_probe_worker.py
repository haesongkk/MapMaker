import contextlib
import shutil
import pytest
from mapmaker import guidance_probe_worker as worker
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_transfer import pack_run, unpack_run


def source_run(root):
    (root/'input').mkdir(parents=True)
    (root/'input/source_image.png').write_bytes(b'preserved source image')
    (root/'input/pointmap.npz').write_bytes(b'preserved pointmap')
    (root/'scene.glb').write_bytes(b'preserved baseline geometry')
    write(root/'scene_metadata.json', dict(run_id='a'*32, input_image='input/source_image.png',
        input_sha256=sha(root/'input/source_image.png'), objects=[],
        pointmap=dict(asset='input/pointmap.npz')))
    return root


@pytest.mark.parametrize('fail', [False, True])
def test_diagnostic_transfer_preserves_source_and_never_claims_scene_success(tmp_path, monkeypatch, fail):
    source=source_run(tmp_path/'source');archive=tmp_path/'input.zip'
    pack_run(source,archive);result_zip=tmp_path/'result.zip'
    class Store:
        def download_input(self, rid, target):shutil.copyfile(archive,target)
        def upload_result(self, rid, target):shutil.copyfile(target,result_zip)
    monkeypatch.setattr(worker,'ArtifactStore',Store)
    monkeypatch.setattr(worker,'prepare_models',lambda *args:None)
    monkeypatch.setattr(worker,'GpuMeasurement',lambda *args:contextlib.nullcontext())
    monkeypatch.setenv('MAPMAKER_SCRATCH',str(tmp_path/'scratch'))
    def execute(staged, output, result):
        assert (staged/'input/pointmap.npz').read_bytes()==b'preserved pointmap'
        output.mkdir();(output/'000.glb').write_bytes(b'candidate geometry')
        write(output/'comparison.json',dict(objects=[dict(asset='000.glb',sha256=sha(output/'000.glb'))],
            completed=not fail,guidance_restored=True,source_scene_unchanged=True))
        if fail:raise RuntimeError('simulated GPU failure after one candidate')
    monkeypatch.setattr(worker,'execute_probe',execute)
    result=worker.handler(dict(input=dict(protocol=worker.PROTOCOL,run_id='b'*32,
        input_sha256=sha(archive),source_scene_sha256=sha(source/'scene.glb'))))
    assert result['success'] is not fail and result['quality_passed'] is False
    assert 'scene_sha256' not in result and sha(result_zip)==result['archive_sha256']
    output=tmp_path/'received';output.mkdir();unpack_run(result_zip,output)
    meta=read(output/'scene_metadata.json')
    assert meta['scene_asset'] is None and meta['objects']==[] and not meta['quality_passed']
    assert not (output/'scene.glb').exists()
    assert (output/'objects/guidance/000.glb').read_bytes()==b'candidate geometry'
    assert read(output/'status.json')['stage']==('failed' if fail else 'done')
    assert (source/'scene.glb').read_bytes()==b'preserved baseline geometry'


def test_normal_generation_protocol_is_not_accepted():
    with pytest.raises(ValueError,match='Invalid guidance'):
        worker.handler(dict(input=dict(protocol=1,run_id='a'*32)))


@pytest.mark.parametrize('targets',[[{}],['a'*64]*2,['a'*64,'b'*64,'c'*64,'d'*64]])
def test_invalid_subset_rejected_before_storage_access(targets):
    with pytest.raises(ValueError,match='Invalid target'):
        worker.handler(dict(input=dict(target_masks=targets)))


def test_source_metadata_cannot_reference_outside_archive(tmp_path):
    source=source_run(tmp_path/'source');meta=read(source/'scene_metadata.json')
    meta['pointmap']['asset']='../outside.npz';write(source/'scene_metadata.json',meta)
    with pytest.raises(ValueError,match='Unsafe artifact path'):
        worker.validate_source(source,dict(source_scene_sha256=sha(source/'scene.glb')))


def test_expansion_requires_targets_before_model_download(tmp_path):
    source = source_run(tmp_path/'source')
    with pytest.raises(ValueError, match='explicit targets'):
        worker.validate_source(source, dict(source_scene_sha256=sha(source/'scene.glb'),
            conditioning_mode='mask_expansion', target_masks=[]))


@pytest.mark.parametrize('mode', ['seed_alternative', 'mask_expansion'])
def test_seed_diagnostic_command_preserves_guidance_and_target_mask(tmp_path,monkeypatch,mode):
    (tmp_path/'logs').mkdir();calls=[]
    monkeypatch.setattr(worker.subprocess,'run',lambda command,**kw:calls.append(command))
    worker.execute_probe(tmp_path/'source',tmp_path/'output',tmp_path,
        dict(conditioning_mode=mode,target_masks=['a'*64]))
    command=calls[0]
    assert command[command.index('--strength')+1]=='0'
    assert command[command.index('--conditioning')+1]==mode
    assert command[command.index('--mask-sha256')+1]=='a'*64
