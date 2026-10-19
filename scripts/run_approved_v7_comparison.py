"""Authorized nine-job v4/v5/v7 comparison, with read-back and v4 restoration.

No automatic submission retries. Does not print or persist endpoint credentials.
Results stay on S3 until collected separately, so downloads never delay rollback.
"""
import copy
import hashlib
import json
import time
import uuid
from pathlib import Path
import requests
from mapmaker.remote_settings import load_settings
from mapmaker.scene_pipeline import create_run
from mapmaker.scene_remote import RunPodClient
from mapmaker.scene_run import read, write, sha, now
from mapmaker.scene_transfer import ArtifactStore, pack_run

ROOT = Path('.runtime/v7-gpu-comparison')
ENDPOINT = '8dzbkfrxys43hb'
BASE = 'https://api.runpod.io/v2/serverless/'+ENDPOINT
TERMINAL = {'COMPLETED','FAILED','CANCELLED','TIMED_OUT'}


def emit(event, **values):
    record = dict(time=now(),event=event,**values)
    with (ROOT/'events.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps(record)+'\n')
    print(json.dumps(record),flush=True)


def control(session, method='GET', suffix='', body=None):
    r = session.request(method,BASE+suffix,json=body,timeout=(15,60))
    if not r.ok: raise RuntimeError(f'Control {method} {suffix}: HTTP {r.status_code}')
    return r.json()


def quiet(client):
    h=client.request('GET','health')
    return not (h['jobs'].get('inProgress',0) or h['jobs'].get('inQueue',0))


def transition(session, client, original, release):
    if not quiet(client):raise RuntimeError('Endpoint has active/queued jobs; refusing worker cycle')
    before=control(session)
    for key in ('gpu','scaling','image','workers'):
        if before.get(key)!=original.get(key):raise RuntimeError(f'Concurrent endpoint setting change: {key}')
    if before['env'].get('MAPMAKER_RELEASE_SHA256')==release['sha256']:
        emit('release_already_active',release=release['sha256']);return
    env=copy.deepcopy(before['env'])
    env.update(MAPMAKER_RELEASE_KEY=release['key'],MAPMAKER_RELEASE_SHA256=release['sha256'])
    stopped=dict(original['workers'],max=0,min=0)
    control(session,'PATCH',body=dict(env=env,workers=stopped))
    after=control(session)
    assert after['env']==env and after['workers']==stopped
    deadline=time.monotonic()+600
    while True:
        workers=control(session,suffix='/workers')
        if not workers['workers']:break
        if time.monotonic()>deadline:raise TimeoutError('Old workers did not stop')
        time.sleep(10)
    control(session,'PATCH',body=dict(workers=original['workers']))
    after=control(session)
    assert after['env']==env and after['workers']==original['workers']
    for key in ('gpu','scaling','image'):assert after.get(key)==original.get(key)
    emit('release_verified',release=release['sha256'],old_workers_stopped=True)


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    if any(ROOT.iterdir()):raise RuntimeError('Experiment directory is not empty; do not resubmit')
    load_settings();client=RunPodClient(ENDPOINT);store=ArtifactStore();session=client.session
    session.headers['Authorization']='Bearer '+Path('.runtime/runpod-api.key').read_text(encoding='utf-8-sig').strip()
    original=control(session)
    assert original['env']['MAPMAKER_RELEASE_SHA256']==read('configs/cloud-deployment.json')['gpu_application_sha256']
    if not quiet(client):raise RuntimeError('Endpoint busy before experiment')
    workers=control(session,suffix='/workers')
    v4=dict(sha256=original['env']['MAPMAKER_RELEASE_SHA256'],key=original['env']['MAPMAKER_RELEASE_KEY'])
    v5=read('.runtime/v5-validation/release.json');v7=read('.runtime/v7-release/release.json')
    write(ROOT/'rollback.json',dict(endpoint=ENDPOINT,release=v4,workers=original['workers'],
        env_digest=hashlib.sha256(json.dumps(original['env'],sort_keys=True).encode()).hexdigest()))
    emit('preflight',release=v4['sha256'],worker_summary=workers['summary'],approved_jobs=9)
    assert sha('.runtime/v7-release/application.zip')==v7['sha256']
    for path,digest in v7['source_sha256'].items():assert sha(path)==digest, f'Package source changed: {path}'
    manifest=read('docs/QUALITY_EVALUATION_V2.json')
    write(ROOT/'evaluation-manifest.json',manifest)
    for r in manifest['held_out']:assert sha(r['file'])==r['sha256']
    # Only the new immutable application key is written. Existing baselines are read.
    store.client.upload_file('.runtime/v7-release/application.zip',store.bucket,v7['key'])
    for release in (v4,v5,v7):
        obj=store.client.get_object(Bucket=store.bucket,Key=release['key'])
        with obj['Body'] as body:assert hashlib.sha256(body.read()).hexdigest()==release['sha256']
    write(ROOT/'releases.json',{'v4':v4,'v5':v5,'v7':v7})
    jobs=[];failure=None
    try:
        for version,release in ((4,v4),(5,v5),(7,v7)):
            transition(session,client,original,release)
            batch=[]
            for sample in manifest['held_out']:
                assert len(jobs)<9
                rid=uuid.uuid4().hex
                run=create_run(Path(sample['file']).read_bytes(),ROOT/'inputs'/rid)
                archive=ROOT/(rid+'-input.zip');pack_run(run,archive,input_only=True);store.upload(rid,archive)
                payload=dict(protocol=1,run_id=rid,input_sha256=sha(archive),publish_web=True)
                # Record intent before POST; ambiguous submissions are never retried.
                intent=dict(version=version,sample=sample['id'],run_id=rid,release=release['sha256'],payload=payload)
                write(ROOT/(rid+'-submission-intent.json'),intent)
                response=client.request('POST','run',{'input':payload,'policy':{'executionTimeout':3600000,'ttl':14400000}})
                job=dict(intent,job_id=response['id'],status=response.get('status','IN_QUEUE'))
                jobs.append(job);batch.append(job);write(ROOT/'jobs.json',jobs)
                emit('submitted',version=version,sample=sample['id'],job_id=job['job_id'],run_id=rid)
            last={};deadline=time.monotonic()+4*3600
            while any(j['status'] not in TERMINAL for j in batch):
                for job in batch:
                    if job['status'] in TERMINAL:continue
                    result=client.poll(job['job_id']);job['status']=result['status']
                    write(ROOT/(job['run_id']+'-result.json'),result);write(ROOT/'jobs.json',jobs)
                    progress=store.get_json(job['run_id'],'progress.json')
                    signature=json.dumps(dict(status=result['status'],progress=progress),sort_keys=True)
                    if last.get(job['run_id'])!=signature:
                        last[job['run_id']]=signature
                        # Progress JSON is generated by our own pipeline; emit selected fields only.
                        emit('progress',version=version,sample=job['sample'],status=result['status'],
                             stage=(progress or {}).get('stage'),message=(progress or {}).get('message'))
                    if result['status'] in TERMINAL:
                        emit('terminal',version=version,sample=job['sample'],status=result['status'],
                             success=result.get('output',{}).get('success'),execution_ms=result.get('executionTime'))
                if time.monotonic()>deadline:raise TimeoutError('Batch deadline exceeded')
                if any(j['status'] not in TERMINAL for j in batch):time.sleep(20)
            if any(j['status']!='COMPLETED' or not read(ROOT/(j['run_id']+'-result.json')).get('output',{}).get('success') for j in batch):
                raise RuntimeError(f'v{version} batch had a failed job; no extra submissions')
    except BaseException as exc:
        failure=type(exc).__name__+': '+str(exc)
        emit('experiment_stopped',reason=failure)
        for job in jobs:
            if job['status'] not in TERMINAL:
                try:client.cancel(job['job_id']);emit('own_job_cancel_requested',job_id=job['job_id'])
                except Exception as cancel_error:emit('cancel_error',type=type(cancel_error).__name__)
    finally:
        # Do not terminate unrelated work while restoring; wait for the queue to clear.
        while not quiet(client):
            emit('waiting_for_quiet_before_restore');time.sleep(20)
        # Restore even if the last transition stopped at max=0.
        current=control(session)
        restored_env=copy.deepcopy(current['env'])
        for key in ('MAPMAKER_RELEASE_KEY','MAPMAKER_RELEASE_SHA256'):restored_env[key]=original['env'][key]
        control(session,'PATCH',body=dict(env=restored_env,workers=dict(original['workers'],min=0,max=0)))
        stopped=control(session);assert stopped['env']==restored_env and stopped['workers']['max']==0
        while control(session,suffix='/workers')['workers']:time.sleep(10)
        control(session,'PATCH',body=dict(workers=original['workers']))
        restored=control(session)
        report=dict(release=restored['env']['MAPMAKER_RELEASE_SHA256'],env_restored=restored['env']==original['env'],
                    workers_restored=restored['workers']==original['workers'],experiment_workers_stopped=True,
                    unchanged={k:restored.get(k)==original.get(k) for k in ('gpu','scaling','image')},
                    submitted_jobs=len(jobs),failure=failure,post_restore_inference=False)
        write(ROOT/'rollback-result.json',report);emit('restored',**report)
        assert report['env_restored'] and report['workers_restored'] and all(report['unchanged'].values())
    if failure:raise RuntimeError(failure)


if __name__=='__main__':main()
