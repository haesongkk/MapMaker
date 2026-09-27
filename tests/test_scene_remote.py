import io
import os
import shutil
import stat
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from mapmaker.scene_pipeline import create_run, configured_pipeline
from mapmaker.scene_remote import RemotePipeline
from mapmaker.scene_run import read, write, sha, status
from mapmaker.scene_transfer import ArtifactStore, pack_run, unpack_run, materialize


def make_run(tmp_path):
    data = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(data, "PNG")
    return create_run(data.getvalue(), tmp_path / ("a" * 32))


def remote_result(run, tmp_path):
    remote = tmp_path / "worker" / run.name
    shutil.copytree(run, remote)
    (remote / "scene.glb").write_bytes(b"test-glb")
    write(remote / "object_candidates.json", {"raw_tags": ["chair"]})
    meta = read(remote / "scene_metadata.json")
    meta["scene_asset"] = "scene.glb"
    write(remote / "scene_metadata.json", meta)
    status(remote, "done", "Done")
    archive = tmp_path / "result.zip"
    pack_run(remote, archive)
    return archive, {"run_id": run.name, "archive_sha256": sha(archive),
                     "scene_sha256": sha(remote / "scene.glb")}


@pytest.mark.parametrize("name", ["../escape", "input/../../escape", "/input/a", "input\\a", "input/a:b", "input/CON.txt", "input/a."])
def test_reject_unsafe_archive_paths(tmp_path, name):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        entry = zipfile.ZipInfo("placeholder")
        entry.filename = name  # Bypass Windows ZipInfo's slash normalization.
        z.writestr(entry, b"bad")
    with pytest.raises(ValueError):
        unpack_run(archive, tmp_path / "out")


def test_reject_archive_symlink(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        entry = zipfile.ZipInfo("input/link")
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(entry, "../../other")
    with pytest.raises(ValueError):
        unpack_run(archive, tmp_path / "out")


def test_verified_materialization(tmp_path):
    run = make_run(tmp_path)
    archive, output = remote_result(run, tmp_path)
    materialize(archive, run, output)
    assert read(run / "status.json")["stage"] == "done"
    assert sha(run / "scene.glb") == output["scene_sha256"]


@pytest.mark.parametrize("field", ["archive_sha256", "scene_sha256", "run_id"])
def test_corrupt_result_never_publishes_done(tmp_path, field):
    run = make_run(tmp_path)
    archive, output = remote_result(run, tmp_path)
    output[field] = "wrong"
    with pytest.raises(ValueError):
        materialize(archive, run, output)
    assert not (run / "scene.glb").exists()
    assert read(run / "status.json")["stage"] == "queued"


class Client:
    endpoint = "test-endpoint"

    def __init__(self, result):
        self.result = result
        self.submissions = []
        self.cancelled = []

    def submit(self, payload, timeout):
        self.submissions.append(payload)
        return {"id": "job-1"}

    def poll(self, job):
        return self.result

    def cancel(self, job):
        self.cancelled.append(job)


class Store:
    def __init__(self, archive=None):
        self.archive = archive

    def upload(self, run_id, path):
        with zipfile.ZipFile(path) as z:
            assert set(z.namelist()) == {"input/source_image.png", "scene_metadata.json"}

    def url(self, *args):
        return "https://storage.example/scoped-url"

    def download(self, run_id, path):
        shutil.copyfile(self.archive, path)

    def progress(self, run_id):
        return None

    def model_urls(self, expiry):
        return {}


def test_remote_one_job_and_integrity(tmp_path):
    run = make_run(tmp_path)
    archive, output = remote_result(run, tmp_path)
    client = Client({"status": "COMPLETED", "output": output})
    RemotePipeline(client, Store(archive)).run(run)
    assert len(client.submissions) == 1
    assert "base64" not in str(client.submissions)
    assert read(run / "logs/remote_integrity.json")["verified"]


@pytest.mark.parametrize("terminal", ["FAILED", "CANCELLED", "TIMED_OUT"])
def test_remote_failure_is_terminal_locally(tmp_path, terminal):
    run = make_run(tmp_path)
    with pytest.raises(RuntimeError):
        RemotePipeline(Client({"status": terminal}), Store()).run(run)
    assert read(run / "status.json")["stage"] == "failed"


def test_interruption_cancels_remote(tmp_path):
    run = make_run(tmp_path)
    client = Client({"status": "IN_PROGRESS"})
    pipeline = RemotePipeline(client, Store())
    pipeline.stopping.set()
    with pytest.raises(TimeoutError):
        pipeline.run(run)
    assert client.cancelled == ["job-1"]
    assert read(run / "status.json")["stage"] == "failed"


def test_windows_backend_does_not_import_gpu(monkeypatch):
    monkeypatch.setenv("MAPMAKER_BACKEND", "runpod")
    assert isinstance(configured_pipeline(), RemotePipeline)


def test_restart_marks_interrupted_run_failed_and_cancels(tmp_path):
    run = make_run(tmp_path)
    write(run / "logs/remote_job.json", {"job_id": "job-1", "endpoint_id": "test-endpoint"})
    client = Client({})
    RemotePipeline(client, Store()).recover_interrupted(tmp_path)
    assert client.cancelled == ["job-1"]
    assert read(run / "status.json")["stage"] == "failed"


def test_failure_releases_existing_generation_lock(tmp_path, monkeypatch):
    from mapmaker import web
    run = make_run(tmp_path)
    monkeypatch.setattr(web, "PIPELINE", RemotePipeline(Client({"status": "FAILED"}), Store()))
    assert web.BUSY.acquire(blocking=False)
    web.background(run)
    assert web.BUSY.acquire(blocking=False)
    web.BUSY.release()
    assert read(run / "status.json")["stage"] == "failed"


def test_real_http_duplicate_request_is_rejected(tmp_path, monkeypatch):
    import http.client
    import threading
    from http.server import ThreadingHTTPServer
    from mapmaker import web
    monkeypatch.setattr(web, "ROOT", tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    assert web.BUSY.acquire(blocking=False)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
        conn.request("POST", "/api/runs", body=b"image")
        response = conn.getresponse()
        assert response.status == 409
        assert b"A scene is already generating" in response.read()
        conn.close()
    finally:
        web.BUSY.release()
        server.shutdown()
        server.server_close()
        thread.join()


def test_stream_body_context_download(tmp_path):
    class FakeClient:
        def get_object(self, **kwargs):
            return {"Body": io.BytesIO(b"streamed bytes")}
    store = ArtifactStore.__new__(ArtifactStore)
    store.client = FakeClient()
    target = tmp_path / "file"
    store.download_object("bucket", "key", target)
    assert target.read_bytes() == b"streamed bytes"
    with pytest.raises(ValueError):
        store.download_object("bucket", "key", target, limit=2)


def test_model_cache_checks_hash_and_reuses(tmp_path, monkeypatch):
    from mapmaker import model_cache as cache
    import hashlib
    run = make_run(tmp_path)
    item = {"key": "original-model", "path": "sam3/model", "bytes": 5,
            "sha256": hashlib.sha256(b"model").hexdigest()}
    write(tmp_path / "configs/serverless/model-storage.json", {"source_volume": "bucket", "files": [item]})
    monkeypatch.setattr(cache, "ROOT", tmp_path)
    monkeypatch.setattr(cache, "MODEL_ROOT", tmp_path / "models")
    monkeypatch.setattr(cache, "READY", False)
    class ModelStore:
        calls = 0
        def download_object(self, bucket, key, path, limit):
            self.calls += 1
            path.write_bytes(b"model")
    store = ModelStore()
    cache.prepare_models(store, run)
    cache.prepare_models(store, run)
    assert store.calls == 1
    assert (tmp_path / "models/sam3/model").read_bytes() == b"model"


def test_failed_worker_diagnostics_materialize(tmp_path):
    run = make_run(tmp_path)
    remote = tmp_path / "worker" / run.name
    shutil.copytree(run, remote)
    status(remote, "failed", "OOM")
    write(remote / "logs/gpu_measurement.json", {"success": False})
    archive = tmp_path / "failure.zip"
    pack_run(remote, archive)
    materialize(archive, run, {"run_id": run.name, "archive_sha256": sha(archive),
                              "scene_sha256": None, "success": False})
    assert read(run / "status.json")["stage"] == "failed"
    assert read(run / "logs/gpu_measurement.json")["success"] is False


def test_private_settings_keep_explicit_environment_precedence(tmp_path, monkeypatch):
    from mapmaker import remote_settings
    monkeypatch.setattr(remote_settings, "ROOT", tmp_path)
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "explicit-endpoint")
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    monkeypatch.delenv("AWS_SHARED_CREDENTIALS_FILE", raising=False)
    write(tmp_path / ".runtime/runpod-settings.json", {
        "RUNPOD_ENDPOINT_ID": "saved-endpoint", "RUNPOD_API_KEY": "ignored-value",
        "UNRELATED_SETTING": "ignored",
    })
    (tmp_path / ".runtime/runpod-api.key").write_text("local-test-key\n")
    (tmp_path / ".runtime/runpod-s3.credentials").write_text("[default]\n")
    remote_settings.load_settings()
    assert os.environ["RUNPOD_ENDPOINT_ID"] == "explicit-endpoint"
    assert os.environ["RUNPOD_API_KEY"] == "local-test-key"
    assert "UNRELATED_SETTING" not in os.environ
    assert os.environ["AWS_SHARED_CREDENTIALS_FILE"] == str(tmp_path / ".runtime/runpod-s3.credentials")
