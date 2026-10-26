"""Queue worker. One resident Pipeline, one complete scene per RunPod job."""

import os
import re
import tempfile
import threading
import traceback
from pathlib import Path

from .scene_pipeline import Pipeline
from .scene_run import read, sha, status, write
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
    if payload.get("protocol") not in (1, 2, 4) or not re.fullmatch(r"[a-f0-9]{32}", payload.get("run_id", "")):
        raise ValueError("Invalid MapMaker job")
    # Protocol 2 prevents older workers from silently running RAM++ for Qwen jobs.
    if payload.get('protocol') == 2 and payload.get('tagger') != 'qwen2.5-vl-7b':
        raise ValueError('Unsupported protocol-2 tagger')
    if payload.get('protocol') == 4 and payload.get('tagger') != 'ram++-qwen-background-v1':
        raise ValueError('Unsupported protocol-4 tagger')
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
        if payload.get('protocol') in (2, 4) and (
                meta.get('execution', {}).get('tagger') != payload['tagger'] or
                meta.get('execution', {}).get('mode') != 1):
            raise ValueError('Qwen job execution metadata mismatch')
        if meta["run_id"] != run.name or meta["input_image"] != "input/source_image.png":
            raise ValueError("Input metadata mismatch")
        if sha(run / "input/source_image.png") != meta["input_sha256"]:
            raise ValueError("Input image SHA-256 mismatch")
        if os.environ.get("MAPMAKER_RELEASE_SHA256"):
            meta["deployment"] = {"application_sha256": os.environ["MAPMAKER_RELEASE_SHA256"]}
            write(run / "scene_metadata.json", meta)
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
                PIPELINE = Pipeline(inference_checkpoint=True)
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
        try:
            pack_run(run, archive)
            store.upload_result(run.name, archive)
        except Exception:
            store.put_json(run.name, 'failure.json', dict(
                phase='result_pack_or_upload', error=traceback.format_exc(),
                metadata=read(run / 'scene_metadata.json'),
                logs={p.name: p.read_text(errors='replace')[-24000:]
                      for p in (run/'logs').glob('*.log')}))
            raise
        if payload.get("publish_web"):
            files = store.publish_files(run)
            store.put_json(run.name, "completion.json", {
                "run_id": run.name, **read(run / "status.json"),
                "metadata": read(run / "scene_metadata.json"), "files": files,
            })
        result = {"protocol": 1, "run_id": run.name, "archive_sha256": sha(archive),
                "success": success,
                "scene_sha256": sha(run / "scene.glb") if success else None,
                "archive_bytes": archive.stat().st_size}
        # Retain the verified download manifest after Runpod's job record expires.
        store.put_json(run.name, 'result-manifest.json', result)
        return result


def main():
    import runpod
    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
