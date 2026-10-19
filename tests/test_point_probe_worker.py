import contextlib
import io
import zipfile
from pathlib import Path
from PIL import Image
import pytest
from mapmaker.scene_pipeline import create_run
from mapmaker.scene_transfer import pack_run
from mapmaker.scene_run import sha, write, read
from mapmaker import point_probe_worker as worker


def test_diagnostic_rejects_web_publication_and_unknown_mode():
    payload=dict(protocol=1,task='point_proposal_ablation',run_id='a'*32,
                 input_sha256='b'*64,comparison_mode='point_component_only')
    worker.validate_payload(payload)
    for updates in ({'publish_web':True},{'comparison_mode':'shell'},
                    {'run_id':'../escape'},{'input_sha256':'invalid'},{'task':'scene'},
                    {'proposal_strategy':'shell'}):
        with pytest.raises(ValueError):worker.validate_payload(dict(payload,**updates))


@pytest.mark.parametrize('failed', [False,True])
@pytest.mark.parametrize('feature', [False,True])
def test_diagnostic_archive_cannot_be_reported_as_completed_scene(tmp_path,monkeypatch,failed,feature):
    image=io.BytesIO();Image.new('RGB',(32,32),'white').save(image,format='PNG')
    source=create_run(image.getvalue(),tmp_path/('a'*32));bundle=tmp_path/'input.zip'
    pack_run(source,bundle,input_only=True)
    uploaded=[]
    class Store:
        def download_input(self,rid,dest):Path(dest).write_bytes(bundle.read_bytes())
        def upload_result(self,rid,path):uploaded.append(Path(path).read_bytes())
        def put_progress(self,*args):pass
    def run(command,**kwargs):
        assert ('--feature-points' in command) is feature
        if failed:raise RuntimeError('simulated GPU failure')
        output=Path(command[command.index('--output')+1]);output.mkdir()
        write(output/'report.json',dict(complete=True,scene_complete=False))
    monkeypatch.setenv('MAPMAKER_SCRATCH',str(tmp_path/'scratch'))
    monkeypatch.setattr(worker,'ArtifactStore',Store)
    monkeypatch.setattr(worker,'prepare_models',lambda *args:None)
    monkeypatch.setattr(worker,'GpuMeasurement',lambda *args:contextlib.nullcontext())
    monkeypatch.setattr(worker.subprocess,'run',run)
    result=worker.handler({'input':dict(protocol=1,task='point_proposal_ablation',
        run_id=source.name,input_sha256=sha(bundle),comparison_mode='point_component_only',
        proposal_strategy='uncovered_image_features' if feature else 'multiscale_points')})
    assert result['success'] is not failed
    assert result['scene_complete'] is False and result['scene_sha256'] is None
    assert result['artifact_kind']=='mask_proposals'
    with zipfile.ZipFile(io.BytesIO(uploaded[0])) as z:
        assert 'scene.glb' not in z.namelist()
        import json
        state=json.loads(z.read('status.json'))
        assert state['stage']==('failed' if failed else 'diagnostic_done')
        if failed:assert 'logs/worker.log' in z.namelist()
        else:assert 'previews/proposal-probe/report.json' in z.namelist()
