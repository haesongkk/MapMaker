"""Authorized 20-job comparison; resume known jobs and restore production v4.

One job at a time, no automatic POST retry. A STOP file cancels only the current
comparison job. This process does not certify visual quality or publish a report.
"""
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapmaker.scene_run import read,write,sha,now
from mapmaker.scene_remote import RunPodClient
from mapmaker.scene_transfer import ArtifactStore,unpack_run
from scripts import run_approved_v7_comparison as infra
from scripts.native_release_transition import replace_environment,restore_environment

ROOT=Path('.runtime/four-way-comparison')
TERMINAL={'COMPLETED','FAILED','CANCELLED','TIMED_OUT'}


def collect(job,release,store):
    result=job['result'];out=result.get('output',{})
    if not out.get('archive_sha256'):raise RuntimeError('Terminal result has no archive')
    assert out['run_id']==job['run_id']
    archive=ROOT/'downloads'/(job['run_id']+'.zip');archive.parent.mkdir(exist_ok=True)
    if not archive.exists() or sha(archive)!=out['archive_sha256']:
        store.download(job['run_id'],archive)
    assert sha(archive)==out['archive_sha256']
    stage='1' if job['profile']=='initial' else '2'
    folder=ROOT/'results'/job['sample']/stage
    if not folder.exists():folder.mkdir(parents=True);unpack_run(archive,folder)
    meta=read(folder/'scene_metadata.json')
    expected=read(ROOT/'inputs'/job['run_id']/'scene_metadata.json')
    assert meta['deployment']['application_sha256']==release['sha256']
    assert sha(folder/meta['input_image'])==meta['input_sha256']==expected['input_sha256']
    if not out.get('success'):raise RuntimeError('GPU pipeline reported failure; diagnostics retained')
    assert not meta.get('placement') and not meta.get('structure')
    assert meta['comparison_profile']==job['profile']
    assert sha(folder/'scene.glb')==out['scene_sha256']
    for obj in meta['objects']:
        for key in ('mask','asset'):
            if obj.get(key):assert sha(folder/obj[key])==obj[key+'_sha256']
    if job['profile']=='initial':assert not meta['object_extraction']['regions']
    write(folder/'comparison-collected.json',dict(complete=True,release=release['sha256'],
        raw_pose_verified=True,generated=sum(o['status']=='generated' for o in meta['objects']),
        failed_objects=len(meta.get('errors',[])),archive_sha256=out['archive_sha256']))
    return str(folder)


def main():
    original=read(ROOT/'endpoint-before.json');assert original['id']==infra.ENDPOINT
    assert original['env']['MAPMAKER_RELEASE_SHA256']=='47fb1a517a24e0d1b32e13fa1ad1f5cf3502696dcf947c591006cb77f4069fbb'
    client=RunPodClient(original['id']);session=client.session;store=ArtifactStore()
    session.headers['Authorization']='Bearer '+Path('.runtime/runpod-api.key').read_text(encoding='utf-8-sig').strip()
    jobs=read(ROOT/'jobs.json');assert len(jobs)==20
    assert len(read(ROOT/'upload-verification.json'))==22
    current=infra.control(session);candidate_env=current['env'];active=None;failure=None
    allowed={read(ROOT/'profiles'/m/'manifest.json')['sha256'] for m in ('initial','expanded')}
    assert candidate_env['MAPMAKER_RELEASE_SHA256'] in allowed|{original['env']['MAPMAKER_RELEASE_SHA256']}
    def save():write(ROOT/'jobs.json',jobs)
    def event(name,**details):
        write(ROOT/'progress.json',dict(time=now(),event=name,**details))
        print(name,details,flush=True)
    try:
        for job in jobs:
            release=read(ROOT/'profiles'/job['profile']/'manifest.json')
            if job.get('collected'):continue
            if not job.get('job_id'):
                if job.get('submission_intent'):raise RuntimeError('Ambiguous prior POST; do not resubmit')
                if (ROOT/'STOP').exists():raise RuntimeError('User stop requested')
                target=dict(original['env'],MAPMAKER_RELEASE_SHA256=release['sha256'],MAPMAKER_RELEASE_KEY=release['key'])
                if candidate_env!=target:
                    event('switching_profile',profile=job['profile'])
                    replace_environment(session,client,original,candidate_env,target)
                    candidate_env=target
                assert infra.control(session)['env']==target
                assert infra.quiet(client)
                job['submission_intent']=now();save()
                result=client.request('POST','run',dict(input=job['input'],policy=dict(executionTimeout=7200000,ttl=86400000)))
                job.update(submitted=True,endpoint_id=original['id'],job_id=result['id']);save()
            active=job
            event('submitted_or_resumed',sample=job['sample'],profile=job['profile'],job_id=job['job_id'])
            last=None;cancelled=False
            while True:
                if (ROOT/'STOP').exists() and not cancelled:
                    client.request('POST','cancel/'+job['job_id']);cancelled=True
                result=client.request('GET','status/'+job['job_id'])
                job['result']=result;save()
                if result['status']!=last:
                    last=result['status'];event('job_status',sample=job['sample'],profile=job['profile'],status=last)
                if result['status'] in TERMINAL:break
                progress=store.progress(job['run_id'])
                if progress:write(ROOT/'worker-progress.json',dict(sample=job['sample'],profile=job['profile'],**progress))
                time.sleep(20)
            active=None
            if result['status']!='COMPLETED':raise RuntimeError('Comparison job ended '+result['status'])
            job['collected']=collect(job,release,store);save()
            event('collected',sample=job['sample'],profile=job['profile'],path=job['collected'])
    except BaseException as exc:
        failure=type(exc).__name__+': '+str(exc)
        event('stopped',reason=failure)
        raise
    finally:
        if active is not None:
            result=client.request('GET','status/'+active['job_id'])
            if result['status'] not in TERMINAL:
                client.request('POST','cancel/'+active['job_id'])
                deadline=time.monotonic()+180
                while result['status'] not in TERMINAL:
                    if time.monotonic()>deadline:raise RuntimeError('Cancellation not confirmed; restore requires follow-up')
                    time.sleep(5);result=client.request('GET','status/'+active['job_id'])
            active['result']=result;save()
        restored=restore_environment(session,client,original,candidate_env)
        write(ROOT/'rollback-result.json',dict(**restored,failure=failure,complete=not failure))
        event('production_restored',**restored)


if __name__=='__main__':main()
