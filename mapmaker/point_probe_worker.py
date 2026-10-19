"""Isolated proposal experiment worker; never publishes a completed 3D scene."""
import os
import re
import shutil
import subprocess
import tempfile
import threading
import traceback
from pathlib import Path
from .scene_run import ROOT, read, write, sha, status
from .scene_transfer import ArtifactStore, unpack_run, pack_run
from .runtime_paths import VISION_PYTHON
from .model_cache import prepare_models
from .serverless_worker import report_progress
from .gpu_measurement import GpuMeasurement

LOCK = threading.Lock()


def validate_payload(payload):
    if (payload.get('protocol') != 1 or payload.get('task') != 'point_proposal_ablation'
            or not re.fullmatch(r'[a-f0-9]{32}', str(payload.get('run_id','')))
            or not re.fullmatch(r'[a-f0-9]{64}', str(payload.get('input_sha256','')))
            or payload.get('publish_web')
            or payload.get('comparison_mode') not in ('point_component_only','saved_full_selection')
            or payload.get('proposal_strategy','multiscale_points') not in ('multiscale_points','uncovered_image_features')):
        raise ValueError('Invalid isolated proposal experiment')


def handler(job):
    payload=job['input'];validate_payload(payload)
    scratch=Path(os.environ.get('MAPMAKER_SCRATCH','/tmp/mapmaker-jobs'))
    scratch.mkdir(parents=True,exist_ok=True)
    with LOCK,tempfile.TemporaryDirectory(dir=scratch) as temp:
        root=Path(temp);store=ArtifactStore();archive=root/'input.zip'
        store.download_input(payload['run_id'],archive)
        if sha(archive)!=payload['input_sha256']:
            raise ValueError('Input archive hash mismatch')
        run=root/payload['run_id'];run.mkdir();unpack_run(archive,run)
        meta=read(run/'scene_metadata.json')
        if (meta['run_id']!=run.name or meta['input_image']!='input/source_image.png'
                or sha(run/meta['input_image'])!=meta['input_sha256']):
            raise ValueError('Input image identity mismatch')
        meta['deployment']={'application_sha256':os.environ.get('MAPMAKER_RELEASE_SHA256')}
        meta['experiment_kind']='mask_proposals';meta['scene_asset']=None
        write(run/'scene_metadata.json',meta)
        for directory in ('logs','previews'):(run/directory).mkdir(exist_ok=True)
        stop=threading.Event()
        reporter=threading.Thread(target=report_progress,args=(run,store,stop),daemon=True)
        reporter.start();success=False
        try:
            prepare_models(store,run)
            status(run,'segmenting','Comparing point proposals; no 3D generation')
            command=[str(VISION_PYTHON),'-m','scripts.probe_multiscale_points',str(run),
                     '--output',str(root/'probe')]
            if payload['comparison_mode']=='point_component_only':command.append('--fresh-points')
            if payload.get('proposal_strategy')=='uncovered_image_features':command.append('--feature-points')
            env=os.environ.copy();env['PYTHONPATH']=str(ROOT)+os.pathsep+env.get('PYTHONPATH','')
            env.setdefault('OMP_NUM_THREADS','8')
            with (run/'logs/proposal-probe.log').open('w') as log,GpuMeasurement(run):
                subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
            report=read(root/'probe/report.json')
            if not report['complete'] or report['scene_complete']:
                raise ValueError('Invalid proposal report')
            shutil.copytree(root/'probe',run/'previews/proposal-probe')
            status(run,'diagnostic_done','Proposal comparison complete; not a 3D scene')
            success=True
        except Exception:
            with (run/'logs/worker.log').open('a') as log:traceback.print_exc(file=log)
            status(run,'failed','Proposal comparison failed; inspect logs')
        finally:
            stop.set();reporter.join(timeout=46)
        result=root/'result.zip';pack_run(run,result);store.upload_result(run.name,result)
        return dict(protocol=1,run_id=run.name,success=success,artifact_kind='mask_proposals',
            scene_complete=False,scene_sha256=None,archive_sha256=sha(result),
            archive_bytes=result.stat().st_size)


if __name__=='__main__':
    import runpod
    runpod.serverless.start({'handler':handler})
