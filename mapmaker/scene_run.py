"""Run artifacts shared by the image-only pipeline and its isolated model workers."""

from pathlib import Path
import datetime, hashlib, json, os

from .runtime_paths import ROOT, BENCH, SAM3D_REPO, SAM3_CHECKPOINT


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
