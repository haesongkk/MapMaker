"""Stage-limited v8 GPU comparison; dry-run by default, no implicit approval.

The separate authenticated browser job is reserved as submission 13. This
runner submits only the 3 development or 9 evaluation jobs, never both at once.
"""
import argparse
import copy
import hashlib
from pathlib import Path
import time
import uuid

try:
    from scripts import run_approved_v7_comparison as infra
except ModuleNotFoundError:  # Direct script invocation without repository on sys.path.
    import run_approved_v7_comparison as infra
from mapmaker.remote_settings import load_settings
from mapmaker.scene_pipeline import create_run
from mapmaker.scene_remote import RunPodClient
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_transfer import ArtifactStore, pack_run

ROOT = Path('.runtime/v8-gpu-comparison')


def poll_existing_job(client, job_id, attempts=3):
    """Retry only reads of the same known job; never infer termination or resubmit."""
    for attempt in range(attempts):
        try:
            return client.poll(job_id)
        except RuntimeError:
            infra.emit('status_observation_failed', job_id=job_id, attempt=attempt+1)
            if attempt+1 == attempts:
                raise
            time.sleep(10)


def plan(stage):
    manifest = read('docs/QUALITY_EVALUATION_V3.json')
    samples = ([s for s in manifest['development'] if s.get('id') in ('demo10', 'demo13', 'demo15')]
               if stage == 'development' else manifest['held_out'])
    assert len(samples) == 3
    candidate = read('.runtime/v8-release/release.json')
    assert sha('.runtime/v8-release/application.zip') == candidate['sha256']
    assert sha('docs/QUALITY_EVALUATION_V3.json') == candidate['evaluation_manifest_sha256']
    for path, digest in candidate['source_sha256'].items():
        assert sha(path) == digest, f'Frozen candidate source changed: {path}'
    for sample in samples:
        assert sha(sample['file']) == sample['sha256']
    baseline = read('.runtime/v7-gpu-comparison/releases.json')
    releases = {'v4': baseline['v4'], 'v5': baseline['v5'], 'v8': candidate}
    versions = [8] if stage == 'development' else [4, 5, 8]
    return samples, releases, versions


def restore(session, client, original, root):
    # No unrelated job is cancelled to make restoration convenient.
    while not infra.quiet(client):
        infra.emit('waiting_for_quiet_before_restore')
        time.sleep(20)
    current = infra.control(session)
    env = copy.deepcopy(current['env'])
    for key in ('MAPMAKER_RELEASE_KEY', 'MAPMAKER_RELEASE_SHA256'):
        env[key] = original['env'][key]
    infra.control(session, 'PATCH', body=dict(env=env, workers=dict(original['workers'], min=0, max=0)))
    while infra.control(session, suffix='/workers')['workers']:
        time.sleep(10)
    infra.control(session, 'PATCH', body=dict(workers=original['workers']))
    result = infra.control(session)
    report = dict(release=result['env']['MAPMAKER_RELEASE_SHA256'],
        env_restored=result['env'] == original['env'], workers_restored=result['workers'] == original['workers'],
        unchanged={key: result.get(key) == original.get(key) for key in ('gpu', 'scaling', 'image')})
    write(root/'rollback-result.json', report)
    infra.emit('restored', **report)
    assert report['env_restored'] and report['workers_restored'] and all(report['unchanged'].values())


def main(args):
    samples, releases, versions = plan(args.stage)
    count = len(samples) * len(versions)
    print(dict(stage=args.stage, planned_submissions=count,
               samples=[s['id'] for s in samples], versions=versions, execute=args.execute), flush=True)
    if not args.execute:
        return
    approval = read(ROOT/'approval.json')
    assert approval['authorized_by_user'] is True and approval['max_submissions'] == 13
    assert approval['candidate_sha256'] == releases['v8']['sha256']
    if args.stage == 'evaluation':
        gate = read(ROOT/'development-review.json')
        assert gate['quality_passed'] is True and gate['candidate_sha256'] == releases['v8']['sha256']
    root = ROOT/args.stage
    root.mkdir(parents=True, exist_ok=False)  # Never resubmit an interrupted stage.
    infra.ROOT = root
    load_settings()
    client = RunPodClient(infra.ENDPOINT)
    client.session.headers['Authorization'] = 'Bearer ' + Path('.runtime/runpod-api.key').read_text(encoding='utf-8-sig').strip()
    session = client.session
    original = infra.control(session)
    assert original['env']['MAPMAKER_RELEASE_SHA256'] == releases['v4']['sha256']
    assert infra.quiet(client), 'Endpoint has active or queued jobs'
    store = ArtifactStore()
    write(root/'rollback.json', dict(endpoint=infra.ENDPOINT, release=releases['v4'], workers=original['workers']))
    write(root/'evaluation-manifest.json', read('docs/QUALITY_EVALUATION_V3.json'))
    write(root/'releases.json', releases)
    jobs = []
    try:
        store.client.upload_file('.runtime/v8-release/application.zip', store.bucket, releases['v8']['key'])
        for version in versions:
            release = releases[f'v{version}']
            obj = store.client.get_object(Bucket=store.bucket, Key=release['key'])
            with obj['Body'] as body:
                assert hashlib.sha256(body.read()).hexdigest() == release['sha256']
            infra.transition(session, client, original, release)
            # One at a time: failures never trigger additional submissions.
            for sample in samples:
                assert len(jobs) < count
                rid = uuid.uuid4().hex
                run = create_run(Path(sample['file']).read_bytes(), root/'inputs'/rid)
                archive = root/(rid+'-input.zip')
                pack_run(run, archive, input_only=True)
                store.upload(rid, archive)
                payload = dict(protocol=1, run_id=rid, input_sha256=sha(archive), publish_web=True)
                intent = dict(version=version, sample=sample['id'], run_id=rid, release=release['sha256'], payload=payload)
                write(root/(rid+'-submission-intent.json'), intent)
                response = client.request('POST', 'run', {'input': payload, 'policy': {'executionTimeout': 3600000, 'ttl': 14400000}})
                job = dict(intent, job_id=response['id'], status=response.get('status', 'IN_QUEUE'))
                jobs.append(job)
                write(root/'jobs.json', jobs)
                infra.emit('submitted', version=version, sample=sample['id'], job_id=job['job_id'], run_id=rid)
                deadline = time.monotonic()+4*3600
                last = None
                while True:
                    result = poll_existing_job(client, job['job_id'])
                    job['status'] = result['status']
                    write(root/(rid+'-result.json'), result)
                    write(root/'jobs.json', jobs)
                    if last != job['status']:
                        infra.emit('progress', sample=sample['id'], status=job['status'])
                        last = job['status']
                    if job['status'] in infra.TERMINAL:
                        assert job['status'] == 'COMPLETED' and result.get('output', {}).get('success'), 'Job failed; stop this stage'
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError('Stage job deadline exceeded')
                    time.sleep(20)
    except BaseException:
        for job in jobs:
            if job['status'] not in infra.TERMINAL:
                client.cancel(job['job_id'])
        raise
    finally:
        restore(session, client, original, root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['development', 'evaluation'], required=True)
    parser.add_argument('--execute', action='store_true')
    main(parser.parse_args())
