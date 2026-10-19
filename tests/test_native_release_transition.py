import copy
import hashlib
import pytest

from scripts import native_release_transition as transition


def setup(monkeypatch):
    original = dict(env={'MAPMAKER_RELEASE_SHA256': 'old', 'MAPMAKER_BOOTSTRAP': 'old code', 'SECRET': 'opaque'},
                    workers=dict(min=0, max=1, idleTimeout=60), gpu={'id': 'unchanged'},
                    scaling={}, image='unchanged')
    state = copy.deepcopy(original)
    mutations = []
    def control(session, method='GET', suffix='', body=None):
        if suffix == '/workers':
            return {'workers': []}
        if method == 'PATCH':
            mutations.append(copy.deepcopy(body))
            state.update(copy.deepcopy(body))
            if 'env' in body:
                state['env']['MAPMAKER_BOOTSTRAP'] = state['env']['MAPMAKER_BOOTSTRAP'].strip()
        return copy.deepcopy(state)
    monkeypatch.setattr(transition.infra, 'control', control)
    monkeypatch.setattr(transition.infra, 'quiet', lambda client: True)
    bootstrap = 'verified native bootstrap\n'
    release = dict(key='candidate/key', sha256='new', bootstrap_sha256=hashlib.sha256(bootstrap.encode()).hexdigest(),
                   required_environment={'MAPMAKER_OVERLAP_REPAIR': '1'})
    candidate = transition.candidate_environment(original, release, bootstrap)
    return original, state, mutations, candidate


def test_apply_and_restore_all_managed_values(monkeypatch):
    original, state, mutations, candidate = setup(monkeypatch)
    transition.replace_environment(None, None, original, original['env'], candidate)
    assert state['env'] == candidate
    state['env']['UNRELATED_NEW_SETTING'] = 'keep'
    transition.restore_environment(None, None, original, candidate)
    assert state['env'] == dict(original['env'], UNRELATED_NEW_SETTING='keep')
    assert state['workers'] == original['workers']
    assert len(mutations) == 4


def test_busy_endpoint_never_mutated(monkeypatch):
    original, state, mutations, candidate = setup(monkeypatch)
    monkeypatch.setattr(transition.infra, 'quiet', lambda client: False)
    with pytest.raises(RuntimeError, match='active or queued'):
        transition.replace_environment(None, None, original, original['env'], candidate)
    assert not mutations


def test_concurrent_managed_change_is_preserved(monkeypatch):
    original, state, mutations, candidate = setup(monkeypatch)
    state['env'] = dict(candidate, MAPMAKER_BOOTSTRAP='someone else changed this')
    with pytest.raises(RuntimeError, match='Concurrent managed'):
        transition.restore_environment(None, None, original, candidate)
    assert not mutations


def test_interrupted_stopped_transition_can_resume(monkeypatch):
    original, state, mutations, candidate = setup(monkeypatch)
    state.update(env=candidate, workers=dict(original['workers'], min=0, max=0))
    transition.replace_environment(None, None, original, original['env'], candidate)
    assert state['workers'] == original['workers']


def test_worker_shutdown_timeout_does_not_restart_workers(monkeypatch):
    original, state, mutations, candidate = setup(monkeypatch)
    control = transition.infra.control
    def workers_remain(session, method='GET', suffix='', body=None):
        if suffix == '/workers':
            return {'workers': [{'id': 'old-worker'}]}
        return control(session, method, suffix, body)
    monkeypatch.setattr(transition.infra, 'control', workers_remain)
    with pytest.raises(TimeoutError, match='Old workers remain'):
        transition.replace_environment(None, None, original, original['env'], candidate, timeout=0)
    assert state['workers']['max'] == 0
    assert len(mutations) == 1


def test_unexpected_environment_prevents_candidate_application(monkeypatch):
    original, state, mutations, candidate = setup(monkeypatch)
    state['env']['NEW_EXTERNAL_VALUE'] = 'keep'
    with pytest.raises(RuntimeError, match='Concurrent environment'):
        transition.replace_environment(None, None, original, original['env'], candidate)
    assert not mutations


def test_wrong_bootstrap_hash_is_rejected():
    release = dict(bootstrap_sha256='not-the-file-hash')
    with pytest.raises(ValueError, match='checksum'):
        transition.candidate_environment({'env': {}}, release, 'changed code')
