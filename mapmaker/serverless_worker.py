"""Queue worker. One resident Pipeline, one complete scene per RunPod job."""

import os
import re
import tempfile
import threading
import traceback
from pathlib import Path

from .scene_pipeline import Pipeline
from .scene_run import read, sha, status
from .scene_transfer import ArtifactStore, pack_run, unpack_run
from .gpu_measurement import GpuMeasurement
from .model_cache import prepare_models

PIPELINE = None
LOCK = threading.Lock()


def report_progress(run, store, stop):
    previous = None
    while not stop.wait(2):
        try:
            content = (run / "status.json").read_bytes()
            if content != previous:
                store.put_progress(run.name, content)
                previous = content
        except Exception:
            pass


def handler(job):
    global PIPELINE
    payload = job["input"]
    if payload.get("protocol") != 1 or not re.fullmatch(r"[a-f0-9]{32}", payload.get("run_id", "")):
        raise ValueError("Invalid MapMaker job")
    # Local scratch supports atomic rename; do not write inference artifacts on global storage.
    scratch = Path(os.environ.get("MAPMAKER_SCRATCH", "/tmp/mapmaker-jobs"))
    scratch.mkdir(parents=True, exist_ok=True)
    with LOCK, tempfile.TemporaryDirectory(dir=scratch) as tmp:
        store = ArtifactStore()
        root = Path(tmp)
        archive = root / "input.zip"
        store.download_input(payload["run_id"], archive)
        if sha(archive) != payload["input_sha256"]:
            raise ValueError("Input bundle SHA-256 mismatch")
        run = root / payload["run_id"]
        run.mkdir()
        unpack_run(archive, run)
        meta = read(run / "scene_metadata.json")
        if meta["run_id"] != run.name or meta["input_image"] != "input/source_image.png":
            raise ValueError("Input metadata mismatch")
        if sha(run / "input/source_image.png") != meta["input_sha256"]:
            raise ValueError("Input image SHA-256 mismatch")
        for name in ("masks", "objects", "previews", "logs"):
            (run / name).mkdir(exist_ok=True)
        status(run, "queued", "Starting RunPod scene pipeline...")
        stop = threading.Event()
        reporter = threading.Thread(target=report_progress, args=(run, store, stop), daemon=True)
        reporter.start()
        success = False
        try:
            prepare_models(store, run)
            if PIPELINE is None:
                PIPELINE = Pipeline()
            with GpuMeasurement(run):
                PIPELINE.run(run)
            success = True
        except Exception as exc:
            # Preserve diagnostics (including OOM measurements) in the same artifact channel.
            with (run / "logs/worker.log").open("a") as log:
                traceback.print_exc(file=log)
            status(run, "failed", f"Worker pipeline failed ({type(exc).__name__}); see logs")
        finally:
            stop.set()
            reporter.join(timeout=46)
        archive = root / "result.zip"
        pack_run(run, archive)
        store.upload_result(run.name, archive)
        return {"protocol": 1, "run_id": run.name, "archive_sha256": sha(archive),
                "success": success,
                "scene_sha256": sha(run / "scene.glb") if success else None,
                "archive_bytes": archive.stat().st_size}


def main():
    import runpod
    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
