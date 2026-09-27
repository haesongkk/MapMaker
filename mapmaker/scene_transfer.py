"""Small JSON jobs, streamed binary artifacts, and verified local materialization."""

import os
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from .scene_run import read, sha

MAX_ARCHIVE_BYTES = 8 * 1024**3
ALLOWED_DIRS = {"input", "masks", "objects", "previews", "logs"}
ALLOWED_FILES = {"scene.glb", "scene_metadata.json", "object_candidates.json", "status.json"}


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or any(ord(c) < 32 for c in name) or "\\" in name or ":" in name or path.is_absolute()
            or any(p in {"", ".", ".."} for p in name.split("/"))
            or any(p.endswith((".", " ")) for p in path.parts)
            or any(re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?", p)
                   for p in path.parts)):
        raise ValueError("Unsafe artifact path")
    if len(path.parts) == 1 and name not in ALLOWED_FILES:
        raise ValueError("Unexpected root artifact")
    if len(path.parts) > 1 and path.parts[0] not in ALLOWED_DIRS:
        raise ValueError("Unexpected artifact directory")
    return path


def pack_run(run, archive, *, input_only=False):
    run = Path(run)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
        paths = ([run / "input/source_image.png", run / "scene_metadata.json"]
                 if input_only else sorted(run.rglob("*")))
        for path in paths:
            if path.is_symlink():
                raise ValueError("Artifact symlinks are not supported")
            if path.is_file():
                name = path.relative_to(run).as_posix()
                safe_name(name)
                z.write(path, name)


def unpack_run(archive, target):
    target = Path(target).resolve()
    seen = set()
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist()) > MAX_ARCHIVE_BYTES:
            raise ValueError("Artifact bundle exceeds size limit")
        for info in z.infolist():
            safe_name(info.orig_filename)
            path = safe_name(info.filename)
            if info.filename.casefold() in seen or info.is_dir():
                raise ValueError("Duplicate or non-file artifact")
            seen.add(info.filename.casefold())
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                raise ValueError("Non-regular artifact")
            destination = target.joinpath(*path.parts)
            if not destination.resolve().is_relative_to(target):
                raise ValueError("Artifact escapes target")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, destination.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)


def materialize(archive, run, output):
    run = Path(run)
    if sha(archive) != output["archive_sha256"]:
        raise ValueError("Result archive SHA-256 mismatch")
    with tempfile.TemporaryDirectory(prefix=".receive-", dir=run.parent) as tmp:
        staged = Path(tmp)
        unpack_run(archive, staged)
        meta = read(staged / "scene_metadata.json")
        if meta["run_id"] != run.name or output["run_id"] != run.name:
            raise ValueError("Result run ID mismatch")
        if sha(staged / "input/source_image.png") != sha(run / "input/source_image.png"):
            raise ValueError("Result input SHA-256 mismatch")
        success = output.get("success", True)
        expected_stage = "done" if success else "failed"
        if read(staged / "status.json")["stage"] != expected_stage:
            raise ValueError("Remote scene status mismatch")
        if success:
            if meta.get("scene_asset") != "scene.glb":
                raise ValueError("Remote scene asset missing")
            if sha(staged / "scene.glb") != output["scene_sha256"]:
                raise ValueError("Scene GLB SHA-256 mismatch")
        # Publish status last: the viewer must never see done before every file exists.
        for path in sorted(staged.rglob("*")):
            if path.is_file() and path.name != "status.json":
                dest = run / path.relative_to(staged)
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.replace(path, dest)
        os.replace(staged / "status.json", run / "status.json")


class ArtifactStore:
    """S3-compatible storage, including an existing RunPod volume's S3 API.

    Workers use S3 credentials configured privately on their endpoint.
    Storage location does not constrain GPU scheduling (no volume attachment).
    """

    def __init__(self):
        import boto3
        from botocore.config import Config
        from .remote_settings import load_settings
        load_settings()
        self.bucket = os.environ["MAPMAKER_S3_BUCKET"]
        self.client = boto3.client(
            "s3", endpoint_url=os.environ.get("MAPMAKER_S3_ENDPOINT"),
            region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
            config=Config(signature_version="s3v4", retries={"max_attempts": 3},
                          connect_timeout=15, read_timeout=60),
        )

    def key(self, run_id, name):
        return f"mapmaker-jobs/{run_id}/{name}"

    def upload(self, run_id, path):
        self.client.upload_file(str(path), self.bucket, self.key(run_id, "input.zip"))

    def upload_result(self, run_id, path):
        self.client.upload_file(str(path), self.bucket, self.key(run_id, "result.zip"))

    def put_progress(self, run_id, data):
        self.client.put_object(Bucket=self.bucket, Key=self.key(run_id, "progress.json"), Body=data)

    def progress(self, run_id):
        import json
        from botocore.exceptions import ClientError
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=self.key(run_id, "progress.json"))
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise
        with obj["Body"] as body:
            return json.loads(body.read(64 * 1024))

    def download_object(self, bucket, key, path, limit=MAX_ARCHIVE_BYTES):
        obj = self.client.get_object(Bucket=bucket, Key=key)
        with obj["Body"] as body, Path(path).open("wb") as dst:
            total = 0
            while chunk := body.read(1024 * 1024):
                total += len(chunk)
                if total > limit:
                    raise ValueError("Result archive exceeds size limit")
                dst.write(chunk)

    def download(self, run_id, path):
        self.download_object(self.bucket, self.key(run_id, "result.zip"), path)

    def download_input(self, run_id, path):
        self.download_object(self.bucket, self.key(run_id, "input.zip"), path)
