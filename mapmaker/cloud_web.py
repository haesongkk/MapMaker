"""Stateless Runpod HTTP frontend; durable GPU jobs run on the queue endpoint."""

import os
import mimetypes
import re
import tempfile
import threading
import time
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .scene_pipeline import create_run
from .scene_remote import RunPodClient, remote_failure_detail
from .scene_run import read, sha
from .scene_transfer import ArtifactStore, pack_run, safe_name
from .web import Handler


class CloudRuns:
    def __init__(self, store=None, client=None, timeout=None):
        self.store = store if store is not None else ArtifactStore()
        self.client = client if client is not None else RunPodClient()
        self.timeout = int(timeout or os.environ.get("MAPMAKER_JOB_TIMEOUT", "7200"))
        if not 60 <= self.timeout <= 21600:
            raise ValueError("MAPMAKER_JOB_TIMEOUT must be 60..21600 seconds")

    def submit(self, data):
        with tempfile.TemporaryDirectory(prefix="mapmaker-upload-") as tmp:
            run = create_run(data, Path(tmp) / uuid.uuid4().hex)
            archive = Path(tmp) / "input.zip"
            pack_run(run, archive, input_only=True)
            self.store.upload(run.name, archive)
            record = {"run_id": run.name, "metadata": read(run / "scene_metadata.json"),
                      "created": time.time(), "timeout": self.timeout,
                      "endpoint_id": self.client.endpoint}
            # Persist before submitting; never retry an ambiguous submission automatically.
            self.store.put_json(run.name, "request.json", record)
            try:
                result = self.client.submit({"protocol": 1, "run_id": run.name,
                                            "input_sha256": sha(archive),
                                            "publish_web": True}, self.timeout)
                if not re.fullmatch(r"[a-zA-Z0-9_-]+", result.get("id", "")):
                    raise ValueError("Invalid job ID")
                record["job_id"] = result["id"]
                self.store.put_json(run.name, "request.json", record)
            except Exception:
                # Return the durable ID even if the submit response was lost. A worker
                # that accepted the job can still publish completion under this ID.
                pass
            return run.name

    def state(self, run_id):
        complete = self.store.get_json(run_id, "completion.json")
        if complete is not None:
            public = {key: value for key, value in complete.items() if key != "files"}
            if public["stage"] == "done":
                public["metadata"] = {**public["metadata"],
                    "scene_bytes": complete["files"]["scene.glb"]["bytes"]}
            return public
        record = self.store.get_json(run_id, "request.json")
        if record is None:
            return None
        state = {"run_id": run_id, "metadata": record["metadata"], "stage": "queued",
                 "message": "Waiting for Runpod..."}
        terminal = self.store.get_json(run_id, "terminal.json")
        if terminal is not None:
            return {**state, **terminal}
        if time.time() - record["created"] > record["timeout"]:
            if record.get("job_id") and record["endpoint_id"] == self.client.endpoint:
                self.client.cancel(record["job_id"])
            terminal = {"stage": "failed", "message": "Runpod generation timed out"}
            self.store.put_json(run_id, "terminal.json", terminal)
            return {**state, **terminal}
        progress = self.store.progress(run_id)
        if progress and progress.get("stage") not in {"done", "failed"}:
            state.update(progress)
        if record.get("job_id") and record["endpoint_id"] == self.client.endpoint:
            result = self.client.poll(record["job_id"])
            if result["status"] in {"FAILED", "CANCELLED", "TIMED_OUT"}:
                terminal = {"stage": "failed", "message": remote_failure_detail(result)}
                self.store.put_json(run_id, "terminal.json", terminal)
                return {**state, **terminal}
            if result["status"] == "COMPLETED":
                # Completion may have appeared while polling. Older workers must
                # not silently leave the UI queued forever.
                if self.store.get_json(run_id, "completion.json") is not None:
                    return self.state(run_id)
                return {**state, "stage": "failed",
                        "message": "Worker did not publish web artifacts; deploy the updated GPU image"}
        elif not record.get("job_id"):
            state["message"] = "Submission unconfirmed; waiting for worker output. Do not resubmit yet."
        return state

    def asset(self, run_id, name, download=False):
        safe_name(name)
        complete = self.store.get_json(run_id, "completion.json")
        if complete is None or name not in complete["files"]:
            return None
        return self.store.asset_url(run_id, name, download=download)

    def asset_part(self, run_id, name, range_header=None):
        safe_name(name)
        complete = self.store.get_json(run_id, "completion.json")
        if complete is None or name not in complete["files"]:
            return None
        size = complete["files"][name]["bytes"]
        start, end = 0, size - 1
        if range_header:
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header)
            if not match:
                raise ValueError("Invalid range")
            start = int(match[1])
            end = min(int(match[2]) if match[2] else size - 1, size - 1)
        if start > end or start >= size or end - start + 1 > 16 * 1024**2:
            raise ValueError("Request an artifact range of at most 16 MiB")
        obj = self.store.client.get_object(Bucket=self.store.bucket,
            Key=self.store.key(run_id, "files/" + name), Range=f"bytes={start}-{end}")
        with obj["Body"] as body:
            data = body.read(16 * 1024**2 + 1)
        if len(data) != end - start + 1:
            raise RuntimeError("Incomplete artifact transfer")
        return data, start, end, size


class CloudHandler(Handler):
    # Each HTTP request has its own clients, avoiding shared requests.Session state.
    def service(self):
        return CloudRuns()

    def do_POST(self):
        if self.path != "/api/runs":
            return self.json({"error": "Not found"}, 404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.json({"error": "Invalid upload size"}, 400)
        if not 0 < length <= 25 * 1024 * 1024:
            return self.json({"error": "Upload one image, up to 25 MB"}, 413)
        try:
            run_id = self.service().submit(self.rfile.read(length))
            return self.json({"run_id": run_id}, 202)
        except (ValueError, OSError) as exc:
            # Do not expose storage errors, credentials, or signed URLs.
            return self.json({"error": "Invalid image or unavailable storage"}, 400)
        except Exception:
            return self.json({"error": "Cloud backend unavailable; try again later"}, 503)

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if path == "/ping":
            return self.json({"status": "healthy"})
        match = re.fullmatch(r"/api/runs/([a-f0-9]{32})", path)
        asset = re.fullmatch(r"/runs/([a-f0-9]{32})/(.+)", path)
        try:
            if match:
                state = self.service().state(match[1])
                return self.json(state or {"error": "Run not found"}, 200 if state else 404)
            if asset:
                part = self.service().asset_part(asset[1], asset[2], self.headers.get("Range"))
                if part is None:
                    return self.json({"error": "Artifact not found"}, 404)
                data, start, end, size = part
                self.send_response(206 if self.headers.get("Range") else 200)
                self.send_header("Content-Type", mimetypes.guess_type(asset[2])[0] or "application/octet-stream")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                if urlsplit(self.path).query == "download":
                    self.send_header("Content-Disposition", 'attachment; filename="scene.glb"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path.startswith(("/api/", "/runs/")):
                return self.json({"error": "Not found"}, 404)
            return super().do_GET()
        except ValueError:
            return self.json({"error": "Invalid artifact path"}, 400)
        except Exception:
            return self.json({"error": "Cloud backend unavailable; retry shortly"}, 503)


def main():
    # Validate configuration before marking this HTTP worker healthy.
    CloudRuns()
    port = int(os.environ.get("PORT", "8080"))
    health_port = int(os.environ.get("PORT_HEALTH", str(port)))
    server = ThreadingHTTPServer(("0.0.0.0", port), CloudHandler)
    if health_port != port:
        health = ThreadingHTTPServer(("0.0.0.0", health_port), CloudHandler)
        threading.Thread(target=health.serve_forever, daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
