"""Reversible native-candidate endpoint settings; never submits inference jobs."""
import copy
import time

from scripts import run_approved_v7_comparison as infra

MANAGED_ENV = ('MAPMAKER_RELEASE_KEY', 'MAPMAKER_RELEASE_SHA256',
               'MAPMAKER_BOOTSTRAP', 'MAPMAKER_OVERLAP_REPAIR')


def candidate_environment(original, release, bootstrap):
    import hashlib
    if hashlib.sha256(bootstrap.encode()).hexdigest() != release['bootstrap_sha256']:
        raise ValueError('Bootstrap checksum mismatch')
    if release.get('required_environment') != {'MAPMAKER_OVERLAP_REPAIR': '1'}:
        raise ValueError('Unexpected candidate environment requirements')
    env = copy.deepcopy(original['env'])
    env.update(MAPMAKER_RELEASE_KEY=release['key'], MAPMAKER_RELEASE_SHA256=release['sha256'],
               # The control API removes terminal newlines from environment
               # values. Verify original bytes above, send its canonical value.
               MAPMAKER_BOOTSTRAP=bootstrap.rstrip('\r\n'), MAPMAKER_OVERLAP_REPAIR='1')
    return env


def replace_environment(session, client, original, expected_env, target_env, *, timeout=600):
    """Read before/after changes; refuse concurrent edits and active jobs.

    If interrupted after stopping workers, caller may resume with the same
    expected and target environments. No jobs are cancelled or resubmitted.
    """
    if not infra.quiet(client):
        raise RuntimeError('Endpoint has active or queued jobs')
    current = infra.control(session)
    for key in ('gpu', 'scaling', 'image'):
        if current.get(key) != original.get(key):
            raise RuntimeError(f'Concurrent endpoint change: {key}')
    stopped = dict(original['workers'], min=0, max=0)
    if current['workers'] not in (original['workers'], stopped):
        raise RuntimeError('Concurrent worker configuration change')
    if current['env'] not in (expected_env, target_env):
        raise RuntimeError('Concurrent environment change')
    # Even matching environment values do not prove that older workers exited.
    infra.control(session, 'PATCH', body=dict(env=target_env, workers=stopped))
    observed = infra.control(session)
    if observed['env'] != target_env or observed['workers'] != stopped:
        raise RuntimeError('Stopped candidate configuration read-back mismatch')
    deadline = time.monotonic() + timeout
    while infra.control(session, suffix='/workers')['workers']:
        if time.monotonic() >= deadline:
            raise TimeoutError('Old workers remain; leave stopped for recovery')
        time.sleep(10)
    infra.control(session, 'PATCH', body=dict(workers=original['workers']))
    observed = infra.control(session)
    if observed['env'] != target_env or observed['workers'] != original['workers']:
        raise RuntimeError('Restored worker configuration read-back mismatch')
    for key in ('gpu', 'scaling', 'image'):
        if observed.get(key) != original.get(key):
            raise RuntimeError(f'Endpoint setting changed during transition: {key}')
    return dict(release=target_env.get('MAPMAKER_RELEASE_SHA256'),
                environment_verified=True, workers_verified=True)


def restore_environment(session, client, original, candidate_env, *, timeout=600):
    # Preserve unrelated concurrent environment edits, but never overwrite a
    # third-party change to one of the candidate's managed values.
    current = infra.control(session)
    target = copy.deepcopy(current['env'])
    for key in MANAGED_ENV:
        missing = object()
        value = current['env'].get(key, missing)
        if value not in (candidate_env.get(key, missing), original['env'].get(key, missing)):
            raise RuntimeError(f'Concurrent managed environment change: {key}')
        if key in original['env']:
            target[key] = original['env'][key]
        else:
            target.pop(key, None)
    return replace_environment(session, client, original, current['env'], target, timeout=timeout)
