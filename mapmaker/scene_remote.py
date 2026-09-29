"""Windows orchestration only: one asynchronous RunPod job per complete scene."""

import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path

from .scene_run import read, write, sha, status, now
from .scene_transfer import ArtifactStore, pack_run, materialize


def remote_failure_detail(result):
    """Expose recognized causes, never arbitrary worker text or signed URLs."""
    error = result.get("error", "")
    if isinstance(error, str):
        try:
            error = json.loads(error)
        except (ValueError, TypeError):
            pass
    message = error.get("error_message", "") if isinstance(error, dict) else error
    if isinstance(message, str) and "QuotaExceeded" in message:
        return "Storage quota exceeded (QuotaExceeded): result upload failed. Free storage space or increase the RunPod network volume before retrying."
    return "Inspect worker logs for the failure cause."


class RunPodClient:
    def __init__(self):
        import requests
        from .remote_settings import load_settings
        load_settings()
        endpoint = os.environ["RUNPOD_ENDPOINT_ID"]
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", endpoint):
            raise ValueError("Invalid RUNPOD_ENDPOINT_ID")
        self.endpoint = endpoint
        self.base = f"https://api.runpod.ai/v2/{endpoint}"
        self.session = requests.Session()
        self.session.headers["Authorization"] = "Bearer " + os.environ["RUNPOD_API_KEY"]

    def request(self, method, operation, data=None):
        # No automatic POST retry: an ambiguous submission must not create two GPU jobs.
        try:
            response = self.session.request(method, self.base + "/" + operation,
                                            json=data, timeout=(15, 60))
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            detail = f"HTTP {code}" if code is not None else type(exc).__name__
            raise RuntimeError(f"RunPod {operation.split('/')[0]} request failed ({detail})") from None

    def submit(self, payload, timeout):
        return self.request("POST", "run", {"input": payload, "policy": {
            "executionTimeout": timeout * 1000, "ttl": timeout * 1000}})

    def poll(self, job):
        return self.request("GET", "status/" + job)

    def cancel(self, job):
        return self.request("POST", "cancel/" + job)


class RemotePipeline:
    def __init__(self, client=None, store=None, timeout=None, poll_interval=3):
        self.client = client
        self.store = store
        self.timeout = int(timeout or os.environ.get("MAPMAKER_JOB_TIMEOUT", "7200"))
        if not 60 <= self.timeout <= 21600:
            raise ValueError("MAPMAKER_JOB_TIMEOUT must be 60..21600 seconds")
        self.poll_interval = poll_interval
        self.stopping = threading.Event()
        self.active = None

    def close(self):
        self.stopping.set()
        if self.active and self.client:
            try:
                self.client.cancel(self.active)
            except Exception:
                pass

    def run(self, run):
        run = Path(run)
        started = time.monotonic()
        job = None
        remote_terminal = False
        try:
            if not re.fullmatch(r"[a-f0-9]{32}", run.name):
                raise ValueError("RunPod run directory must have a 32-character lowercase hex ID; omit --output to generate one")
            self.client = self.client or RunPodClient()
            self.store = self.store or ArtifactStore()
            status(run, "queued", "Uploading image for RunPod...")
            with tempfile.TemporaryDirectory(prefix=".transfer-", dir=run.parent) as tmp:
                archive = Path(tmp) / "input.zip"
                pack_run(run, archive, input_only=True)
                self.store.upload(run.name, archive)
                payload = {
                    "protocol": 1, "run_id": run.name, "input_sha256": sha(archive),
                }
                response = self.client.submit(payload, self.timeout)
                job = response["id"]
                if not re.fullmatch(r"[a-zA-Z0-9_-]+", job):
                    raise ValueError("Invalid RunPod job ID")
                self.active = job
                # Persist identity, never API keys.
                write(run / "logs/remote_job.json", {
                    "job_id": job, "endpoint_id": self.client.endpoint, "submitted_at": now(),
                })
                last_progress = None
                failures = 0
                while True:
                    if self.stopping.is_set() or time.monotonic() - started > self.timeout:
                        raise TimeoutError("RunPod generation interrupted or timed out")
                    try:
                        result = self.client.poll(job)
                        failures = 0
                    except RuntimeError:
                        failures += 1
                        if failures >= 5:
                            raise
                        self.stopping.wait(self.poll_interval)
                        continue
                    state = result["status"]
                    if state == "COMPLETED":
                        remote_terminal = True
                        output = result["output"]
                        write(run / "logs/runpod_timing.json", {
                            key: result.get(key) for key in
                            ("id", "status", "delayTime", "executionTime", "workerId")
                        })
                        status(run, "exporting", "Downloading and verifying scene...")
                        archive = Path(tmp) / "result.zip"
                        self.store.download(run.name, archive)
                        from .scene_placement import finalize_scene
                        materialize(archive, run, output, finalize=finalize_scene)
                        if not output.get("success", True):
                            raise RuntimeError("Worker pipeline failed; diagnostics downloaded to this run's logs")
                        write(run / "logs/remote_integrity.json", {
                            "job_id": job, "archive_sha256": sha(archive),
                            "scene_sha256": sha(run / "scene.glb"), "verified": True,
                            "worker_scene_sha256": output.get("scene_sha256"),
                            "local_finalization": read(run / "scene_metadata.json").get("placement"),
                            "round_trip_seconds": time.monotonic() - started,
                        })
                        return
                    if state in {"FAILED", "CANCELLED", "TIMED_OUT"}:
                        remote_terminal = True
                        detail = remote_failure_detail(result)
                        write(run / "logs/runpod_failure.json", {
                            **{key: result.get(key) for key in
                               ("id", "status", "delayTime", "executionTime", "workerId")},
                            "detail": detail,
                        })
                        raise RuntimeError(f"RunPod job {job}: {state}; {detail}")
                    try:
                        progress = self.store.progress(run.name)
                    except Exception:
                        progress = None  # Progress delivery cannot fail a running GPU job.
                    if progress and progress != last_progress and progress.get("stage") not in {"done", "failed"}:
                        write(run / "status.json", progress)
                        last_progress = progress
                    elif not last_progress:
                        status(run, "queued", f"RunPod: {state}")
                    self.stopping.wait(self.poll_interval)
        except Exception as exc:
            if job and not remote_terminal:
                try:
                    self.client.cancel(job)
                except Exception:
                    write(run / "logs/remote_cancel.json", {"job_id": job, "confirmed": False})
            # Exceptions from S3 can include signed URLs; expose only the error type.
            message = str(exc) if isinstance(exc, (RuntimeError, ValueError, TimeoutError)) else f"Remote generation failed ({type(exc).__name__}); check backend configuration"
            meta = read(run / "scene_metadata.json")
            meta["errors"].append({"stage": "runpod", "error": message})
            write(run / "scene_metadata.json", meta)
            status(run, "failed", message)
            raise
        finally:
            self.active = None

    def recover_interrupted(self, runs):
        """A process restart cannot resume the old background thread."""
        for record in Path(runs).glob("*/status.json"):
            run = record.parent
            try:
                if read(record)["stage"] in {"done", "failed"}:
                    continue
                job_file = run / "logs/remote_job.json"
                cancelled = False
                if job_file.exists():
                    saved = read(job_file)
                    try:
                        self.client = self.client or RunPodClient()
                        if self.client.endpoint == saved["endpoint_id"]:
                            self.client.cancel(saved["job_id"])
                            cancelled = True
                    except Exception:
                        pass
                    write(run / "logs/remote_cancel.json", {
                        "job_id": saved["job_id"], "confirmed": cancelled,
                    })
                status(run, "failed", "Local backend restarted during generation; submit a new run")
            except (OSError, ValueError, KeyError):
                continue
