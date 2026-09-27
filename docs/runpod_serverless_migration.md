# RunPod Serverless migration — in progress

Updated 2026-09-28. **Not deployed or GPU validated.** This document distinguishes
implemented transport from the original GPU validation recorded in
`sam3d_project_validation.md`. Do not treat local tests as evidence of GPU compatibility.

## Implemented locally

- Windows web and CLI default to the RunPod backend. `scripts/start_scene_web.ps1`
  binds the existing web app to localhost:8082. Linux retains the original local
  pipeline by default. `MAPMAKER_BACKEND=local|runpod` selects explicitly.
- One `/run` request contains a complete scene job. Poll `/status/{job_id}` with
  bounded transient retries; do not automatically retry an ambiguous submission.
- Source PNG and metadata travel in an uncompressed ZIP over authenticated S3.
  Job JSON contains only run identity and hashes. The worker uses S3 credentials
  supplied privately in endpoint configuration; no credentials enter the image.
  Real RunPod S3 presigned GET testing failed with HTTP 401 / `missing Authorization
  header`, so presigned URLs are not used by this deployment.
- The queue handler reuses one `Pipeline` and its existing resident SAM3D process.
  Vision and SAM3D remain separate environments/processes. RAM++/SAM3 currently
  reload once per scene, as before; SAM3D is not reloaded per object or warm job.
- Worker status is periodically uploaded to a small S3 object. Local status keeps
  the existing UI stages. `done` is published only after downloading and checking
  archive SHA-256, scene SHA-256, run ID and source-image SHA-256.
- Results materialize into the existing local `runs/{run_id}` layout. ZIP paths,
  symlinks, duplicate names and expanded size are checked. Input/GLB never enter
  the RunPod JSON payload as base64.
- Remote failure, cancellation, polling failure and deadline expiry become local
  `failed`; existing generation lock releases in `finally`. Restart marks unfinished
  runs failed and attempts cancellation of recorded jobs for the configured endpoint.
  Cancellation failures are recorded and require checking the remote job; local
  restart does not imply remote cancellation succeeded.
- `logs/gpu_measurement.json` samples total device memory across subprocesses.
  `logs/sam3d_gpu.json` records Python/Torch/CUDA, model readiness time, allocator peaks
  and enabled attention backends. Actual attention dispatch still requires worker logs.
- Native pose, GLB conversion, filtering, mask policies, compile=False and seed=42
  are unchanged. `scene_assembly.py`, `object_candidates.py`, `models.py` are unchanged.

## Live RunPod discovery

MCP endpoint, template, volume, pod and GPU catalog reads succeeded. No duplicate
MCP configuration was created. Initial endpoint/template lists were empty.
Existing volume: `mapmaker-storage`, `qv17bc1sx8`, 500 GB, EU-RO-1. Existing two A100
Pods were EXITED. They were not modified. No billable resources were created.

Serverless catalog snapshot (availability changes; refresh before provisioning):

| GPU | Pool | Availability | Catalog USD/hour |
|---|---|---|---:|
| A40 48 GB | AMPERE_48 | HIGH | 1.22 |
| RTX A6000 48 GB | AMPERE_48 | LOW | 1.22 |
| L40 48 GB | ADA_48_PRO | NONE | 1.75 |
| L40S 48 GB | ADA_48_PRO | LOW | 1.75 |
| RTX 6000 Ada 48 GB | ADA_48_PRO | LOW | 1.75 |
| A100 80 GB PCIe | AMPERE_80 | LOW | 2.72 |

These are capacity/price observations, **not** inference compatibility results.
Use minimum zero/maximum one worker initially, with one GPU and no regional
placement restriction unless required for a temporary source-runtime audit.

## Storage findings and provisional choice

The current [Global Volume overview](https://docs.runpod.io/storage/globalvolume/overview)
states GPU Serverless support and `/runpod-volume` mounting. However:

- The connected MCP has no Global Volume CRUD/attach tools.
- The fetched [REST v2 OpenAPI](https://api.runpod.io/v2/openapi.json) exposes regional
  network volumes; `CreateEndpointRequest` has `networkVolumes`, no global-volume field.
- This account's Serverless create UI exposes Network volumes only. The Storage
  create UI offers Global volume but describes Pod attachment.
- The overview's Serverless detail link returned 404 during this check.

Therefore actual Serverless attachment/mount has **not** been demonstrated. Do not
invent a global-volume ID or treat it as a regional volume ID. Recheck rollout before
choosing a final deployment storage configuration.

[Cached models](https://docs.runpod.io/serverless/endpoints/model-caching) are region
independent, support gated/private HF models with credentials, but currently allow
only one cached model per endpoint. MapMaker needs multiple model families plus
the pinned DINO source/cache. A combined private bundle would require an additional
upload and full license/provenance review.

Implemented fallback: immutable, hash-manifested model files read over object
storage into worker-local cache, with one central model-root configuration. The
existing RunPod volume's S3 API can serve it without attaching the regional volume
to inference workers. This avoids a new storage provider and leaves GPU scheduling
unconstrained. Trade-offs: cross-region transfer and repeated cold-start downloads;
source storage is still region-dependent for availability, even though GPU placement
is not. The source manifest has 26 files totaling 21,385,172,187 bytes (21.4 GB).
The original living-room GLB is 45,629,804 bytes. Cold-start time remains unmeasured.

Alternative comparison:

| Option | Benefit | Cost / limitation |
|---|---|---|
| Global Volume | Shared read-mostly models across regions | Account's attach path and real mount not verified |
| HF host cache | Downloads before billed worker startup | One repository/model per endpoint; multiple families need bundling |
| Private image with weights | Immutable, simple worker startup | Large image, private registry/build auth and license packaging |
| Immutable object bundle | No GPU region binding, reuse existing S3 | Download time/egress, local cache warmup |
| Regional replicas | Fast mounted reads in selected regions | Replication, duplicated storage cost and regional maintenance |

Artifacts and temporary inference writes must stay on worker-local disk, even if
Global Volume support becomes usable: global storage lacks atomic rename and full
POSIX semantics required by `scene_run.write()`.

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

## Linux runtime inputs recovered from the successful installation

`runtime_paths.py` centralizes `MAPMAKER_MODEL_ROOT`, `MAPMAKER_RAM_CHECKPOINT`,
`MAPMAKER_SAM3_CHECKPOINT`, `MAPMAKER_SAM3D_CHECKPOINT`, `MAPMAKER_DINO_PROVENANCE`,
`SAM3D_REPO`, and `MAPMAKER_VISION_PYTHON`. The original Linux layout still resolves
by default relative to the repository. `SAM3D_PYTHON`, `MAPMAKER_SAM3D_BASE` and
`TORCH_HOME` can override the existing worker launcher. Scratch defaults to
`/tmp/mapmaker-jobs` for the Serverless handler.

The original clone contained only the SAM3D successful freeze, not the original
vision environment, model weights, native libraries, or reference runs. S3 reads now
confirm that vision used Python 3.12.3 / Torch 2.8.0+cu128 with system-site-packages,
whereas SAM3D used Python 3.11.0 / Torch 2.5.1+cu121. These environments cannot simply
be merged. The vision overlay's 26 distributions and the original conda specification
are recorded under `configs/serverless/`, with SAM3 and RAM source commits.
Original native recovery builds targeted A100 sm80. A portable image must build
and verify Ampere sm86 and Ada sm89 compatibility without changing inference quality.

`deploy/runpod/Dockerfile` and `build_runtime.sh` implement a proposed reproducible
build, using verified amd64 base-image digests and separate environments. Native
build targets are sm80, sm86, and sm89+PTX. The first managed build completed native
compilation and its version audit passed all 438 records, but exceeded RunPod's
30-minute build limit while sending the exported image. The Dockerfile now uses a
separate final stage containing only installed environments and pinned sources,
excluding builder download caches and compiler intermediates. The second build
completed at 2026-09-27 20:13:06 UTC (build
`be057b93-171f-4efe-8906-1bf9955455b8`, commit `b22b70789`). The final stage repeated
the 438-record audit and passed imports for SAM3D Torch 2.5.1+cu121 and vision Torch
2.8.0+cu128. Published image:
`registry.runpod.net/haesongkk-mapmaker-codex-runpod-serverless-migration-deploy-runpod-dockerfile:b22b70789`.
GPU compatibility must not be inferred from successful compilation.
The worker stages the pinned manifest with SHA-256 checks and disables HF online
fallback. MoGe/BERT caches already used by the original pipeline are preserved;
no new depth/placement algorithm was added.

Required before an honest Docker build/deploy:

1. Verify the recovered vision/base specifications reproduce the original imports.
2. Download reference images/masks/GLBs for actual GPU regression comparison.
3. Build pinned Linux environments (SAM3D Python 3.11.0, Torch 2.5.1+cu121,
   SAM3D f91db411c50efee93d8db7aeb323885650f6f722,
   DINO 7764ea0f912e53c92e82eb78a2a1631e92725fc8).
4. Build/publish the custom image. RunPod UI offers GitHub-managed builds, so a
   separate registry is not required. The user authorized the Runpod Inc. GitHub app
   to read MapMaker code/metadata and completed GitHub identity verification.
5. Deploy and measure real A40/A6000, L40S/RTX 6000 Ada, and optionally A100 runs.
   Then run real Windows Generate → RunPod → received GLB → viewer/export checks.

## Validation so far

- Original tests in this clone: **20 passed** (the historical 48-test report refers
  to a different historical workspace/test inventory).
- Current tests including transport, integrity rejection, restart, failure-lock
  release and a real localhost HTTP 409 check: **45 passed**.
- Python compileall: passed. Frontend `npm ci`: passed.
- Real S3 input/result/progress upload/download and hash round trip: passed,
  report `.runtime/s3-transport-validation.json`.
- Actual Chrome loaded the Windows localhost UI on port 8082.
- Mock transport tests do not perform model inference or validate RunPod execution.
  Image build/publish is complete; real GPU inference and full E2E are still pending.

RunPod-managed build is now running from `codex/runpod-serverless-migration`, initial
commit `04d731bd04fe93ea09e95ae9b24c99d02e0b82cb`. Endpoint `8dzbkfrxys43hb` uses
AMPERE_48, min/max workers 0/1, 100 GB disk, a 7200-second execution timeout and no
network-volume attachment. The user explicitly authorized storing S3 credentials
as RunPod Secrets; the endpoint references them without plaintext values.
The original living-room input, metadata and 45,629,804-byte GLB were downloaded to
`.runtime/reference-living-room` for regression comparison. Its GLB SHA-256 is
`144d62362c93ff2ff21570d4aa37d4efc5be5984508567c83415702985aa83c9`.

The user supplied a separate RunPod API key through the local hidden prompt.
Authenticated endpoint health queries and every local doctor check pass. The local
web backend was restarted with the saved settings. The published image is now
initializing on A40 in EU-SE-1. Idle timeout is temporarily 60 seconds for validation
of model reuse between scenes; min/max workers remain 0/1.

The user submitted a city image through the actual Windows UI: run
`4894e94c9f684d11baaf6d970824fdbd`, job `55cfa03b-a99d-45ce-9abf-86534845ce64-e2`.
It is queued behind the initial image build. A real second HTTP submission returned
409 `A scene is already generating`, without creating a second job.
