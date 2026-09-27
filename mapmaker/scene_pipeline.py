"""Single-image production pipeline, preserving separate vision/SAM3D environments."""

from pathlib import Path
import argparse, atexit, io, os, subprocess, sys, time, traceback, uuid
from PIL import Image, ImageOps
from .scene_run import ROOT, now, read, write, sha, status
from .runtime_paths import VISION_PYTHON


def create_run(data, output=None):
    with Image.open(io.BytesIO(data)) as im:
        if im.width * im.height > 16_000_000:
            raise ValueError("Please use an image with at most 16 megapixels")
        image = ImageOps.exif_transpose(im).convert("RGB")
    run = Path(output).resolve() if output else ROOT / "runs" / uuid.uuid4().hex
    run.mkdir(parents=True, exist_ok=False)
    for folder in ("input", "masks", "objects", "previews", "logs"):
        (run / folder).mkdir()
    image.save(run / "input/source_image.png")
    write(
        run / "scene_metadata.json",
        {
            "run_id": run.name,
            "created_at": now(),
            "input_image": "input/source_image.png",
            "input_sha256": sha(run / "input/source_image.png"),
            "input_size": list(image.size),
            "objects": [],
            "scene_asset": None,
            "pipeline": {
                "object_extraction_model": "RAM++",
                "segmentation_model": "SAM3",
                "reconstruction_model": "SAM3D",
                "placement_method": "official make_scene/compose_transform + inverse GLB export rotation",
                "structural_geometry": False,
            },
            "timing": {},
            "errors": [],
        },
    )
    status(run, "queued", "Waiting to generate...")
    return run


class Pipeline:
    def __init__(self):
        self.worker = None
        self.worker_log = None
        atexit.register(self.close)

    def close(self):
        if self.worker and self.worker.poll() is None:
            self.worker.terminate()
            try:
                self.worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.worker.kill()
                self.worker.wait()
        if self.worker_log:
            self.worker_log.close()

    def reconstruct(self, run):
        if self.worker is None or self.worker.poll() is not None:
            (ROOT / ".runtime").mkdir(exist_ok=True)
            self.worker_log = (ROOT / ".runtime/sam3d-service.log").open("a")
            self.worker = subprocess.Popen(
                ["bash", str(ROOT / "scripts/run_sam3d_worker.sh"), "--serve"],
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=self.worker_log,
                stderr=subprocess.STDOUT,
                text=True,
            )
        self.worker.stdin.write(__import__("json").dumps({"run": str(run)}) + "\n")
        self.worker.stdin.flush()
        result = run / "logs/reconstruction_result.json"
        while not result.exists():
            if self.worker.poll() is not None:
                if self.worker_log:
                    self.worker_log.flush()
                service_log = ROOT / ".runtime/sam3d-service.log"
                if service_log.is_file():
                    import shutil
                    shutil.copyfile(service_log, run / "logs/sam3d-service.log")
                raise RuntimeError(
                    "SAM3D worker exited; inspect reconstruction.log and .runtime/sam3d-service.log"
                )
            time.sleep(0.5)
        answer = read(result)
        if not answer["ok"]:
            raise RuntimeError(answer["error"])

    def run(self, run):
        run = Path(run)
        start = time.monotonic()
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
            env.setdefault("OMP_NUM_THREADS", "8")
            env.setdefault("MKL_NUM_THREADS", "8")
            with (run / "logs/vision.log").open("w") as log:
                subprocess.run(
                    [
                        str(VISION_PYTHON),
                        "-m",
                        "mapmaker.scene_vision",
                        str(run),
                    ],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                )
            self.reconstruct(run)
            with (run / "logs/preview.log").open("w") as log:
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "mapmaker.scene_preview",
                        str(run / "scene.glb"),
                        "--out",
                        str(run / "previews/meshes"),
                        "--material",
                    ],
                    cwd=ROOT,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                )
            meta = read(run / "scene_metadata.json")
            meta["timing"]["total_seconds"] = time.monotonic() - start
            meta["finished_at"] = now()
            write(run / "scene_metadata.json", meta)
            count = sum(o["status"] == "generated" for o in meta["objects"])
            status(
                run,
                "done",
                f"Done — {count} objects",
                current=count,
                total=len(meta["objects"]),
                errors=meta["errors"],
            )
        except Exception as exc:
            with (run / "logs/run.log").open("a") as log:
                traceback.print_exc(file=log)
            meta = read(run / "scene_metadata.json")
            meta["errors"].append({"stage": "pipeline", "error": str(exc)})
            meta["timing"]["total_seconds"] = time.monotonic() - start
            write(run / "scene_metadata.json", meta)
            status(run, "failed", str(exc))
            raise


def configured_pipeline():
    backend = os.environ.get("MAPMAKER_BACKEND", "runpod" if os.name == "nt" else "local")
    if backend == "runpod":
        from .remote_settings import load_settings
        load_settings()
        from .scene_remote import RemotePipeline
        return RemotePipeline()
    if backend != "local":
        raise ValueError("MAPMAKER_BACKEND must be local or runpod")
    return Pipeline()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("image", type=Path)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    run = create_run(args.image.read_bytes(), args.output)
    pipeline = configured_pipeline()
    try:
        pipeline.run(run)
        print(run / "scene.glb")
    finally:
        pipeline.close()


if __name__ == "__main__":
    main()
