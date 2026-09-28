# SAM3D Scene Studio

For the current project architecture, validated pipeline, runtime and handoff information, see [PROJECT_CURRENT_STATE.md](docs/PROJECT_CURRENT_STATE.md).

Windows → RunPod Serverless is deployed and has passed real A40, RTX 6000 Ada and A100 SXM 80GB end-to-end runs.
The original A100 baseline regression also passed; see [current results and setup](docs/runpod_serverless_migration.md).
The historical Linux runtime and its validation are preserved below.

## Windows local UI + remote GPU

In this configured checkout, start the local web backend with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_scene_web.ps1
```

Open **http://127.0.0.1:8082**. Generate submits one complete scene to RunPod and
returns verified artifacts to `runs/{run_id}`. The local GPU is not used for inference.
Keep the local backend running until completion. A browser refresh restores the
run from its URL; a backend restart marks interrupted jobs failed and attempts cancellation.
Credentials stay in ignored `.runtime` files; setup for another checkout is in the
[migration guide](docs/runpod_serverless_migration.md).

Turn one image into an object-based 3D scene:

```text
Image → RAM++ tags → SAM3 instance masks → SAM3D objects
      → official pose transforms → scene.glb → web preview / visibility / download
```

The input is an image only. RAM++ supplies the object candidates; there is no manually supplied object list. The application reconstructs independent objects, not walls, floors, room shells, or other background geometry.

## Original Linux runtime

```bash
cd /workspace/MapMaker
npm ci --prefix web
bash scripts/start_scene_web.sh
```

The server binds to **0.0.0.0:8082** by default. Open **http://127.0.0.1:8082** locally, or use the RunPod endpoint that exposes container port **8082** for remote access. Upload an image and select **Generate 3D Scene**. The page reports the current stage and object progress, then displays the scene with orbit, zoom, pan, object visibility checkboxes, and **Export GLB**. Export downloads the complete generated scene; visibility is a preview control.

The server accepts one generation job at a time and keeps the SAM3D model loaded between jobs. The first run can spend tens of minutes importing packages and reading checkpoints on this workspace's network filesystem. Subsequent jobs reuse the loaded model. Run files survive server restarts; an interrupted inference job is not automatically resumed.

CLI alternatives:

```bash
.venv/bin/python -m mapmaker.cli doctor
.venv/bin/python -m mapmaker.cli run path/to/image.jpg --output runs/my_scene
.venv/bin/python -m mapmaker.cli render runs/my_scene/scene.glb --output runs/my_scene/previews/meshes
.venv/bin/python -m mapmaker.cli serve --port 8082
```

The output directory must not already exist. The web MVP accepts images up to 25 MB and 16 megapixels. The MVP has no built-in authentication; clients that can reach the exposed port can access uploaded images and generated artifacts. To bind only to localhost, use `bash scripts/start_scene_web.sh --host 127.0.0.1`.

## Preserved model environments

| Component | Runtime / source |
|---|---|
| Web, orchestration, mesh previews | `.venv` |
| RAM++ and SAM3 | existing `.venv-vision`, unchanged |
| SAM3D | `.venv-sam3d`, Python 3.11.0, PyTorch 2.5.1+cu121 |
| Official SAM3D source | `experiments/image_first_scene_object_benchmark/model_setup/sam3d_objects/repo`, commit `f91db411c50efee93d8db7aeb323885650f6f722` |
| Official SAM3D weights | source checkout's `checkpoints/hf` |
| DINOv2 source and pretrained ViT-L/14 registers | `.runtime/sam3d-torch/hub/` |

**Keep the SAM3D base environment at `experiments/image_first_scene_object_benchmark/model_setup/sam3d_objects/env`: `.venv-sam3d` uses its Python and native libraries.** These paths are persistent workspace files, not temporary caches. Do not upgrade the vision or SAM3D packages to run the web app. `npm ci` installs frontend dependencies only.

Recovery provenance, exact package freeze, source and weight hashes, and GPU smoke results are documented in [runtime recovery](docs/sam3d_runtime_recovery.md). The official auxiliary cache can be restored without changing packages:

```bash
source scripts/sam3d_runtime_env.sh
"$SAM3D_PYTHON" scripts/recover_dinov2.py
"$SAM3D_PYTHON" scripts/sam3d_dino_smoke.py
"$SAM3D_PYTHON" scripts/sam3d_checkpoint_preflight.py
```

## Implementation

- `mapmaker/models.py:ram_tags()` runs the existing RAM++ checkpoint. `scene_vision.py` analyzes the original image and, for larger images, five fixed overlapping regions to improve small-object recall. These regions are only for tagging: SAM3 and SAM3D receive the original full image.
- `object_candidates.py` normalizes aliases and excludes scene/background/appearance tags and minor furnishings using deterministic rules. Candidate labels are ranked by agreement across views, capped at 40. SAM3 confidence, mask area and duplicate/containment filtering select up to 12 instances. Every candidate and rejection is logged.
- `scene_reconstruct.py` uses the original official `Inference`, `compile=False`, `seed=42`, preprocessing, and mesh export. Every mask produces a separate GLB and native pose JSON.
- `scene_assembly.py` uses the official `compose_transform` used by `make_scene`. It undoes the official mesh export's axis rotation before applying the native pose. Each object is a named root node with its own mesh children. Sample vertices are checked against official `SceneVisualizer.object_pointcloud`, and exported transforms are checked after reloading the GLB. No new placement estimator is used.
- The official `make_scene` also produces a posed Gaussian PLY and reference previews. Its display normalization affects previews only, not GLB object transforms.
- `scene_pipeline.py` handles isolated model processes, artifacts and progress. `web.py` serves the local UI and generation API. `web/` uses locally installed Three.js, without a CDN.

## Run artifacts

```text
runs/<run_id>/
  input/source_image.png
  input/analysis_region_*.png
  object_candidates.json
  masks/<object_id>.png
  objects/<object_id>.glb
  objects/<object_id>.pose.json
  scene.glb
  scene_metadata.json
  status.json
  previews/masks.png
  previews/scene_posed.ply
  previews/combined_preview.png
  previews/combined_view_*.png
  previews/meshes/*.png
  logs/run.log
  logs/vision.log
  logs/segmentation.json
  logs/reconstruction.log
  logs/preview.log
```

Metadata records the actual RAM++ outputs, masks, object statuses, original poses, applied GLB matrices, model/source versions, implementation hashes, timing and errors. A failed object is recorded; successful objects can still form a scene. If every object fails, the run fails. Scene masks are binary images at original input resolution.

## Validation

```bash
.venv/bin/python scripts/validate_scene_run.py runs/<run_id>
# Compare input pixels and mask coverage against the frozen successful room:
.venv/bin/python scripts/validate_scene_run.py runs/<run_id> \
  --reference experiments/image_first_scene_object_benchmark/runs/sam3d/phase_c/main_living_room
```

The real browser test uploads an image, starts inference, checks progress, loads the GLB, toggles every object, exercises orbit/zoom/pan and compares the downloaded GLB hash:

```bash
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.runtime/browsers"
export LD_LIBRARY_PATH="$PWD/.runtime/browser-libs/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
cd web
node e2e.mjs /absolute/path/to/image.png
```

Browser validation requires the local server and Playwright Chromium. Its report is written to `.runtime/web-e2e.json` and the successful run's `logs/web_validation.json`. Browser dependencies are separate from model environments.

Frozen successful benchmark artifacts remain as regression evidence. They are not the application's object inventory or generation entrypoint.

## Verified results

See [the actual GPU, regression and browser validation report](docs/sam3d_project_validation.md), including run paths, object counts, coordinate checks, cleanup details, and observed limitations.
