"""Stage verified original model files on local worker disk, independently of GPU region."""

import json
from pathlib import Path, PurePosixPath

from .runtime_paths import ROOT, MODEL_ROOT
from .scene_run import sha, status

READY = False


def prepare_models(store, run):
    global READY
    if READY:
        return
    manifest = json.loads((ROOT / "configs/serverless/model-storage.json").read_text())
    for index, item in enumerate(manifest["files"]):
        rel = PurePosixPath(item["path"])
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("Invalid model manifest path")
        path = MODEL_ROOT.joinpath(*rel.parts)
        status(run, "loading", f"Preparing model files {index + 1}/{len(manifest['files'])}...")
        if path.is_file() and path.stat().st_size == item["bytes"] and sha(path) == item["sha256"]:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".part")
        store.download_object(manifest["source_volume"], item["key"], partial, limit=item["bytes"])
        if partial.stat().st_size != item["bytes"] or sha(partial) != item["sha256"]:
            partial.unlink(missing_ok=True)
            raise ValueError(f"Model checksum mismatch: {item['path']}")
        partial.replace(path)
    READY = True
