# PROJECT CURRENT STATE — SAM3D Scene Studio

조사 기준: **2026-09-28, Windows `D:\MapMaker`, branch `main`, HEAD `94c7b16`**.
작업 시작 시 Git working tree는 깨끗했다. 이 문서는 현재 코드·설정·로컬 산출물을 직접 조사한 handoff다. 이번 작업에서는 GPU 추론, 원격 배포 변경, 새 browser E2E를 실행하지 않았다.

기존 상태 문서는 `docs/PROJECT_CURRENT_STATE.md`에 있고 루트에는 없었다. 요청에 따라 이 루트 문서를 작성했다. 기존 문서와 README의 링크는 수정하지 않았으며, 그 문서의 Linux 경로·검증 수치를 현재 Windows 환경으로 해석하면 안 된다.

## 1. Project Overview

- 목적: 이미지 한 장에서 RAM++로 후보를 찾고 SAM3로 instance mask를 만든 다음, 공식 SAM3D로 객체별 mesh와 pose를 생성하여 독립 node가 있는 `scene.glb`로 조립한다.
- 목표 시스템: 이미지 업로드 → 자동 객체 추출·3D 생성 → 웹 3D preview·객체별 표시 전환·전체 GLB 다운로드.
- 현재 범위: 위 흐름과 Windows → RunPod Serverless 원격 실행, S3 artifact 전송·무결성 검사, 상태 표시 및 실패 처리가 구현되어 있다. 저장된 실제 GPU 성공 결과가 있다.
- 단계: **제한된 입력에서 E2E 성공 근거가 있는 MVP**. 범용 이미지 품질, 모든 GPU, 새 환경의 재현성을 모두 검증한 제품은 아니다.
- 벽·바닥·천장/room shell 복원, world expansion, 객체 transform/material 편집, AI scene editing, 프로젝트 편집 저장·불러오기는 현재 앱에 구현되어 있지 않다. URL로 기존 run을 다시 여는 기능은 있다.

상태 용어: **구현 완료**는 코드와 명시된 검증 범위를 의미한다. **구현 존재/E2E 미검증**, **일부 구현**, **legacy**, **실험용**, **미구현**, **알려진 문제**, **외부 의존으로 현재 검증 불가**를 아래에서 구분한다.

## 2. Current End-to-End Pipeline

현재 Windows 기본 경로:

```text
Browser image → local create_run → S3 input.zip → RunPod /run (scene당 1 job)
  → worker model staging → RAM++ → candidate filtering → SAM3 masks
  → resident SAM3D → native pose / GLB axis conversion → scene.glb + previews
  → S3 result.zip → local verification/materialization → status done → Three.js
```

`mapmaker/scene_pipeline.py:configured_pipeline()`은 Windows에서 기본 `runpod`, 그 외 OS에서 기본 `local`을 선택한다. `MAPMAKER_BACKEND`로 명시할 수 있다. Windows launcher는 `runpod`를 지정하며, worker는 직접 `Pipeline`을 사용한다. Linux local 경로도 코드에 남아 있으며 legacy pipeline과는 별개인 현행 실행 옵션이다.

| 단계 | 입력 → 출력 | 담당 코드 / 모델 | 확인 범위 |
|---|---|---|---|
| 입력 정규화 | 이미지 bytes → RGB PNG, metadata, queued 상태 | `scene_pipeline.py:create_run`; Pillow EXIF transpose | CPU 테스트 및 저장된 입력 |
| 원격 제출 | PNG + metadata ZIP → S3 input, job ID | `scene_remote.py:RemotePipeline.run`, `scene_transfer.py` | mock 테스트 + 기존 실제 run 로그 |
| 모델 준비 | immutable manifest → worker 로컬 모델 파일 | `serverless_worker.py:handler`, `model_cache.py:prepare_models` | 파일 크기/SHA 검사 구현, 저장된 staging/GPU 기록 |
| 태그 추출 | 원본 및 tag용 crop → raw tags/후보 | `scene_vision.py`, `models.py:ram_tags`, RAM++ | 기존 GPU run의 `object_candidates.json` |
| 후보 정리 | 실제 RAM tags → 최대 40 text prompts | `object_candidates.py:candidates`; alias/제외 규칙, 여러 view 지지 수 정렬 | 코드·기존 출력 |
| Instance segmentation | 원본 전체 이미지 + prompts → 최대 12 binary masks | `scene_vision.py:run_scene`, SAM3 | 기존 GPU 결과, 최신 run mask 재검사 |
| 객체 복원 | 원본 전체 이미지 + 각 mask → GLB, rotation/translation/scale | `scene_reconstruct.py:run_scene`, 공식 `notebook/inference.py:Inference` | 기존 A40/Ada/A100 성공 기록; 이번 추론 미실행 |
| 장면 조립 | 성공 객체 GLB + native pose → 독립 node scene | `scene_assembly.py:object_matrix/assemble` | 실행 시 공식 point transform 비교·재로드 검사; 최신 산출물 matrix 재검사 |
| Preview/완료 | scene → Gaussian PLY/PNG, CPU mesh PNG, done | `scene_reconstruct.py`, `scene_preview.py`, `scene_pipeline.py` | 기존 preview 파일·성공 상태 |
| 결과 회수 | worker ZIP → 검증된 로컬 run | `scene_transfer.py:materialize` | CPU 테스트·기존 integrity 기록·GLB hash 재검사 |
| 표시 | metadata + GLB → Three.js viewer | `web/app.js`, `web.py` | 기존 viewer 검증 기록; 이번 브라우저 미실행 |

처리 규칙:

- RAM++는 내부 384 입력 transform을 사용한다. 원본 긴 변이 768보다 크면 원본 외에 폭·높이 각각 60%인 겹치는 crop 5개를 추가한다. Crop은 tag 전용이며 SAM3/SAM3D는 원본 전체 이미지를 받는다. RAM threshold 배율은 0.75다.
- SAM3 선택 기준: confidence ≥ 0.6, mask 면적 ≥ 전체의 0.003. 면적 내림차순으로 선택하며 기존 선택 mask와 IoU > 0.8 또는 자신의 90% 초과가 포함되면 제외한다. 최대 12개다.
- 객체 ID는 정규화한 이름과 0부터 시작하는 두 자리 번호: `coffee_table_00`. 후보·제외 이유는 `object_candidates.json`, `logs/segmentation.json`에 기록한다.
- SAM3D는 `compile=False`, `seed=42`. SAM3D subprocess/model은 warm job 간 재사용하고 RAM++/SAM3 vision subprocess는 scene마다 새로 실행한다.
- 공식 `compose_transform`으로 pose를 조합하고 mesh export 축 회전을 되돌린다. GLB column-vector matrix는 `native_row.T @ undo_export`, 3×3 축 행렬은 `[[1,0,0],[0,0,-1],[0,1,0]]`다. 객체 root 아래 mesh child를 유지한다.
- 조립 시 공식 `SceneVisualizer.object_pointcloud`와 sample vertex 오차 ≤ `1e-5`를 검사하고 export 후 matrix를 `atol=1e-6`로 재검사한다. 별도 depth placement/scale fitting은 없다. Gaussian display normalization은 GLB에 적용하지 않는다.
- 일부 객체 실패는 기록 후 성공 객체로 계속 진행한다. 전부 실패하면 run 실패다. Gaussian PNG 렌더 실패는 metadata 경고로 남기지만, 조립/PLY 생성 또는 후속 CPU preview subprocess 실패는 전체 run 실패로 이어질 수 있다.

## 3. Repository Structure

| 경로 | 역할 / 진입점 / 관계 |
|---|---|
| `mapmaker/cli.py` | Typer `run`, `serve`, `render`, `doctor`; 설치 명령 `mapmaker`의 entrypoint |
| `mapmaker/web.py` | 표준 라이브러리 HTTP 서버, static/API serving, 단일 generation lock |
| `mapmaker/scene_pipeline.py`, `scene_run.py` | run 생성, 모델 subprocess 연결, JSON atomic replace, 상태·로그 |
| `mapmaker/scene_remote.py`, `scene_transfer.py`, `remote_settings.py` | Windows 원격 orchestration, job polling/cancel, ZIP/S3, private 설정 로드 |
| `mapmaker/serverless_worker.py`, `model_cache.py`, `gpu_measurement.py` | worker entrypoint, 모델 staging, scene 실행, GPU 기록 |
| `mapmaker/scene_vision.py`, `object_candidates.py` | RAM tags → 후보 → SAM3 masks; `models.py`의 `ram_tags`만 현행 extraction에서 재사용 |
| `mapmaker/scene_reconstruct.py`, `scene_assembly.py`, `scene_preview.py` | 공식 SAM3D worker, 좌표 변환/조립, CPU orthographic preview |
| `mapmaker/runtime_paths.py` | code root와 model/source/interpreter 경로 분리 |
| `web/` | `index.html`, `app.js`, `style.css`; npm lock, Three.js, Playwright E2E. 별도 frontend build 서버 없음 |
| `deploy/runpod/` | Linux amd64 Dockerfile 및 `build_runtime.sh`; 분리된 vision/SAM3D 환경과 native extension 구축 |
| `configs/serverless/`, `configs/sam3d/` | 외부 source revision, model manifest, vision overlay, conda 명세, 성공 SAM3D freeze |
| `scripts/` | OS별 launcher, credential 설정, runtime audit/recovery, GPU smoke/regression, artifact 검사 |
| `tests/` | remote protocol/상태/lock/path 테스트와 이전 geometry/pipeline CPU 테스트 |
| `runs/` | Git 제외된 실제 성공·실패 artifact. Git clone에 포함되지 않음 |
| `.runtime/` | Git 제외된 private 설정·로그·복구 reference. 키 내용을 문서/로그에 복사하지 않음 |
| `samples/living_room.jpg`, `samples/ATTRIBUTION.md` | 샘플 이미지 및 출처. 실제 검증 입력은 각 run의 PNG로 특정할 것 |
| `docs/` | 이전 handoff, runtime 복구, Linux 검증, Serverless migration/JSON evidence |

**현재 사용하지 않음 / legacy:** `mapmaker/pipeline.py`의 별도 `Pipeline`, `assembly.py`, `reconstruction.py`, `geometry.py` 및 `gen3c_*`, `moge_worker.py`, `model_worker.py`는 이전 depth/video/mesh 접근 관련 코드다. `scene_pipeline.Pipeline`과 혼동하지 않는다. `models.py`도 MoGe/Gen3C/Hunyuan 기능을 함께 포함하지만 그 전체가 현행 실행 경로는 아니다. `raster.py` 등은 기존 테스트에서 사용하고 `models.py:ram_tags`는 현행 코드가 재사용하므로 legacy 관련 파일을 일괄 삭제하면 안 된다.

## 4. Runtime / Environment

| 영역 | 현재 확인한 사실 |
|---|---|
| 로컬 | Windows, `D:\MapMaker`; `.venv` Python **3.11.9** 실행 확인. `pyproject.toml` 요구는 Python ≥3.10 |
| 로컬 패키지 | 설치 확인: numpy 2.4.6, Pillow 12.3.0, trimesh 5.1.0, requests 2.34.2, boto3 1.43.103, pytest 9.1.1. 이는 모델 환경 버전이 아님 |
| Frontend | 로컬 Node **22.14.0**; `package.json`에 Node engines 제한 없음. Three.js **0.180.0**, Playwright **1.55.1**, `package-lock.json` 존재 |
| Worker OS | Dockerfile은 pinned `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` base와 Linux amd64 build를 명시 |
| Vision | build assertion/config: Python **3.12.3**, Torch **2.8.0+cu128**; `.venv-vision`은 base system packages + pinned overlay |
| SAM3D | config 및 저장된 GPU 로그: Python **3.11.0**, Torch **2.5.1+cu121**, CUDA **12.1**; 별도 `.venv-sam3d`와 `/opt/sam3d-base` |
| Native 환경 | CUDA toolkit/compiler·conda는 `sam3d-conda.yml`; flash-attn, pytorch3d, gsplat, kaolin 등은 freeze/build script. native target `8.0;8.6;8.9+PTX` |
| Worker orchestrator | `.venv`; optional dependency `runpod==1.10.1`; Docker build `uv sync --frozen --no-dev --extra serverless --extra remote` |
| GPU | 실제 저장 결과는 A40, RTX 6000 Ada, A100-SXM4-80GB. CPU inference fallback 없음. 약 22–24천 MiB의 샘플 peak는 해당 입력 기록이며 최소 VRAM 보장이 아님 |
| 로컬 모델 부재 | `.venv-vision`, `.venv-sam3d`, `experiments/`, `checkpoints/`, `external/` 모두 현재 Windows root에 없음 |

핵심 설정:

| 설정 | 의미 / 기본값 |
|---|---|
| `MAPMAKER_BACKEND` | `runpod` 또는 `local`; OS별 기본값은 §2 |
| `RUNPOD_API_KEY`, `RUNPOD_ENDPOINT_ID` | RunPod job API 인증·endpoint |
| `MAPMAKER_S3_BUCKET`, `MAPMAKER_S3_ENDPOINT`, `AWS_DEFAULT_REGION` | artifact S3 저장소. region 코드 기본값은 `us-east-1`; 해당 저장소 region을 명시해야 함 |
| `AWS_SHARED_CREDENTIALS_FILE` 또는 표준 AWS credential chain | S3 인증. RunPod job API key와 별개 |
| `MAPMAKER_JOB_TIMEOUT` | 기본 7200초, 허용 60..21600. local 대기+처리 시간과 job policy TTL/executionTimeout에 사용 |
| `MAPMAKER_MODEL_ROOT` | worker `/opt/mapmaker-models`; 미설정 시 repo root |
| `SAM3D_REPO`, `SAM3D_PYTHON`, `MAPMAKER_VISION_PYTHON`, `MAPMAKER_SAM3D_BASE` | 외부 source, 각 Python, base native 환경 |
| `MAPMAKER_SAM3D_CHECKPOINT`, `MAPMAKER_RAM_CHECKPOINT`, `MAPMAKER_SAM3_CHECKPOINT`, `MAPMAKER_DINO_PROVENANCE` | `runtime_paths.py`의 모델 파일 override |
| `TORCH_HOME`, `HF_HOME` | Docker에서 model root 아래 cache. `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` |
| `MAPMAKER_SCRATCH` | worker 임시 job 디렉터리; 기본 `/tmp/mapmaker-jobs` |

`remote_settings.load_settings()`는 `.runtime/runpod-settings.json`의 허용된 endpoint/storage/timeout 항목, `.runtime/runpod-api.key`, `.runtime/runpod-s3.credentials`를 읽고 **이미 설정한 환경 변수를 우선**한다. 현재 세 private 파일 존재와 `doctor`의 설정/credential 탐색 성공만 확인했다. 키 값은 출력하지 않았고 원격 인증 유효성은 재확인하지 않았다.

## 5. External Models and Dependencies

외부 모델 source는 이 Git 저장소에 vendored되어 있지 않다. Docker build가 pinned commit을 clone/install한다. 체크포인트는 image에 포함하지 않고 worker가 S3에서 가져온다.

| 의존성 | 용도 / source 및 checkpoint | 필수성·제약 |
|---|---|---|
| RAM++ | `recognize-anything`, commit `7cb804a8609e9f4b1a50b7f31436d2df40bb9481`; `/opt/ram`; `checkpoints/ram_plus_swin_large_14m.pth` | 자동 후보 생성에 필수 |
| SAM3 | `facebookresearch/sam3`, `2345a4ad109ac29c569da749c91d84f10dc08c40`; `/opt/sam3`; `sam3/sam3.pt` | mask 생성에 필수; 로컬 checkpoint 사용(`load_from_HF=False`) |
| SAM3D Objects | `facebookresearch/sam-3d-objects`, `f91db411c50efee93d8db7aeb323885650f6f722`; `/opt/sam3d`; `sam3d/pipeline.yaml` 및 다수 ckpt/yaml | 복원·pose·공식 조립 의존 필수 |
| DINOv2 | `facebookresearch/dinov2`, `7764ea0f912e53c92e82eb78a2a1631e92725fc8`; Torch Hub source 및 `dinov2_vitl14_reg4_pretrain.pth` | SAM3D 내부 feature 의존 및 provenance JSON 필수 |
| MoGe / BERT caches | manifest에 `Ruicheng/moge-vitl` model 및 `bert-base-uncased` tokenizer/config/ref 포함 | worker staging이 manifest 전체를 요구. 외부 source가 로컬에 없어 내부 호출 상세는 이번 조사에서 재검증 안 함. legacy `models.analyze`와 별도 구분 |
| Native libraries | PyTorch3D transforms, flash-attn, spconv, gsplat, kaolin 등 | 성공 freeze와 빌드 절차 보존 필요; 단순 `pip install mapmaker`로 준비되지 않음 |
| requests / boto3 / RunPod SDK | job API / authenticated S3 / worker handler | 원격 모드 필수; 로컬 GPU 모드에는 remote transport 불필요 |
| Three.js / Playwright | viewer / browser test | Three.js는 UI 필수, Playwright는 검증용 선택사항 |

`configs/serverless/model-storage.json`: **26파일, 21,385,172,187 bytes**. source bucket은 manifest의 `source_volume`이고 artifact bucket 설정과 구분된다. 각 파일 경로·원격 key·크기·SHA가 고정되어 있으며 `prepare_models`가 검사 후 `.part`를 rename한다. 같은 worker에서는 `READY` 상태와 파일을 재사용한다.

라이선스/접근 상태: `docs/runpod_serverless_migration.md`는 SAM3/SAM3D의 SAM License, RAM/DINO source의 Apache-2.0 및 RAM checkpoint 재배포 조건 추가 확인 필요를 기록한다. **이번에는 외부 license 원문이나 HF 계정 승인 상태를 재검증하지 않았다.** 배포 시 해당 모델 접근권한·조건을 별도 확인해야 한다. 현재 구현은 이미 보존된 모델의 authenticated S3 접근에 의존하며 새 HF 로그인/download를 수행하는 handler가 아니다.

## 6. Input / Output Contracts

### 입력과 API

- UI는 PNG/JPEG/WebP를 안내한다. 실제 backend는 MIME/확장자 allowlist 없이 Pillow로 decode 가능한 이미지 bytes를 받으며 EXIF 방향을 적용하고 RGB PNG로 저장한다.
- 웹 body 크기: `0 < Content-Length ≤ 25 * 1024 * 1024`; 위반 시 413, 잘못된 숫자는 400. pixel 수는 **16,000,000 이하**. CLI도 pixel 제한을 적용하지만 25 MB HTTP body 제한은 적용하지 않는다.
- `POST /api/runs`: **raw image body**, multipart/form-data나 JSON/base64가 아님. 성공 202 `{"run_id":"<32 lowercase hex>"}`. 생성 중이면 409, 이미지 처리 오류는 400.
- `GET /api/runs/<32hex>`: `run_id`, `status.json` 내용, `metadata` 반환. 없으면 404.
- `GET /runs/<32hex>/<path>`: 입력·artifact 파일. `/runs/<id>/scene.glb?download`는 attachment header를 붙인다.
- `GET /`, `/app.js`, `/style.css`, `/vendor/...`: frontend/static dependency serving. 별도 health, run 목록, cancel, delete API는 없다.
- CLI `--output`은 존재하지 않는 새 디렉터리여야 한다. remote 모드는 디렉터리 이름이 32자리 lowercase hex여야 하므로 보통 생략한다. local 모드의 임의 이름은 웹의 UUID 경로와 호환되지 않는다.

### Artifact 구조

```text
runs/<run_id>/
  input/source_image.png
  input/analysis_region_0.png ... analysis_region_4.png   # 큰 이미지의 tag용
  object_candidates.json
  masks/<object_id>.png                                 # 원본 크기, 0/255
  objects/<object_id>.glb
  objects/<object_id>.pose.json
  scene.glb
  scene_metadata.json
  status.json
  previews/masks.png
  previews/scene_posed.ply
  previews/combined_preview.png
  previews/combined_view_00.png ... _03.png / _06.png / _09.png
  previews/meshes/front_Z.png / top_Y.png / oblique.png
  logs/run.log / vision.log / segmentation.json / reconstruction.log / preview.log
  logs/reconstruction_result.json / sam3d_gpu.json
  logs/remote_job.json / runpod_timing.json / remote_integrity.json
```

실패 단계에 따라 일부 파일만 존재한다. `runpod_failure.json`, `remote_cancel.json`, `worker.log`, GPU 측정 및 model staging 기록은 조건부다. `artifact_validation.json`, `serverless_regression.json`, `web_validation.json`과 browser PNG는 검증 도구가 추가한 산출물로 모든 run에 보장되지 않는다.

`scene_metadata.json`에는 normalized input hash/size, 실제 tags, objects의 mask/asset hash·bbox·상태·native pose·적용 matrix, pipeline 정보, 구현 파일 hash, timings/errors, scene asset 경로가 들어간다. 실패 객체의 asset/pose는 없거나 일부만 있을 수 있다. SAM3D source revision 문자열은 코드에서 고정 기록하므로 그 문자열만으로 실제 외부 checkout 일치를 증명하지 않는다.

원격 저장소 key: `mapmaker-jobs/<run_id>/input.zip`, `progress.json`, `result.zip`. `/run` payload는 `protocol:1`, `run_id`, `input_sha256`; worker 결과는 `protocol`, `run_id`, `success`, `archive_sha256`, `scene_sha256`, `archive_bytes`다. mesh/base64를 job JSON에 넣지 않는다.

다운로드 ZIP은 archive SHA, run/input identity, 성공 GLB SHA, terminal 상태를 검사한다. 허용 root 파일/디렉터리, path traversal·symlink·중복 파일 거부 및 8 GiB 제한이 있다. **모든 파일을 배치한 뒤 `status.json`을 마지막에 교체**한다. 원격 `COMPLETED`만으로 로컬 성공을 선언하지 않는다.

## 7. Web Application Flow

- Frontend는 vanilla JS + ES modules/importmap + Three.js다. `web/node_modules`를 같은 Python 서버의 `/vendor/`에서 제공한다. Vite/React나 별도 dev server는 없다.
- `web.py` import 시 `PIPELINE`과 process-local `threading.Lock`인 `BUSY`를 생성한다. POST가 nonblocking acquire에 성공해야 run을 생성한다. 생성 실패 시 즉시 release, background thread는 성공/실패에 관계없이 `finally`에서 release한다. 추가 요청을 큐에 쌓지 않고 409를 반환한다.
- `status.json`은 새 run의 `queued`에서 시작하여 `analyzing → segmenting → segmented → loading → reconstructing → assembling → exporting → done` 또는 `failed`로 갱신된다. 원격 모델 staging도 `loading`을 사용하므로 단순한 단방향 단계 비율은 아니다. JSON은 임시 파일 후 replace로 저장하고 `status()` 호출은 `logs/run.log`에도 append한다.
- Worker는 2초 간격으로 변경된 progress를 S3에 게시하고 Windows는 기본 3초 간격으로 job/progress를 poll한다. progress 전송 실패는 job 자체를 실패시키지 않는다. 브라우저는 1.5초 간격으로 local API를 poll한다.
- 브라우저는 Generate/파일 선택을 비활성화하고 run ID를 `?run=<id>`에 넣는다. 새로고침하면 해당 run polling을 재개하며 새 job은 제출하지 않는다. localStorage/database 기반 generation state는 없다.
- RemotePipeline은 `logs/remote_job.json`에 job/endpoint ID를 저장한다. backend 재시작 시 미완료 run을 `failed`로 만들고 endpoint가 일치하면 cancel을 시도한다. 성공 여부는 `remote_cancel.json`에 남긴다. **자동 재개는 없다.** 이 recovery는 remote 모드에만 있다.
- Timeout/종료/비terminal 오류 시 cancel을 시도한다. POST 제출은 중복 GPU job 방지를 위해 자동 retry하지 않는다. polling 오류는 연속 5회째에 실패 처리한다. worker 내부도 process-local lock과 resident Pipeline을 사용한다.
- `done` 후 GLTFLoader가 독립 object node를 로드하고 OrbitControls로 orbit/zoom/pan을 제공한다. checkbox는 viewer node visibility만 변경한다. metalness/roughness 조정도 화면에만 적용하며 Export는 서버의 **전체 원본 생성 GLB**를 다운로드한다.

## 8. Verified Functionality

### 이번 조사에서 직접 수행한 안전한 검증

| 검증 | 결과 / 범위 |
|---|---|
| `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` (`PYTHONDONTWRITEBYTECODE=1`) | **50 passed, 4.11초**. mock remote 전송/실패/lock/재시작/ZIP/model cache/path와 legacy CPU geometry 포함. 실제 GPU/S3 E2E 테스트가 아님 |
| `node --check web/app.js` | 통과. browser rendering 검증 아님 |
| `python -m mapmaker.cli doctor` | endpoint/API key/S3 bucket/credential 탐색/Web dependencies OK. 네트워크 인증·모델 실행은 검사하지 않음 |
| 성공 run 5개의 `scene.glb` SHA 재계산 | 각 저장된 `remote_integrity.json.scene_sha256`와 일치 |
| `65db3225cab34978868d888c014268d7` read-only artifact 검사 | 6객체 mask 크기/0·255 값, mask·object GLB hash, scene node 존재·metadata matrix 일치 확인. inference나 preview 재생성 없음 |

### 현재 디스크에서 확인한 실제 성공 산출물

다음 모두 `status=done`, metadata errors 빈 배열, GLB 존재, 저장된 `remote_integrity.verified=true`, `artifact_validation.passed=true`다. 이는 **이전 실제 실행의 결과를 이번에 확인**한 것이며 새 추론 성공 주장이 아니다.

| `runs/` 하위 ID | 입력 / GPU / 결과 |
|---|---|
| `83b8a7a8fde840bf81abcff40ef25c82` | 거실 1280×854 / A40 / 6객체 |
| `2e58128c189949f0a959803306afc83f` | 도시 275×183 / A40 warm / `city_00`, `lush_00`, `coast_00` 3객체 |
| `5614756e06bd4580a2e432d9198b8be3` | 거실 1280×854 / RTX 6000 Ada / 6객체 |
| `a0d1b9737bd14b99ac8abf7002688ef5` | 거실 1280×854 / A100-SXM4-80GB / 6객체 |
| `65db3225cab34978868d888c014268d7` | 용량 초과 후 거실 재시도 1280×854 / RTX 6000 Ada / 6객체 |

거실 객체는 loveseat, cabinet, coffee_table, television, plant, book이다. 원격 전송 후 로컬 GLB/객체/mask/preview/로그까지 저장되어 있다. 도시의 `lush` 같은 label도 실제 결과이며 semantic filtering이 완전하다는 근거는 아니다.

첫 4건의 세부 GPU/timing/regression은 `docs/runpod_serverless_validation.json`과 각 run logs에 있다. 기록된 A100 비교는 mask IoU 1.0, translation 차이 0, scale ratio 1.0이다. A40/Ada에는 작은 차이가 있으므로 GPU 간 bitwise 동일성을 주장하지 않는다. A40 실행은 이전 image + interpreter fix override, Ada/A100은 최종 image로 기록되어 있다.

Browser 성공 근거는 위 JSON의 room/city rendering, visibility off/on, download event 및 migration 문서다. 기존 Linux의 sofa/apple/전체 Chromium orbit·zoom·pan·download hash 검증은 `docs/sam3d_project_validation.md`의 **과거 기록**이다. 기존 문서의 두 UUID run 및 `experiments/`는 현 Windows root에 없다. `.runtime/reference-living-room`은 복구 reference로 존재하나 일반 run의 `status.json`은 없으므로 완전한 현행 run으로 취급하지 않는다.

## 9. Known Issues / Limitations

| 구분 | 확인한 내용 / 근거 |
|---|---|
| 알려진 실패 및 회복 | `e5b4b3d530a7474a98dd71f312b7eb66/logs/runpod_failure.json`: S3 `QuotaExceeded`, scene 로컬 미회수. 이후 `65db...` 성공 artifact 확인. migration 문서에는 volume 500→550 GB 증설 기록이 있으나 현재 원격 용량/잔량은 조회하지 않음 |
| 저장소 관리 미구현 | 코드에 S3 job artifact 자동 삭제/수명 관리 없음. 모델 약 21.4 GB와 결과 ZIP이 저장공간을 사용함. Upload 실패 시 worker 진단 ZIP도 회수 못하고 handler 종료 시 scratch가 정리됨 |
| Cold start | 저장된 기록상 모델 staging 약 197~649초, image pull은 추가. worker 종료 후 다시 다운로드할 수 있음. warm SAM3D 재사용은 worker 수명 내에서만 유효 |
| 제한된 concurrency | 웹 lock과 worker lock은 각각 프로세스 내부만 보호. 다중 local backend/CLI 전체를 묶는 shared lock은 없음. 다중 프로세스 운영 E2E 미검증 |
| 브라우저 polling 일부 구현 | fetch/GLB load 오류도 UI `failed`로 표시하고 polling을 멈춘다. 이때 backend job 취소는 하지 않는다. URL 새로고침으로 다시 관찰 가능; UI 실패 문구만으로 원격 종료를 판단하지 말 것 |
| Restart 처리 | remote는 미완료 run 실패 처리+cancel 시도만 지원. local GPU Pipeline에는 `recover_interrupted`가 없고 worker result 기다림의 별도 timeout도 없음 |
| 인증 미구현 | HTTP API/static/artifact에 내장 사용자 인증 없음. Windows는 localhost 기본, shell launcher는 `0.0.0.0:8082` 기본 |
| 입력/품질 한계 | 25 MiB 웹/16 MP 제한, 40후보·12객체 상한, deterministic semantic/면적 필터. 실제 room/city 검증을 모든 이미지 품질로 확대할 수 없음 |
| CPU preview 한계 | `scene_preview.py`는 orthographic painter 방식과 triangle 중심 UV 색을 사용한다. 원본 카메라 정합·세밀한 texture 품질 검증용이 아니며 `render_note.json`에 이를 기록함 |
| 환경 의존 | Windows 로컬 GPU 모델 환경/체크포인트 부재. 외부 repo/native ABI/model manifest 및 private S3/API에 의존 |
| stale 문서 | `docs/PROJECT_CURRENT_STATE.md`의 `/workspace/MapMaker`·48 tests와 migration의 47 tests는 당시 기록. 현행 테스트는 50개. 기존 README CLI 임의 `--output` 예시는 remote에 그대로 적용 불가 |

**현재 검증 불가/미수행:** live endpoint 상태·배포 digest·GPU pool/요금·volume 여유 공간·S3 접근권한·HF 승인·새 Docker build·Linux 직접 실행·GPU 신규 추론·browser 신규 E2E. 배포 identity `8a0bcaa35` 및 endpoint 정보는 저장된 기록이며 HEAD `94c7b16`이 원격에 배포되었다고 가정하지 않는다. 비용/대용량 다운로드/외부 상태 변경 없이 로컬 근거 조사만 수행했다.

## 10. Current Development Status

| 상태 | 현재 범위 |
|---|---|
| 구현 완료, 명시된 범위에서 검증 | 이미지 정규화, remote protocol/무결성·실패 처리 CPU 테스트; 저장된 room/city의 extraction→SAM3D→scene→로컬 반환 |
| 동작하지만 검증 범위 제한 | 3종 GPU·2종 입력의 원격 생성, Three.js 표시/visibility/download 기존 기록, warm worker 재사용 |
| 구현 존재 / 이번 E2E 미검증 | Linux local GPU mode, Docker 재빌드, 새 환경 bootstrap, 전체 browser E2E |
| 일부 구현 | progress 전달은 best effort; cancel도 best effort; browser network 복구는 refresh 의존; 일부 object 실패 허용 |
| 현재 사용하지 않음 / legacy | MoGe depth·Gen3C video·Hunyuan 및 이전 `pipeline.py` 기반 scene 구성 |
| 실험용 / 진단용 | `scripts/sam3d_smoke.py`, `sam3d_regression.py`, inspect/compare 도구 및 과거 benchmark 문서. 현행 앱 entrypoint가 아님 |
| 미구현 | 구조물/배경 복원, 편집 기능, auth, shared multi-process orchestration, 중단 job resume, artifact lifecycle |

Git 최근 흐름은 Windows orchestration/worker deployment → 이미지 cache 제외 및 venv interpreter fix → browser run 복원 → GPU 검증 기록 → HEAD의 quota 오류 설명/회복 기록이다. 구현 변경 없이 현재 문서만 작성했으며 remote image와 local HEAD를 같은 revision으로 간주하지 않는다.

## 11. How to Run

### 이미 준비된 현재 Windows checkout

```powershell
cd D:\MapMaker
.venv\Scripts\python.exe -m mapmaker.cli doctor
powershell -ExecutionPolicy Bypass -File scripts/start_scene_web.ps1
```

`http://127.0.0.1:8082`를 연다. 포트 변경은 launcher `-Port 8083`. 별도 frontend 실행은 필요 없고 backend를 생성 완료까지 유지한다. 시작 시 remote interrupted-run recovery가 작동하므로 서버 시작은 단순 read-only 점검 명령이 아니다.

### 새 Windows checkout 준비 — 이번에 재설치하지 않음

`pyproject.toml`, package lock 및 실제 설정 스크립트에 근거한 절차:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -e '.[remote]'
npm.cmd ci --prefix web
powershell -ExecutionPolicy Bypass -File scripts/configure_runpod_api.ps1
powershell -ExecutionPolicy Bypass -File scripts/configure_runpod_s3.ps1
$env:RUNPOD_ENDPOINT_ID = '<deployed-endpoint-id>'
$env:MAPMAKER_S3_BUCKET = '<artifact-bucket>'
$env:MAPMAKER_S3_ENDPOINT = '<S3-endpoint-URL>'
$env:AWS_DEFAULT_REGION = '<storage-region>'
.venv\Scripts\python.exe -m mapmaker.cli doctor
powershell -ExecutionPolicy Bypass -File scripts/start_scene_web.ps1
```

대안은 허용 설정을 `.runtime/runpod-settings.json`에 저장하는 것이다. credential 설정 스크립트는 인증 파일을 **작성**하므로 이미 구성된 checkout에서 점검 목적으로 재실행하지 않는다. 별도로 모델 manifest에 접근 가능한 endpoint/worker가 배포되어 있어야 한다. 위 절차만으로 원격 인프라를 만들지는 않는다.

### CLI / 검증

```powershell
# 비용이 발생할 수 있는 실제 remote generation; 새 UUID run 생성
.venv\Scripts\python.exe -m mapmaker.cli run samples/living_room.jpg

# 안전한 CPU 테스트; pytest는 pyproject 의존성에 별도 선언되어 있지 않음
$env:PYTHONDONTWRITEBYTECODE = '1'
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
node --check web/app.js

# 기존 artifact 검사: 아래 두 명령은 logs에 보고서를 작성함
.venv\Scripts\python.exe scripts/validate_scene_run.py runs/<run_id>
.venv\Scripts\python.exe scripts/compare_serverless_run.py .runtime/reference-living-room runs/<run_id>

# CPU preview 재생성: 출력 파일을 작성함
.venv\Scripts\python.exe -m mapmaker.cli render runs/<run_id>/scene.glb --output <new-preview-directory>
```

`validate_scene_run.py --reference`는 과거 benchmark의 `input/rgb.png`, `segmentation/method.json` 레이아웃용이다. production-format reference 비교에는 `compare_serverless_run.py`를 사용한다. 두 검사 스크립트 모두 보고서를 쓰므로 이번 read-only 재검사는 별도 in-memory 검사로 수행했다.

Browser E2E는 실행 중인 backend, Playwright Chromium이 필요하다. `web` 디렉터리에서 `node e2e.mjs <absolute-image-path>`를 실행한다. 기본 입력 경로는 현재 없는 `experiments/...`이므로 반드시 입력을 지정한다. 기본 실행은 새 GPU job을 제출한다. `RESUME_RUN=<existing-id>` 환경 변수로 기존 run 관찰 경로를 선택할 수 있으나 이때도 보고서/스크린샷을 작성한다.

### Worker / Linux local

```bash
# Linux amd64 Docker build; 무거운 native build이며 이번에는 미실행
docker build --platform linux/amd64 -f deploy/runpod/Dockerfile .

# 별도 GPU/모델 환경이 준비된 Linux checkout에서만
MAPMAKER_BACKEND=local bash scripts/start_scene_web.sh
# localhost로 제한하려면 --host 127.0.0.1 추가
```

Docker entrypoint는 `/opt/mapmaker/.venv/bin/python -m mapmaker.serverless_worker`. endpoint에 artifact S3 설정·credential과 manifest source bucket 읽기 권한이 필요하다. 모델 파일은 worker 시작 job에서 manifest 경로로 내려받으므로 image에 수동 checkpoint를 넣지 않는다.

기존 Linux fallback 경로는 `runtime_paths.py` 기준 `experiments/image_first_scene_object_benchmark/model_setup/sam3d_objects/repo/checkpoints/hf/pipeline.yaml`, `.venv-vision/bin/python`, `.venv-sam3d/bin/python`, SAM3D base `.../sam3d_objects/env`, RAM checkpoint 및 repo 부모 `.cache/huggingface/.../sam3.pt`다. DINO source/weights/provenance도 필요하다. 현 Windows에는 없으므로 바로 실행 가능하다고 보장하지 않는다. 세부 복구는 `docs/sam3d_runtime_recovery.md`와 `scripts/recover_sam3d_runtime.sh`, `sam3d_runtime_env.sh`를 읽고 수행한다; 복구 스크립트는 단순 조회 도구가 아니다.

## 12. Handoff Notes

1. 이 문서 → `scene_pipeline.py` → `scene_remote.py`/`serverless_worker.py` → `scene_vision.py` → `scene_reconstruct.py`/`scene_assembly.py` → `web.py`/`web/app.js` 순으로 읽는다. 배포 작업은 `runtime_paths.py`, Dockerfile, manifests/freeze를 함께 읽는다.
2. 현재 Windows 흐름을 기준으로 작업한다. `scene_pipeline.Pipeline`은 현행 local/worker 코드이고 `pipeline.Pipeline`은 이전 접근이다. legacy 테스트 통과를 SAM3D 실행 성공으로 보고하지 않는다.
3. 독립 root node 이름·native pose·축 변환·metadata 계약을 유지한다. placement 변경 시 공식 point transform와 GLB 재로드, 기존 room regression을 다시 검사한다.
4. `.runtime` credential, reference, `runs` 성공·실패 근거, 외부 model storage를 함부로 삭제하지 않는다. Linux 환경의 SAM3D base/native libs는 venv의 일부 의존성이므로 venv 폴더만 보존해서는 부족하다.
5. Vision Python symlink를 `resolve()`하지 않는다. base Python으로 실행되어 packages가 사라졌던 실패 근거와 `tests/test_runtime_paths.py` 회귀 테스트가 있다.
6. 새 작업에서 `doctor OK`를 원격 인증/추론 검증으로 해석하지 않는다. endpoint 실제 image revision·S3 공간/권한·모델 hash/접근은 필요한 작업 시 별도 확인한다. image의 `HF_*_OFFLINE` 설정 때문에 누락 cache가 온라인 fallback으로 해결되지 않는다.
7. Generation state 변경 시 duplicate 409, 모든 실패 경로의 lock 해제, restart cancellation, URL 복원, progress 유실, `done` 최종 게시 순서를 재검증한다. 단일 process lock의 범위를 넘기는 배포에는 추가 검증이 필요하다.
8. 문서와 저장된 GPU/브라우저 evidence, 이번 CPU/artifact 재검사, 아직 미실행인 항목을 계속 구분한다. 새 model inference/대량 artifact 생성 없이 확인할 수 없는 항목은 미검증으로 남긴다.
