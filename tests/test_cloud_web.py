import io
import time
from types import SimpleNamespace

import pytest
from PIL import Image

from mapmaker.cloud_web import CloudRuns


class Store:
    def __init__(self):
        self.records = {}

    def put_json(self, run_id, name, value):
        self.records[run_id, name] = dict(value)

    def get_json(self, run_id, name):
        return self.records.get((run_id, name))

    def upload(self, run_id, path):
        assert path.is_file()

    def progress(self, run_id):
        return {"stage": "done", "message": "Not published yet"}

    def asset_url(self, run_id, name, download=False):
        return f"https://storage.example/{run_id}/{name}"


def image_bytes():
    data = io.BytesIO()
    Image.new("RGB", (8, 8)).save(data, "PNG")
    return data.getvalue()


def client(**overrides):
    return SimpleNamespace(**{"endpoint": "gpu", "submit": lambda *_: {"id": "job-1"},
                             "poll": lambda _: {"status": "IN_PROGRESS"},
                             "cancel": lambda _: None, **overrides})


def test_new_web_worker_can_reopen_pending_and_completed_run():
    store = Store()
    run_id = CloudRuns(store, client()).submit(image_bytes())
    fresh = CloudRuns(store, client())
    assert fresh.state(run_id)["stage"] == "queued"  # Never publish progress 'done'.
    store.put_json(run_id, "completion.json", {
        "run_id": run_id, "stage": "done", "metadata": {"scene_asset": "scene.glb"},
        "files": {"scene.glb": {"sha256": "abc"}},
    })
    state = CloudRuns(store, client()).state(run_id)
    assert state["stage"] == "done"
    assert state["metadata"]["scene_url"].endswith("/scene.glb")
    assert "files" not in state
    assert fresh.asset(run_id, "scene.glb")
    assert fresh.asset(run_id, "logs/missing.log") is None
    with pytest.raises(ValueError):
        fresh.asset(run_id, "../secret")


def test_ambiguous_submit_keeps_durable_id_and_does_not_retry():
    store = Store()
    calls = []

    def submit(*args):
        calls.append(args)
        raise RuntimeError("Timeout")

    run_id = CloudRuns(store, client(submit=submit)).submit(image_bytes())
    assert len(calls) == 1
    assert store.get_json(run_id, "request.json")
    assert "unconfirmed" in CloudRuns(store, client()).state(run_id)["message"]


def test_timeout_and_terminal_failure_persist_across_workers():
    store = Store()
    cancelled = []
    api = client(cancel=cancelled.append)
    service = CloudRuns(store, api)
    run_id = service.submit(image_bytes())
    store.records[run_id, "request.json"]["created"] = time.time() - 10000
    assert service.state(run_id)["stage"] == "failed"
    assert CloudRuns(store, api).state(run_id)["stage"] == "failed"
    assert cancelled == ["job-1"]


def test_old_worker_completion_is_explicit_failure():
    store = Store()
    service = CloudRuns(store, client(poll=lambda _: {"status": "COMPLETED"}))
    run_id = service.submit(image_bytes())
    assert "updated GPU image" in service.state(run_id)["message"]


def test_worker_publishes_completion_only_after_artifacts(tmp_path, monkeypatch):
    from mapmaker import serverless_worker as worker
    from mapmaker.scene_pipeline import create_run
    from mapmaker.scene_run import sha, status
    from mapmaker.scene_transfer import pack_run
    import shutil
    from contextlib import nullcontext

    run = create_run(image_bytes(), tmp_path / ("a" * 32))
    bundle = tmp_path / "input.zip"
    pack_run(run, bundle, input_only=True)
    events = []

    class WorkerStore(Store):
        def download_input(self, _, target):
            shutil.copyfile(bundle, target)

        def upload_result(self, *args):
            events.append("archive")

        def publish_files(self, run):
            events.append("files")
            return {"scene.glb": {}}

        def put_json(self, *args):
            events.append("completion")
            super().put_json(*args)

    def pipeline(run):
        (run / "scene.glb").write_bytes(b"glb")
        status(run, "done", "Done")

    monkeypatch.setenv("MAPMAKER_SCRATCH", str(tmp_path / "scratch"))
    monkeypatch.setattr(worker, "ArtifactStore", WorkerStore)
    monkeypatch.setattr(worker, "prepare_models", lambda *_: None)
    monkeypatch.setattr(worker, "GpuMeasurement", lambda _: nullcontext())
    monkeypatch.setattr(worker, "PIPELINE", SimpleNamespace(run=pipeline))
    result = worker.handler({"input": {"protocol": 1, "run_id": run.name,
                            "input_sha256": sha(bundle), "publish_web": True}})
    assert result["success"]
    assert events == ["archive", "files", "completion"]


def test_http_frontend_static_upload_status_and_safe_redirect():
    from http.client import HTTPConnection
    from http.server import ThreadingHTTPServer
    import json
    import threading
    from mapmaker.cloud_web import CloudHandler

    store = Store()
    service = CloudRuns(store, client())

    class TestHandler(CloudHandler):
        def service(self):
            return service

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(method, path, body=None):
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.request(method, path, body=body)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    try:
        assert request("GET", "/ping")[0] == 200
        assert b"<html" in request("GET", "/")[2].lower()
        assert request("POST", "/api/runs", b"not an image")[0] == 400
        code, _, body = request("POST", "/api/runs", image_bytes())
        assert code == 202
        run_id = json.loads(body)["run_id"]
        assert json.loads(request("GET", f"/api/runs/{run_id}")[2])["stage"] == "queued"
        assert request("GET", f"/runs/{run_id}/scene.glb")[0] == 404
        store.put_json(run_id, "completion.json", {
            "run_id": run_id, "stage": "done", "metadata": {}, "files": {"scene.glb": {}}})
        code, headers, _ = request("GET", f"/runs/{run_id}/scene.glb?download")
        assert code == 302 and headers["Location"].startswith("https://storage.example/")
        assert request("GET", f"/runs/{run_id}/../secret")[0] == 400
        assert request("GET", "/api/runs/bad-id")[0] == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
