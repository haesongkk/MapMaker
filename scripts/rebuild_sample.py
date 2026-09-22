"""Execute all sample stages in fresh processes, retaining a per-stage log.

--after-running-views only attaches to this session's already started fresh
original/views stages; the default runs everything from scratch.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

p = argparse.ArgumentParser()
p.add_argument("--output", type=Path, required=True)
p.add_argument("--after-running-views", action="store_true")
p.add_argument("--stop-after-sofa", action="store_true")
p.add_argument(
    "--resume-from",
    choices=["segment", "select-views", "meshes", "sofa-scene", "scene"],
)
args = p.parse_args()
out = args.output.resolve()
source = Path("samples/living_room.jpg").resolve()
if (
    not args.after_running_views
    and not args.resume_from
    and (out / "input.png").exists()
):
    raise SystemExit(
        "Choose a fresh output directory; existing results are never mixed."
    )
out.mkdir(parents=True, exist_ok=True)
manifest = {
    "source": str(source),
    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    "started_at": time.time(),
    "stages": [],
    "old_artifacts_reused": False,
}
if args.resume_from:
    previous = json.loads((out / "execution.json").read_text())
    if previous["source_sha256"] != manifest["source_sha256"]:
        raise SystemExit("Source changed; choose a fresh output directory.")
    manifest = previous
if args.after_running_views:
    while not (out / "videos/config.json").exists():
        time.sleep(5)
    assert (out / "analysis/camera.json").exists()
    manifest["stages"] = [
        {
            "name": name,
            "log": str(out / f"{name}.log"),
            "attached_to_current_fresh_run": True,
        }
        for name in ("original", "views")
    ]
env = os.environ.copy()
env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="4", PYTHONUNBUFFERED="1")
stages = [
    "original",
    "views",
    "candidates",
    "segment",
    "select-views",
    "meshes",
    "sofa-scene",
    "scene",
]
if args.after_running_views:
    stages = stages[2:]
if args.resume_from:
    stages = stages[stages.index(args.resume_from) :]
if args.stop_after_sofa:
    stages = stages[:-1]
for stage in stages:
    command = [
        sys.executable,
        "-m",
        "mapmaker.cli",
        "step",
        stage,
        str(source),
        "--output",
        str(out),
        "--moge-python",
        ".venv-moge/bin/python",
        "--gen3c-python",
        ".venv-gen3c/bin/python",
        "--vision-python",
        ".venv-vision/bin/python",
        "--hunyuan-python",
        ".venv/bin/python",
        "--distance",
        "0.8",
        "--angle",
        "90",
    ]
    log_path = out / f"{stage}.log"
    if log_path.exists():
        attempt = sum(e["name"] == stage for e in manifest["stages"])
        log_path.rename(out / f"{stage}.attempt{attempt}.log")
    entry = {"name": stage, "command": command, "started_at": time.time()}
    manifest["stages"].append(entry)
    (out / "execution.json").write_text(json.dumps(manifest, indent=2))
    print("Starting", stage, flush=True)
    with (out / f"{stage}.log").open("w") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env)
    entry.update(returncode=result.returncode, finished_at=time.time())
    (out / "execution.json").write_text(json.dumps(manifest, indent=2))
    if result.returncode:
        raise SystemExit(f"{stage} failed; see {out}/{stage}.log")
print("Completed stages:", ", ".join(e["name"] for e in manifest["stages"]), flush=True)
