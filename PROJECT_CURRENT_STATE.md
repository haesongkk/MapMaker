# PROJECT CURRENT STATE — SAM3D Scene Studio

최신 업데이트: 2026-09-29, Windows `D:\MapMaker`. 시작 HEAD는
`476a8a4d64b5c3a9f8e53559e5ff04ac22e2d5dc`이며 기존 README 변경, untracked samples 및
샘플 검증 스크립트/테스트는 보존했다. 아래 최신 절이 과거 기록보다 우선한다.

## 최신: placement correction + floor

- 이미지 → RAM++ → SAM3 → SAM3D 객체 GLB/pose → 공식 scene assembly 경로는 유지한다.
- `scene_placement.py`는 공식 조립 후 CPU에서 실행한다. GLB/Three.js world +Y를 사용하며
  기존 `native_row.T @ inverse_export` matrix와 child/node transform을 그대로 존중한다.
  local vertex나 pivot을 다시 정규화하지 않는다. pose 원본 파일도 수정하지 않는다.
- 실제 문제: 가구 world bbox 최저점이 서로 달랐고 바닥 접촉 제약/geometry가 없었다.
  기존 공식 좌표 검증은 통과한 상태다. 이번 조사에서 축 변환/중복 transform 오류를 입증하지 못했다.
  공통 카메라 기울기와 SAM3D 자체 orientation 오류는 여전히 남는다.
- 확실한 가구 이름 whitelist의 최저점 중앙값을 floor_y로 잡는다. world bbox는 모든 descendant
  geometry instance의 전체 transform을 적용한 모든 vertex에서 계산한다.
  `delta_y = floor_y - bbox_min_y`; 높이 50%를 넘는 보정은 skip한다.
  XZ, rotation, scale은 불변. 소품 whitelist + footprint 겹침 + 수직 범위로 지지 가구가
  정확히 하나인 경우 그 가구의 delta_y만 따라간다. 새 위치로 snap하지 않는다.
- 메타데이터에 원본 matrix, local/world bbox, 최저/최고점, 중심, bottom center, 이동량,
  skip 이유, 지지 객체 및 before/after metric을 기록한다. 최종 GLB 재로드로 bbox/matrix를 검증한다.
- 바닥: 지지 가구 footprint(없으면 전체 scene) + 각 변 15% margin, scene scale의 0.5% 두께.
  slab 위쪽이 정확히 floor_y. 별도 `background_floor` node이고 기존 객체를 제거하지 않는다.
- Local `Pipeline.run`은 reconstruct 후 보정하고 mesh preview를 만든다. 원격 경로는
  `materialize(..., finalize=finalize_scene)`에서 archive/input/원본 GLB hash 검증 후,
  staging 내부에서 보정/preview를 완료한 다음 status를 마지막에 게시한다.
  새/기존 worker 모두 지원하며 version+최종 hash 검사로 이중 보정을 방지한다.
  원격 worker/endpoint/image는 변경하거나 배포하지 않았다.
- `previews/meshes`는 최종 scene 기준. CPU painter의 큰 바닥 삼각형 occlusion 오류는
  backdrop 우선 그리기로 수정했다. 정밀한 depth 판단은 WebGL이 기준이다.
  Gaussian PNG/PLY는 공식 원래 pose를 보존하며 바닥이 없다는 점을 metadata에 명시한다.
- MakeYourBrick 실제 조사: `mesh/orient.py`의 longest-axis 추정(1.2 dominance)과 명시적 Y-up 회전,
  `mesh/inspect.py`의 transform을 포함한 Scene flatten/finite bounds 검사를 확인했다.
  bbox/transform 검사 방식을 참고했지만 소파의 긴 축을 세우는 오류를 피하려고 auto orientation은
  포팅하지 않았다. 직접 복사한 upstream 코드는 없다. source 링크는 검증 보고서에 있다.
- 벽, 새 모델, physics/collision solver, PCA/자동 방향 추론은 의도적으로 제외. 추가 dependency 없음.

## 최신 검증 범위

- CPU 회귀 46 passed; 기존 공식 assembly 축 검증 테스트도 통과. 새 테스트는 nested node/shared
  instance, 비균일 scale/회전/pivot bbox, floor contact, outlier skip, 소품 이동, floor GLB,
  idempotence/hash, 원격 검증/게시 순서와 실패 원자성을 검사한다.
- 거실/식당/침실의 저장된 실제 SAM3D 결과 3개를 CPU 재처리했다. 30/30 객체 mesh·pose·mask·입력은
  보존, 회전/scale/XZ 불변. 선정한 가구 16개에서 추정 floor 기준 floating 7→0, penetration 7→0.
  이는 실제 이미지 바닥 ground truth 평가가 아니며 category 밖 객체의 floating을 포함하지 않는다.
- Before는 기존 inference artifact 복사 + 현재 CPU preview 재실행이다. After는 같은 mesh/pose의
  실제 새 GLB/preview 생성이다. 새 이미지→GPU 전체 inference E2E는 이번 환경에서 실행하지 않았다.
  Windows에는 GPU 모델 환경이 없고 셸 외부 연결/Chromium 실행 제한이 있어 추가 자원 설정을 하지 않았다.
- 3개 scene의 artifact validator, 실제 HTTP 다운로드 hash 검사가 통과했다.
  앱 내 브라우저로 before/after 3개 scene을 열고 floor/객체를 확인했다.
  세부 UI 검증 결과/미검증 범위와 screenshot은 `docs/placement_validation.md` 및
  `runs/placement_validation/`에 기록한다.
- 품질 한계: camera tilt와 잘못된 canonical orientation을 유지하므로 모든 다리가 바닥에 닿는 것은
  아니다. 식물/벽 장식은 보수적으로 제외. large AABB overlap은 식당에서 6→7쌍으로 증가했다
  (table/chair 빈 공간도 포함하는 proxy); 충돌 해결/전반적인 품질 개선을 주장하지 않는다.

커밋은 `.git/index.lock` 쓰기 권한 제한으로 생성하지 못했다. 사용자 추가 승인 없이
변경 파일과 `runs/placement_validation/changes.patch`를 보존했다. push 없음.

상세 결과와 재실행 방법: [placement validation](docs/placement_validation.md).

---

# 이전 상태 기록 — 2026-09-28 (아래 내용은 보정 도입 전)

조사·정리 기준: 2026-09-28, Windows `D:\MapMaker`. 실제 import/call graph, subprocess/CLI entrypoint, Docker, scripts/tests/frontend, 고정 upstream source와 S3 model YAML을 교차 확인했다. 기존 작업 tree는 깨끗했다. 실행 절차는 [README](README.md), 배포·복구는 [runtime guide](docs/runtime.md)가 담당한다.

## 1. 제품과 현행 실행 경로

```text
Browser image → local create_run → S3 input.zip → RunPod /run
  → model staging → RAM++ → SAM3 masks → resident SAM3D mesh + pose
  → independent object nodes → scene.glb + previews → S3 result.zip
  → local archive/input/GLB integrity verification → status done → Three.js
```

Windows 기본 backend는 `runpod`, Linux는 `local`이며 `MAPMAKER_BACKEND`로 선택한다. Worker는 `scene_pipeline.Pipeline`을 직접 실행한다. Local GPU 모드는 Linux의 준비된 모델 환경에서만 가능하다. Windows checkout에는 모델/외부 source/GPU venv가 없다.

현행 기능: 이미지 EXIF 정규화와 RGB PNG, 실제 RAM++ 후보 추출, SAM3 instance segmentation, SAM3D 객체별 mesh/pose, 일부 객체 실패 허용, 독립 node 조립, RunPod/S3 전송, 무결성 검사, progress/status, 실패·timeout·cancel 처리, 중복 생성 거부, backend restart 처리, Three.js viewer, visibility toggle, 기존 run URL 복원과 GLB 다운로드.

이번 정리는 모델·입력 해상도·seed·후보/segmentation 알고리즘·좌표계·pose heuristic·API·artifact·RunPod protocol을 변경하지 않았다. RAM++ 함수는 `scene_vision.py`로 이동했고 AST 동일성을 확인했다. `implementation_sha256`과 extraction의 `code` provenance 값은 이동한 실제 코드 위치를 기록한다.

## 2. 코드 책임과 구조

| 경로 | 책임 |
|---|---|
| `mapmaker/cli.py`, `web.py` | CLI/HTTP 진입점. `serve()` lifecycle은 web 모듈 하나에서 관리 |
| `scene_pipeline.py`, `scene_run.py` | run 생성, 별도 vision subprocess, resident reconstruction subprocess, JSON/status/log |
| `scene_remote.py`, `remote_settings.py` | RunPod submit/poll/cancel/restart, private 설정 우선순위 |
| `scene_transfer.py` | S3 스트리밍, ZIP safety, archive/input/scene hash, 검증 후 materialization |
| `serverless_worker.py`, `model_cache.py`, `gpu_measurement.py` | worker handler, 모델 staging, 원격 progress publication, GPU 측정 |
| `scene_vision.py`, `object_candidates.py` | RAM++ tag 추출, 후보 필터, SAM3 원본 해상도 mask |
| `scene_reconstruct.py`, `scene_assembly.py`, `scene_preview.py` | 공식 Inference, native pose, GLB node 조립, Gaussian/CPU preview |
| `runtime_paths.py` | code/model/source/interpreter 경로. Python venv symlink 보존 |
| `web/` | vanilla JS + Three.js; Playwright는 devDependency; build server 없음 |
| `configs/serverless/`, `configs/sam3d/` | 고정 source revisions, model manifest, ABI별 overlay/conda/freeze |
| `deploy/runpod/` | Linux amd64 multi-stage Docker build와 pinned source 설치 |
| `scripts/` | runtime/deployment/recovery 및 production-format artifact 검증 |
| `tests/` | CPU contracts 및 mocked remote/network/GPU dependency 회귀 |
| `samples/` | 샘플과 attribution |
| `.runtime/`, `runs/` | ignored private 설정·reference·실제 GPU 산출물·검증 evidence |

## 3. 유지한 production contract

- RAM++: 입력 크기 384, threshold 배율 0.75. 원본 긴 변이 768 초과면 tag용 60% 겹침 crop 5개를 추가한다. SAM3/SAM3D는 원본 전체 이미지를 받는다.
- 후보 최대 40, mask 최대 12. Confidence ≥0.6, area ≥0.003, IoU >0.8 또는 90% 초과 포함 mask 제외. 공통 alias/filter와 정렬은 변경하지 않았다.
- SAM3D: 공식 notebook `Inference`, `compile=False`, `seed=42`. Warm worker가 모델을 재사용한다. 전부 실패하면 run 실패; 일부 실패는 성공 객체로 계속한다.
- GLB column-vector matrix: `official_native_row.T @ E4`, `E=[[1,0,0],[0,0,-1],[0,1,0]]`. 각 객체는 독립 root이고 mesh는 child node다.
- 실제 조립 시 공식 `SceneVisualizer.object_pointcloud`와 최대 오차 `1e-5` 이하 검사, GLB 재로드 matrix `atol=1e-6` 검사. Gaussian preview normalization은 GLB에 적용하지 않는다.
- `POST /api/runs`: raw image bytes, 25 MiB/16MP 제한, 성공 202 + 32 hex run_id, 중복 409. `GET /api/runs/<id>`는 status/metadata. `GET /runs/<id>/scene.glb?download`는 전체 scene 다운로드.
- RunPod input: protocol 1, run_id, input_sha256. Output: run_id, success, archive_sha256, scene_sha256, archive_bytes. 대형 결과는 S3 ZIP으로 전달한다.
- ZIP: 허용 root/path, traversal·symlink·duplicate 거부, expanded size 최대 8 GiB. 모든 파일을 배치한 후 status.json을 마지막에 publish한다.
- Submit 모호한 오류는 자동 재시도하지 않는다. Poll transient 실패는 제한적으로 재시도. Timeout/interruption은 cancel 시도. Backend restart는 미완료 remote run 실패 처리와 cancel 시도만 한다.

## 4. 의존성 및 model manifest 판단

CPU/orchestrator 직접 dependency는 NumPy, Pillow, trimesh, Typer다. Remote extra는 requests/boto3, serverless extra는 boto3/RunPod SDK다. pytest는 dev group에 선언했다. `uv.lock`은 해당 구성으로 갱신했으며 기존 package를 임의 upgrade하지 않았다. 로컬 sync는 기존 lock의 NumPy 1.26.4를 적용했다. npm은 Three.js 0.180.0 / Playwright 1.55.1로 변경하지 않았다.

OpenCV, SciPy, Numba, imageio, imageio-ffmpeg의 **orchestrator 직접 dependency**와 전이 llvmlite를 제거했다. SAM3D/vision에서 필요한 동명 package는 각 GPU 환경의 frozen 명세에 그대로 있다. 특히 Gaussian PNG의 imageio는 SAM3D subprocess에서 사용한다.

| 모델/외부 source | 현재 필요한 이유 |
|---|---|
| RAM++ recognize-anything | `scene_vision.ram_tags`; tag 추출과 package data |
| SAM3 | image builder/processor, checkpoint 기반 instance segmentation |
| SAM3D Objects | 공식 `Inference`, compose_transform, SceneVisualizer, Gaussian preview 및 native postprocessing |
| DINOv2 | ss/slat generator YAML의 `Dino(dinov2_vitl14_reg)` feature embedder; Torch Hub source/weights |
| MoGe v1 + `Ruicheng/moge-vitl` cache | 실제 staged pipeline.yaml의 depth_model → PointMap pipeline `compute_pointmap()` 호출 |
| BERT cache | RAM++ constructor → `init_tokenizer` → `BertTokenizer.from_pretrained('bert-base-uncased')` |
| PyTorch3D / flash-attn / spconv / gsplat / kaolin / utils3d | 공식 transforms, attention, sparse convolution, Gaussian/mesh 처리; ABI와 pinned source 유지 |
| RunPod / authenticated S3 | 원격 GPU 실행, input/result/progress 및 model storage |

외부 source checkout 4개는 full history clone에서 **고정 commit depth-1 fetch**로 축소했다. 버전 값은 `source-revisions.json`을 사용한다. 4개 repo 모두 실제 fetch/checkout에서 revision 일치와 commit count=1을 확인했다. Editable/package-data/notebook/Torch Hub 경로 때문에 source tree 자체는 유지하며 vendoring하지 않았다.

Model manifest: **24파일, 21,385,171,688 bytes**. 제거한 `ss_encoder.yaml`(231B), `slat_encoder.yaml`(268B)은 pipeline/generator config에 참조가 없다. 공식 base pipeline의 ss encoder는 checkpoint가 있을 때만 초기화하며 현재 checkpoint/config argument가 없다. slat encoder는 해당 inference constructor 경로에 없다. 두 Gaussian decoder는 초기화 시 모두 로드되므로 보존했다. Pipeline YAML 자체와 모든 checkpoint/hash/S3 key는 그대로다. 모델 절감량은 499B이며 cold download 비용이 실질적으로 감소했다고 주장하지 않는다.

조사 근거: 고정 [SAM3D pipeline](https://github.com/facebookresearch/sam-3d-objects/blob/f91db411c50efee93d8db7aeb323885650f6f722/sam3d_objects/pipeline/inference_pipeline.py), [PointMap](https://github.com/facebookresearch/sam-3d-objects/blob/f91db411c50efee93d8db7aeb323885650f6f722/sam3d_objects/pipeline/inference_pipeline_pointmap.py), [RAM++](https://github.com/xinyu1205/recognize-anything/blob/7cb804a8609e9f4b1a50b7f31436d2df40bb9481/ram/models/ram_plus.py), [tokenizer](https://github.com/xinyu1205/recognize-anything/blob/7cb804a8609e9f4b1a50b7f31436d2df40bb9481/ram/models/utils.py)와 manifest source bucket에서 hash가 고정된 실제 YAML을 읽었다.

## 5. 정리 범위와 scripts 전수 분류

삭제 코드: 이전 `pipeline`, `assembly`, `reconstruction`, `geometry`, `gen3c_intrinsics`, `gen3c_patch`, `moge_worker`, `model_worker`, 혼합 `models`, 전용 `raster`, `standalone_render`, `validation`, `common` 총 13개 모듈. 현행 import/subprocess/CLI 경로는 이들을 참조하지 않는다. 혼합 models의 RAM++만 현행 vision으로 이동했다.

삭제 테스트: `test_pipeline.py`, `test_raster.py`, `test_gen3c_path.py`의 레거시 전용 20 case. 레거시를 보존하기 위해 이 테스트를 유지하지 않았다. 현행 remote/path 30 case를 보존하고 정규화/독립 node/좌표 mismatch/게시 순서/cache corruption 5 case를 추가했다.

| scripts | 분류 / 처리 |
|---|---|
| `run_sam3d_worker.sh`, `sam3d_runtime_env.sh` | production runtime 필수: 유지 |
| `start_scene_web.ps1`, `start_scene_web.sh` | OS별 실행 진입점: 유지 |
| `configure_runpod_api.ps1`, `configure_runpod_s3.ps1` | private deployment 설정: 유지 |
| `sam3d_runtime_audit.py` | Docker build 및 recovery 버전 검사: 유지 |
| `recover_sam3d_runtime.sh`, `build_sam3d_native.sh` | Linux repair/native build: 유지; 본체 checkpoint override 지원 |
| `recover_dinov2.py` | 필수 auxiliary cache 복구: 유지; TORCH_HOME/model root override 반영 |
| `sam3d_checkpoint_preflight.py` | recovery/model path 검증: 유지; worker checkpoint layout 지원 |
| `sam3d_file_audit.py`, `sam3d_smoke.py`, `sam3d_dino_smoke.py` | 설치 완전성/native GPU/feature smoke: 유지; 실제 Linux 환경 필요 |
| `validate_scene_run.py`, `compare_serverless_run.py` | production artifact/pose/mask reference 검증: 유지; 과거 benchmark 전용 comparison branch를 현행 compare 함수로 통합 |
| `compare_scene.py`, `inspect_scene.py`, `inspect_generated.py` | 이전 scene.json/camera/mesh-audit schema 전용: 삭제 |
| `rebuild_sample.py` | 삭제된 CLI step/Gen3C/Hunyuan 호출: 실행 불가능하므로 삭제 |
| `sam3d_regression.py` | 없는 benchmark 원본/고정 sofa/과거 load JSON에 결합: 삭제; 현행 run generation + production reference 비교로 대체 |

문서: 과거 Linux investigation/validation, InSpace, depth/video pipeline, 중복 상태 및 migration 문서 7개를 삭제하고 README + 이 문서 + docs/runtime.md로 역할을 통합했다. `docs/runpod_serverless_validation.json`은 기존 실제 GPU evidence를 보존하고 이번 검증을 `cleanup_validation`에 추가했다. 과거 evidence의 implementation path는 당시 기록이며 현행 안내가 아니다.

Ignored/untracked: `.runtime` private credential 3종, endpoint 설정, `.runtime/reference-living-room`, 기존 성공/실패 run 전체와 GPU evidence JSON은 보존했다. pytest/프로젝트 bytecode cache, stale S3 probe, 과거 OpenAPI snapshot, 일회용 collect_validation.py를 제거했다. `.venv`는 lock으로 sync하여 불필요한 package를 제거했다. Three.js node_modules, 현재 Playwright browser 설치, 이번 검증 보고서는 실행/회귀에 필요하여 유지한다.

## 6. 이번 검증과 근거

- CPU: `PYTHONDONTWRITEBYTECODE=1 .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` → **35 passed**. 실제 GPU 라이브러리 호출은 CPU 테스트에서 double을 사용한다. 공식 수치 비교는 GPU assembly가 수행한다.
- Syntax/import: `node --check web/app.js`, `node --check web/e2e.mjs`; retained Python AST parsing; CLI help 및 doctor 통과. doctor는 설정 존재만 확인한다.
- Dependencies: `uv sync --frozen --extra remote`, `uv lock --check --offline` 통과. 제거한 직접 dependency가 없는 환경에서 CPU 검증했다.
- Artifact regression: 기존 `65db3225cab34978868d888c014268d7`와 새 `bdb87bacea354d3db4965630840dd9fb`의 6개 object GLB/masks/node/matrix/preview 검증 통과. 새 run은 같은 GPU의 기존 결과와 mask IoU 1.0, translation 차이 0, scale 비율 1, 최대 rotation 차이 0.00000171°. Mesh extent 최대 상대 차이는 0.02957%이며 bitwise 동일성은 주장하지 않는다. 보존 reference 대비 최소 mask IoU 0.999565, 최대 rotation 차이 0.341877°, translation 차이 0.005383; 누락/추가 객체와 오류가 없다.
- Browser: 기존 run과 새 GPU run 모두 `RESUME_RUN=<id> node web/e2e.mjs` 통과. 실제 URL restore, status, WebGL, 6개 toggle, orbit/zoom/pan, 다운로드 SHA 일치, page errors 0. 새 run screenshot도 직접 확인했다. 이번 browser 검증은 완료 결과의 URL 복원부터 수행했으며 신규 업로드→HTTP submit 전체를 한 browser 세션에서 재실행하지 않았다.
- Build: 모든 shell script Bash syntax 검사 통과. Docker executable/daemon이 없어 전체 image/native rebuild는 미검증이다. 기존 image의 native environments를 사용하는 worker source overlay 검증과 Docker rebuild를 혼동하지 않는다.
- GPU: 승인 후 기존 endpoint `8dzbkfrxys43hb`의 시작 명령을 일시 변경하여 실제 RTX 6000 Ada에서 실행했다. Job `c5d30746-ac3d-464b-82d0-42f08f42f724-u1`, run `bdb87bacea354d3db4965630840dd9fb`: COMPLETED, 6/6 객체, 오류 0, archive/input/scene 무결성 통과. Pipeline 232.38초, RunPod execution 873.48초(모델 staging 포함), delay 56.84초. 관측 GPU memory peak 22,775 MiB. 공식 좌표 변환 최대 오차 1.3361e-7로 기준 1e-5 이하. GPU implementation hash 및 전체 42파일 snapshot이 작업 tree와 일치했다. 상세 machine evidence는 `docs/runpod_serverless_validation.json` 및 run의 `logs/`에 있다.

처음에는 inherited `RUNPOD_API_KEY` 환경 변수가 `.runtime/runpod-api.key`보다 우선하여 HTTP 401이 발생했다. 두 키가 다름을 값을 출력하지 않고 확인했다. 해당 프로세스에서 override를 제외하자 기존 private 파일 키의 실제 HTTP health/poll 인증이 성공했다. 인증 파일은 수정하지 않았다. GPU job 제출은 승인된 RunPod MCP로 했고, 실제 RunPodClient HTTP 응답을 production RemotePipeline에 전달하여 S3 progress/result와 materialization을 검증했다. 따라서 제출 인증 경로는 평소 CLI와 다르지만 결과를 mock하지 않았다. 최초 local submit 실패 run `74c42b5368834e7bac57c3cef27fb4a6`은 원인 근거로 보존했다.

현재 검증 source archive SHA-256: `bd4156e9b18a7e4768cb42e6b18be81afd9172ddb82abc01401cbfe31177466a`. Native image `8a0bcaa35`에 이 source snapshot을 적용하고 orchestrator를 frozen lock으로 sync했다. Worker 로그에서 source hash 및 제거 package 목록을 확인했다. 기존 운영 endpoint의 image/GPU/storage/env는 유지하고, 시작 명령만 검증 동안 변경했다. 완료 후 원래 `-m mapmaker.serverless_worker`로 복구했고 전체 endpoint 설정이 변경 전과 같음을 재조회해 확인했다. 실행/대기 job은 0이다. Private S3의 검증용 source ZIP 2개를 삭제하고 각각 404를 확인했다. 정리 코드를 운영 이미지에 영구 배포하거나 push하지 않았다.

첫 overlay run `9589c248afc44cf28a7663f999e7be06`은 shell CRLF를 발견해 staging 중 취소했다(실제 CANCELLED 확인). `.gitattributes`로 shell LF를 고정하고 snapshot을 다시 만들었다. 별도 임시 endpoint `wkrwc7fj085x5y`는 registry 인증 오류로 후속 job이 실행되지 않아 취소·삭제했고 404를 확인했다. 해당 실패 run `878b842b8c114e7897e46f09c124f4ae`도 보존했다. 취소/인증 실패를 inference 성공으로 세지 않는다.

## 7. 알려진 한계 / 다음 작업자

- 환경 변수는 private 파일 설정보다 우선한다. 이번 도구 프로세스의 다른 inherited API key가 401을 일으켰고, 프로세스 override를 제외하면 저장된 키로 실제 인증이 성공했다. 키 값을 출력하거나 설정 파일을 덮어쓰지 않는다.
- 실제 Docker rebuild 및 새 native environment 재현은 미검증이다. 이 작업의 GPU source overlay 성공을 새 image build 성공으로 해석하지 않는다.
- Cold start에 약 21.4GB model staging과 큰 image pull이 남는다. Native freeze의 넓은 upstream dependency는 안전한 축소 근거가 부족하여 유지했다.
- API/worker lock은 process-local이다. Multi-process 전체의 duplicate 제어와 durable job resume는 없다. Remote restart는 cancel 시도+실패 처리이며 local GPU mode에는 자체 reconstruction timeout/recovery가 없다.
- S3 artifact lifecycle/자동 삭제가 없어 quota 관리가 필요하다. 결과 업로드 실패 시 worker scratch 종료로 진단 결과까지 잃을 수 있다.
- UI polling/GLB fetch 오류는 표시를 실패로 바꾸지만 GPU job을 자동 취소하지 않는다. URL refresh로 다시 확인할 수 있다.
- 일부 객체 실패는 허용하지만 모든 객체 실패/assembly 실패는 run 실패다. Gaussian PNG 실패는 경고로 남을 수 있고 CPU preview 실패는 전체 run 실패가 된다.
- 품질 검증은 제한된 입력 기준이다. 구조물/room shell/편집/인증 기능은 구현되지 않았다. CPU preview는 orthographic painter와 triangle-centroid UV sampling으로 원본 camera 정합 평가가 아니다.

처음 읽는 순서: 이 문서 → scene_pipeline → scene_remote/serverless_worker → scene_vision → scene_reconstruct/scene_assembly → web. 배포 변경 시 runtime_paths, model manifest, source revisions, ABI별 freeze를 함께 확인한다. 기존 successful artifacts를 지우기 전에 reference/evidence 사용처를 먼저 확인한다.
