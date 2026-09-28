# Windows + RunPod Serverless migration

Updated 2026-09-28. **Real A40, RTX 6000 Ada and A100 SXM 80GB end-to-end validation passed.**
The original A100 baseline regression also passed. Machine-readable evidence is in
[runpod_serverless_validation.json](runpod_serverless_validation.json); full logs,
meshes and metadata remain in the local `runs` directories identified there.

## Run this checkout

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_scene_web.ps1
```

Open http://127.0.0.1:8082. Upload one image and Generate. Windows runs the existing
web backend, job transport and Three.js viewer; it does not run local model inference.
The server is already configured in this checkout. Keep it running until completion.
Refreshing the browser restores the run from `?run=<id>` without resubmitting it.

## Deployment identity

- Endpoint: `8dzbkfrxys43hb` (`mapmaker-scene-validation`), queue-based, one GPU.
- Runtime commit: `8a0bcaa35349d4ed488728e219185c8668de6ac9`.
- Image: `registry.runpod.net/haesongkk-mapmaker-codex-runpod-serverless-migration-deploy-runpod-dockerfile:8a0bcaa35`.
- Pulled digest: `sha256:5aec52d956c31d1aeb7d15b13320731d21c5c5b842cad3afab23737950c0f586`.
- GitHub-managed build: `0ba9702b-827e-4025-b74e-5013cc66fd96`, completed
  2026-09-27 20:49:03 UTC. All 438 frozen SAM3D package records matched; native
  imports and vision imports through the actual application interpreter path passed.
- Default GPU selection is restricted to tested A40 and RTX 6000 Ada. The shared
  pools also contain untested A6000, L40, L40S and Blackwell MIG; these are explicitly excluded.
- Workers min/max 0/1, 100 GB local disk, 60-second idle timeout, no attached volume,
  no data-center restriction, host CUDA >=12.8 among the configured versions.
- Execution limit 7200 seconds. `RUNPOD_INIT_TIMEOUT=1800` accommodates the large
  runtime ([official setting](https://docs.runpod.io/serverless/development/optimization)).
- `codex/runpod-serverless-migration` remains pinned to the runtime commit so report
  changes do not automatically rebuild it. `codex/runpod-serverless-validation-results`
  contains the runtime plus local diagnostics/UI fixes and the final evidence.
- Original A100 Pods were not modified or restarted. Existing storage capacity and
  region are unchanged; job artifacts use the separate `mapmaker-jobs/` prefix.

## Preserved pipeline and environments

```text
Windows image -> S3 input archive -> one RunPod /run job
  -> RAM++ -> deterministic candidate filtering -> SAM3 instance masks
  -> resident SAM3D -> original native pose / GLB conversion -> independent nodes
  -> S3 result archive -> verified local runs/{run_id} -> existing viewer
```

`models.py`, `object_candidates.py`, and `scene_assembly.py` are unchanged. No manual
object list, new placement math, quantization, reduced resolution, or quality changes
were used. SAM3D stays `compile=False`, `seed=42`. RAM++/SAM3 reload once per scene as
before; the resident SAM3D process is reused across objects and warm scene jobs.

| Environment | Exact runtime / source |
|---|---|
| Windows orchestration | Python 3.11.9 in local `.venv`; no Torch inference |
| Worker orchestration | Separate `.venv`, RunPod SDK 1.10.1 |
| Vision | Python 3.12.3, Torch 2.8.0+cu128, original overlay + system packages |
| SAM3D | Python 3.11.0, Torch 2.5.1+cu121, frozen 438-package audit |
| SAM3D source | `f91db411c50efee93d8db7aeb323885650f6f722` |
| DINOv2 source | `7764ea0f912e53c92e82eb78a2a1631e92725fc8` |

SAM3 and RAM revisions, recovered conda YAML, vision overlay, and the immutable
26-file model manifest are under `configs/serverless`. The Docker build keeps
three environments and compiles native targets sm80, sm86, sm89+PTX. DINO weights
and the original MoGe/BERT caches are preserved and HF online fallback is disabled.

`runtime_paths.py` centralizes model paths. The worker uses `/opt/mapmaker-models`
and local `/tmp/mapmaker-jobs` scratch. The Linux fallback layout is repository-relative;
new code does not depend on `/workspace/MapMaker`. Interpreter symlinks are deliberately
not resolved, preserving the vision virtual environment.

## Actual GPU validation

| Case | Objects | Pipeline seconds | SAM3D readiness seconds | Sampled peak device MiB | Local end-to-end seconds |
|---|---:|---:|---:|---:|---:|
| A40, reference room cold | 6/6 | 241.08 | 53.572 | 22,781 | 525.67 |
| A40, user city warm | 3/3 | 75.86 | 0.004 | 22,451 | 87.19 |
| RTX 6000 Ada, reference room cold | 6/6 | 208.41 | 53.569 | 22,988 | 1123.52 |
| A100 SXM 80GB, reference room cold | 6/6 | 222.52 | 60.019 | 23,757 | 1352.50 |

All four completed with no pipeline errors, valid GLB nodes/transforms, previews,
and verified archive/scene SHA-256. A40 driver: 595.91.07. Ada driver: 580.159.04.
A100 driver: 580.126.16. All ran SAM3D Torch 2.5.1+cu121 / CUDA 12.1 / Python 3.11.0. Application logs selected
`sdpa` attention on A40/Ada and `flash_attn` on A100, retaining the original GPU-based
automatic selection. All used `spconv` sparse convolution (`auto`). These logs identify the
application backend, not every internal SDPA kernel dispatch. Allocator peaks are
in the JSON report, separately from whole-device measurements sampled every second.
Short device peaks can be missed; these images do not establish a universal VRAM limit.

A40 jobs used the previous `b22b70789` image with the same interpreter-path fix applied
through the startup command while the replacement built. Ada and A100 used the final image
with the normal module entrypoint; the temporary override was removed. This distinction
is retained in the report rather than attributing every test to the final image.

Reference comparison against the recovered original A100 production run:

| Measurement | A40 | RTX 6000 Ada | A100 SXM 80GB |
|---|---:|---:|---:|
| Missing/additional objects | 0/0 | 0/0 | 0/0 |
| Minimum mask IoU | 0.999318 | 0.999565 | 1.0 |
| Maximum pose rotation difference | 0.985 degrees | 0.342 degrees | 0.0000025 degrees |
| Maximum translation distance | 0.00953 native units | 0.00539 native units | 0 |
| Scale ratio range | 0.98676-1.00980 | 0.99343-1.01130 | 1.0 |

Cross-GPU results are close, not bitwise identical. Pose/assembly algorithms were
not adjusted to force agreement. The original reference has GLB SHA-256
`144d62362c93ff2ff21570d4aa37d4efc5be5984508567c83415702985aa83c9` and lives at
`.runtime/reference-living-room` locally.

Chrome displayed the returned six-object room, and toggling loveseat off/on visibly
removed/restored it. GLB export triggered a browser download. The city result is in
`runs/2e58128c189949f0a959803306afc83f`; the unchanged extraction policy selected
`city`, `lush`, and `coast`. All three remain independent nodes.

Local checks: **47 tests passed**, compileall, JavaScript syntax and diff checks passed.
The original clone had 20 tests; old handoff test counts refer to another workspace.
Real duplicate generation returned HTTP 409 without submitting another job. A worker
failure returned diagnostics and released the local lock; an HTTP submission failure
also became local `failed`. These are separate from the successful GPU runs above.

## Storage decision and measured trade-offs

The connected MCP/API and account UI were inspected before choosing storage. Existing
volume `mapmaker-storage` (`qv17bc1sx8`, 500 GB, EU-RO-1) serves model files through S3;
it is **not mounted on the inference worker**. GPU placement is therefore unrestricted,
which was verified by execution in EU-SE-1, US-WA-1 and US-MD-1. The source still has regional
availability dependency and cross-region transfer latency.

[Global Volume overview](https://docs.runpod.io/storage/globalvolume/overview) advertises
Serverless support, but this account's UI exposed only Network Volume attachment;
the connected MCP and [REST v2 schema](https://api.runpod.io/v2/openapi.json) exposed
no Global Volume attach field. The linked Serverless detail page returned 404. A real
Global Volume mount could not be demonstrated; no unsupported attach request was invented.

| Option | Finding / trade-off |
|---|---|
| Global Volume | Attractive read-mostly model storage; actual Serverless attach not verified |
| [HF cached model](https://docs.runpod.io/serverless/endpoints/model-caching) | Region-independent host cache, but one repository/model per endpoint; multiple original caches need a new private bundle |
| Private image with weights | Simple immutable package, but larger image and redistribution review |
| Immutable object files (chosen) | Existing authenticated storage, no GPU region binding; repeated cold downloads |
| Regional replicas | Faster regional reads; duplicated storage and replication maintenance |

The manifest has 26 files totaling 21,385,172,187 bytes. Files are hash-checked and
atomically published on worker-local disk, then reused while the worker lives.
Observed staging was about 197 seconds in EU-SE-1 and 649 seconds in US-WA-1, before
inference (A100 in US-MD-1: 437 seconds). Initial image pull is additional: the final image is roughly 18.59 GB
compressed, preserving the successful environments. Cold starts can take many minutes.
Warm city generation completed end-to-end in 87 seconds. Min-zero workers avoid
continuous active GPU charges; warm retention lasts only for the configured idle period.

All inference scratch and artifact assembly remain local to the worker. S3 holds
small progress objects and input/result ZIPs. Authenticated S3 SDK transfer is used:
real presigned GET testing on RunPod S3 returned 401 `missing Authorization header`.
The user approved S3 keys stored in RunPod Secrets and referenced by the worker.
No credentials or model weights are in Git or the Docker build context.

## Model redistribution review

No model weights were copied into an image or published.

- [SAM3D pinned source license](https://github.com/facebookresearch/sam-3d-objects/blob/f91db411c50efee93d8db7aeb323885650f6f722/LICENSE)
  and [SAM3 model license](https://huggingface.co/facebook/sam3/blob/main/LICENSE):
  SAM License; retain the agreement with any redistributed materials and preserve
  its use restrictions. Private packaging is not an exemption from the license.
- [RAM++ repository license](https://github.com/xinyu1205/recognize-anything/blob/main/LICENSE):
  Apache-2.0. Original checkpoint provenance/model-specific terms still need to be
  checked against the actual preserved checkpoint before image redistribution.
- [DINO pinned source license](https://github.com/facebookresearch/dinov2/blob/7764ea0f912e53c92e82eb78a2a1631e92725fc8/LICENSE):
  Apache-2.0. Preserve license/notices with its source and matching official weights.

## Local setup

Use Python >=3.10 for the CPU web environment. This Windows verification used
Python 3.11.9; **this is not the SAM3D Python**, which must remain 3.11.0 on Linux.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -e '.[remote]'
npm.cmd ci --prefix web
$env:RUNPOD_ENDPOINT_ID = '<deployed-endpoint-id>'
# RUNPOD_API_KEY must be provided privately to this process, not committed.
$env:MAPMAKER_S3_BUCKET = 'qv17bc1sx8'
$env:MAPMAKER_S3_ENDPOINT = 'https://s3api-eu-ro-1.runpod.io'
$env:AWS_DEFAULT_REGION = 'EU-RO-1'
.venv\Scripts\python.exe -m mapmaker.cli doctor
.\scripts\start_scene_web.ps1
```

S3 credentials use the standard AWS provider chain (`~/.aws/credentials`, environment,
etc.). `scripts/configure_runpod_s3.ps1` provides an interactive prompt and saves
`.runtime/runpod-s3.credentials`, excluded from Git; the transport and launcher
recognize that file automatically. RunPod S3 credentials differ from the MCP/API key.
Never commit either. Local S3 authentication was configured and verified.
The backend also reads `.runtime/runpod-settings.json` for endpoint/storage settings
and `.runtime/runpod-api.key` for the job API key. Explicit environment variables take
precedence. `scripts/configure_runpod_api.ps1` saves a key through a hidden local prompt.
Keep input/output job objects until validation finishes; no automatic deletion or
lifecycle rule was enabled on the user's existing volume.

[RunPod's operation reference](https://docs.runpod.io/serverless/endpoints/operation-reference)
specifies a 10 MB `/run` payload and 30-minute result retention. This implementation
uses run identity/hashes and polls continuously. `MAPMAKER_JOB_TIMEOUT` defaults to 7200s
(60..21600), applies to queue + execution locally and supplies explicit RunPod TTL
and execution timeout.


A100 is verified as an optional alternative, but the default endpoint selects only the
two verified 48 GB models. Catalog rates during validation were $1.22/hour (A40),
$1.75/hour (Ada), and $2.72/hour (A100); rates/availability can change. Original Pods
remain stopped. All test workers were stopped before restoring the default GPU pool.

## Failure handling and limits

One asynchronous job covers the whole scene. Submission is never automatically
retried after an ambiguous network error; polling tolerates bounded transient errors.
A failed/timeout/cancelled job releases the local lock. Backend restart marks unfinished
runs failed and attempts cancellation; cancellation failure is logged, not claimed as success.

Downloaded archives are checked for SHA-256, run/input identity, GLB SHA-256, safe paths,
symlinks, duplicates and expanded-size limits before publishing `done` last. Results
keep the original input/masks/objects/scene/metadata/previews/logs layout. Worker pipeline
failures also return their logs over the same artifact channel.

Windows CLI: `.venv\Scripts\python.exe -m mapmaker.cli run image.png` generates a
canonical UUID run directory. A custom `--output` name must be 32 lowercase hex characters
for the remote protocol; invalid names fail locally before upload. Original Linux local
execution retains arbitrary output directory names.

No artifact lifecycle deletion was enabled on the existing volume. Results survive locally
after RunPod's short status retention expires. New local orchestration records safe job
queue/execution timing and worker ID alongside artifacts before that retention expires.

On 2026-09-28, run `e5b4b3d530a7474a98dd71f312b7eb66` (job
`0ba8a6e9-8ce5-4c81-a73f-b5ae56681dd8-e2`) failed during S3 `UploadPart`
with `QuotaExceeded` on the existing 500 GB `mapmaker-storage` volume. Its last
stored progress was GLB export; the result archive never reached local storage.
Local orchestration now recognizes this cause and saves a sanitized diagnosis and
job timing in `logs/runpod_failure.json`, rather than showing only “inspect worker
logs.” This reporting fix does not free storage: space must be reclaimed or the
volume enlarged before retrying. Upload failure also prevents delivery of worker
diagnostics, and temporary worker artifacts are removed when the handler exits.
The user authorized expanding this volume to 550 GB, and RunPod confirmed the
resize on 2026-09-28. The estimated standard storage charge increases from
$35 to $38.50 per month; GPU execution remains billed separately. The original
image was resubmitted as run `65db3225cab34978868d888c014268d7` for verification.
That retry completed successfully: 6/6 objects, no errors, verified archive/GLB
hashes and artifact validation, and the browser rendered the scene. Job
`212116fc-8403-4fc0-9ce7-60c85c0d2eae-e2` ran on RTX 6000 Ada worker
`ye5nw99g18rsyg`, with 56.721 seconds queue delay, 834.802 seconds execution,
and 910.344 seconds total local round trip including cold model preparation.

## Deployment issues resolved

1. The first managed build exceeded its 30-minute limit while exporting a cache-heavy
   image. A final runtime stage excludes builder caches and compiler intermediates.
2. The first GPU attempt staged every model but launched the base vision Python because
   a symlink was resolved. The interpreter path is now preserved, tested, and exercised
   by the image's final build-time import check.
3. Browser refresh previously lost the active run. The URL now restores polling without
   submitting another job. Failure placeholders now show a stopped state.
4. A submission immediately after changing GPU configuration was rejected; authentication
   and health remained valid. A later fresh submission succeeded.
   Local failures now preserve the HTTP status code without exposing response secrets.
