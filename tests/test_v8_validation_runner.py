"""Guard actual paid-execution boundaries without contacting Runpod."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from scripts import run_v8_validation as runner
from mapmaker.scene_run import write


def setup_plan(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(runner, 'plan', lambda stage: (
        [{'id': str(i)} for i in range(3)], {'v8': {'sha256': 'frozen'}},
        [8] if stage == 'development' else [4, 5, 8]))
    network = Mock(side_effect=AssertionError('Network must not be reached'))
    monkeypatch.setattr(runner, 'load_settings', network)
    return network


def test_dry_run_needs_no_approval_and_never_reaches_network(monkeypatch, tmp_path):
    network = setup_plan(monkeypatch, tmp_path)
    runner.main(SimpleNamespace(stage='development', execute=False))
    network.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_missing_approval_blocks_execution_before_network(monkeypatch, tmp_path):
    network = setup_plan(monkeypatch, tmp_path)
    with pytest.raises(FileNotFoundError):
        runner.main(SimpleNamespace(stage='development', execute=True))
    network.assert_not_called()


def test_failed_development_review_blocks_held_out_jobs(monkeypatch, tmp_path):
    network = setup_plan(monkeypatch, tmp_path)
    write(tmp_path/'approval.json', dict(authorized_by_user=True, max_submissions=13, candidate_sha256='frozen'))
    write(tmp_path/'development-review.json', dict(quality_passed=False, candidate_sha256='frozen'))
    with pytest.raises(AssertionError):
        runner.main(SimpleNamespace(stage='evaluation', execute=True))
    network.assert_not_called()
    assert not (tmp_path/'evaluation').exists()


def test_existing_stage_cannot_be_resubmitted(monkeypatch, tmp_path):
    network = setup_plan(monkeypatch, tmp_path)
    write(tmp_path/'approval.json', dict(authorized_by_user=True, max_submissions=13, candidate_sha256='frozen'))
    (tmp_path/'development').mkdir()
    with pytest.raises(FileExistsError):
        runner.main(SimpleNamespace(stage='development', execute=True))
    network.assert_not_called()


def test_transient_status_failure_reads_same_job_without_submission(monkeypatch):
    client = Mock()
    client.poll.side_effect = [RuntimeError('timeout'), {'status': 'IN_PROGRESS'}]
    monkeypatch.setattr(runner.infra, 'emit', Mock())
    monkeypatch.setattr(runner.time, 'sleep', Mock())
    assert runner.poll_existing_job(client, 'known-job') == {'status': 'IN_PROGRESS'}
    assert [call.args for call in client.poll.call_args_list] == [('known-job',), ('known-job',)]
    client.submit.assert_not_called()
    client.request.assert_not_called()
    client.cancel.assert_not_called()
