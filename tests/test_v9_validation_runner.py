"""Guard actual paid-execution boundaries without contacting Runpod."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from scripts import run_v9_validation as runner
from mapmaker.scene_run import write


def setup_plan(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(runner, 'plan', lambda stage: (
        [{'id': str(i)} for i in range(3)], {'v9': {'sha256': 'frozen'}},
        [9] if stage == 'development' else [4, 5, 9]))
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


def test_twelve_remaining_requires_browser_evaluation_reservation(monkeypatch, tmp_path):
    network = setup_plan(monkeypatch, tmp_path)
    write(tmp_path/'approval.json', dict(authorized_by_user=True, max_submissions=12,
        candidate_sha256='frozen', browser_evaluation_sample='living_room'))
    with pytest.raises(AssertionError):
        runner.main(SimpleNamespace(stage='development', execute=True))
    network.assert_not_called()


def test_evaluation_reserves_one_cell_for_browser(monkeypatch, tmp_path, capsys):
    network = setup_plan(monkeypatch, tmp_path)
    runner.main(SimpleNamespace(stage='evaluation', execute=False,
        browser_evaluation_sample='living_room'))
    assert "'planned_submissions': 8" in capsys.readouterr().out
    network.assert_not_called()


@pytest.mark.parametrize('ceiling,duplicate', [(17,False),(20,True)])
def test_v10_counts_failed_and_cancelled_prior_submissions(monkeypatch,tmp_path,ceiling,duplicate):
    network=setup_plan(monkeypatch,tmp_path)
    monkeypatch.setattr(runner,'plan',lambda stage: (
        [{'id':str(i)} for i in range(3)],{'v10':{'sha256':'candidate'}},[10]))
    prior=tmp_path/'prior.json'
    jobs=[dict(job_id=str(i),status='CANCELLED' if i==0 else 'COMPLETED') for i in range(8)]
    if duplicate:jobs[-1]['job_id']='0'
    write(prior,jobs)
    write(tmp_path/'approval.json',dict(authorized_by_user=True,max_submissions=12,
        candidate_sha256='candidate',browser_evaluation_sample='living_room',
        prior_job_manifests=[str(prior)],prior_submissions=8,combined_ceiling=ceiling,
        stages=dict(development=3,evaluation_api=8,evaluation_browser=1)))
    with pytest.raises(AssertionError):
        runner.main(SimpleNamespace(stage='development',execute=True,browser_evaluation_sample='living_room'))
    network.assert_not_called()
    assert not (tmp_path/'development').exists()


def test_v10_dry_run_uses_candidate_version_and_browser_reservation(monkeypatch,tmp_path,capsys):
    network=setup_plan(monkeypatch,tmp_path)
    monkeypatch.setattr(runner,'plan',lambda stage:(
        [{'id':str(i)} for i in range(3)],{'v10':{'sha256':'candidate'}},[4,5,10]))
    runner.main(SimpleNamespace(stage='evaluation',execute=False,browser_evaluation_sample='living_room'))
    output=capsys.readouterr().out
    assert "'planned_submissions': 8" in output and "'versions': [4, 5, 10]" in output
    network.assert_not_called()
