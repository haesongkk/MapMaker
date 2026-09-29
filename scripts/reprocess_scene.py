"""Replay saved real inference artifacts into a new run without GPU or credentials."""

import argparse
import shutil
import uuid
from pathlib import Path

from mapmaker.scene_run import ROOT, read, write, status
from mapmaker.scene_placement import finalize_scene


def replay(source, output=None):
    source = Path(source).resolve()
    meta = read(source / "scene_metadata.json")
    if meta.get("placement"):
        raise ValueError("Use an original, uncorrected source run")
    if read(source / "status.json")["stage"] != "done":
        raise ValueError("Use a completed source run")
    output = Path(output).resolve() if output else ROOT / "runs" / uuid.uuid4().hex
    output.mkdir(parents=True, exist_ok=False)
    for folder in ("input", "masks", "objects"):
        shutil.copytree(source / folder, output / folder)
    for folder in ("logs", "previews"):
        (output / folder).mkdir()
    shutil.copy2(source / "scene.glb", output / "scene.glb")
    if (source / "object_candidates.json").exists():
        shutil.copy2(source / "object_candidates.json", output / "object_candidates.json")
    meta["run_id"] = output.name
    meta["validation_replay"] = {"source_run": source.name, "mode": "saved SAM3D artifacts; no new AI inference"}
    write(output / "scene_metadata.json", meta)
    status(output, "assembling", "Replaying saved meshes and poses")
    try:
        finalize_scene(output)
        status(output, "done", "Done — reprocessed saved scene")
    except Exception as exc:
        status(output, "failed", str(exc))
        raise
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(replay(args.source, args.output))
