"""Run artifacts shared by the image-only pipeline and its isolated model workers."""

from pathlib import Path
import datetime, hashlib, json, os

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "experiments/image_first_scene_object_benchmark"
SAM3D_REPO = BENCH / "model_setup/sam3d_objects/repo"
SAM3_CHECKPOINT = Path(
    "/workspace/.cache/huggingface/hub/models--facebook--sam3/snapshots/3c879f39826c281e95690f02c7821c4de09afae7/sam3.pt"
)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.part")
    tmp.write_text(json.dumps(data, indent=2, allow_nan=False))
    tmp.replace(path)


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while chunk := f.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def status(run, stage, message, **kwargs):
    record = {"stage": stage, "message": message, "updated_at": now(), **kwargs}
    write(Path(run) / "status.json", record)
    with (Path(run) / "logs/run.log").open("a") as f:
        f.write(json.dumps(record) + "\n")
