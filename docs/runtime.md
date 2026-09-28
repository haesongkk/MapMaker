# Worker deployment and recovery

현재 아키텍처와 이번 검증 결과는 [상태 문서](../PROJECT_CURRENT_STATE.md), Windows 사용법은 [README](../README.md)에 있습니다.

## Build

```bash
docker build --platform linux/amd64 -f deploy/runpod/Dockerfile .
```

Docker는 source revision을 [source-revisions.json](../configs/serverless/source-revisions.json)에서 읽어 필요한 commit만 depth 1로 fetch합니다. 모델 source는 editable 설치 및 RAM package data, SAM3 tokenizer assets, SAM3D notebook entrypoint, DINO Torch Hub 때문에 유지합니다. 외부 구현을 복사해 자체 wrapper로 대체하지 않습니다.

| 환경 | 용도 / 고정 버전 |
|---|---|
| `.venv` | orchestration, boto3, RunPod SDK, CPU preview; `uv sync --frozen --no-dev --extra serverless --extra remote` |
| `.venv-vision` | base Python 3.12.3 / Torch 2.8.0+cu128 + [vision overlay](../configs/serverless/vision-overlay.txt) |
| `.venv-sam3d` | Python 3.11.0 / Torch 2.5.1+cu121 + [successful freeze](../configs/sam3d/successful-runtime-freeze.txt) |
| `/opt/sam3d-base` | [conda Python/CUDA compiler and native libraries](../configs/serverless/sam3d-conda.yml) |

이 분리는 서로 다른 Python/Torch/CUDA ABI를 보존합니다. flash-attn, PyTorch3D, gsplat, kaolin, spconv 버전/빌드 방식을 변경하지 않습니다. Native CUDA targets는 `8.0;8.6;8.9+PTX`입니다. Multi-stage runtime image는 builder 다운로드 cache와 compiler intermediate를 포함하지 않습니다. Native freeze에는 upstream inference import가 요구하는 넓은 의존성이 남아 있습니다. 직접 import가 없다는 이유만으로 제거하지 마세요.

## Endpoint configuration

Entrypoint: `/opt/mapmaker/.venv/bin/python -m mapmaker.serverless_worker`.
Worker의 `MAPMAKER_BACKEND=local`은 정상입니다. Windows orchestrator가 RunPod에 제출하고 worker 내부에서는 local GPU pipeline을 실행합니다.

- 설정: `MAPMAKER_S3_BUCKET`, `MAPMAKER_S3_ENDPOINT`, `AWS_DEFAULT_REGION`.
- 인증: AWS access/secret은 RunPod Secrets 참조 또는 private provider로 전달합니다. 모델 manifest source bucket 읽기와 artifact bucket 읽기/쓰기 권한이 필요합니다.
- `RUNPOD_INIT_TIMEOUT=1800`, job timeout은 기본 7200초. 원격 생성의 초기 모델 준비는 오래 걸릴 수 있습니다.
- `MAPMAKER_MODEL_ROOT=/opt/mapmaker-models`; `.runtime` cache와 HF/Torch home도 Docker ENV를 따릅니다.
- `SAM3D_REPO`, `SAM3D_PYTHON`, `MAPMAKER_VISION_PYTHON`, `MAPMAKER_SAM3D_BASE`는 Docker가 설정합니다. Vision interpreter symlink를 resolve하면 venv가 사라지므로 경로를 보존해야 합니다.
- `MAPMAKER_SAM3D_CHECKPOINT`, `MAPMAKER_RAM_CHECKPOINT`, `MAPMAKER_SAM3_CHECKPOINT`, `MAPMAKER_DINO_PROVENANCE`로 경로 override가 가능합니다.
- 모델 [manifest](../configs/serverless/model-storage.json)는 original S3 key, target path, bytes, SHA-256을 고정합니다. Offline HF 로딩을 사용하며 job마다 임의 모델을 다운로드하지 않습니다.
- 모델은 GPU worker disk에 stage되고 warm worker에서 재사용됩니다. Region별 GPU 배치와 모델 source storage는 독립적입니다. S3 source의 가용성과 cold download 비용은 남습니다.

`models--Ruicheng--moge-vitl`은 현재 SAM3D `pipeline.yaml`의 depth_model입니다. RAM++는 `BertTokenizer.from_pretrained('bert-base-uncased')`를 호출합니다. 이들 cache는 삭제한 과거 MoGe pipeline과 별개입니다. DINOv2는 ss/slat generator config의 feature embedder입니다. Gaussian decoder 두 종류도 pipeline 초기화에 모두 로드되어 유지합니다.

Checkpoint나 source를 재배포할 때는 각 upstream LICENSE/NOTICE와 모델 접근 조건을 보존해야 합니다. 이번 정리는 source vendoring이나 모델 재배포 방식을 변경하지 않습니다.

## Linux local / repair

새 GPU worker는 Docker build를 우선 사용합니다. 아래 도구는 이미 존재하는 Linux SAM3D source/base environment를 복구하는 용도이며, Windows에서 새 모델 환경을 만드는 installer가 아닙니다.

```bash
export SAM3D_REPO=/opt/sam3d
export MAPMAKER_SAM3D_BASE=/opt/sam3d-base
export MAPMAKER_MODEL_ROOT=/opt/mapmaker-models
export TORCH_HOME=/opt/mapmaker-models/.runtime/sam3d-torch
source scripts/sam3d_runtime_env.sh
"$SAM3D_PYTHON" scripts/sam3d_runtime_audit.py
"$SAM3D_PYTHON" scripts/sam3d_file_audit.py
"$SAM3D_PYTHON" scripts/sam3d_checkpoint_preflight.py
```

`sam3d_runtime_env.sh`는 CUDA compiler/library 경로와 persistent cache를 설정합니다. 명시 override가 없으면 기존 Linux benchmark layout을 사용합니다. 해당 기본 layout은 현재 Windows checkout에 없으므로 경로를 지정해야 합니다.

- `recover_sam3d_runtime.sh`: 성공 freeze를 같은 버전으로 설치하고 `build_sam3d_native.sh`를 호출합니다. 먼저 base conda environment, pinned source, 본체 checkpoints가 있어야 합니다.
- `build_sam3d_native.sh`: 네트워크 파일시스템의 느린 header 접근을 줄이는 `/dev/shm` build scratch; 설치물은 `UV_LINK_MODE=copy`로 persistent venv에 남깁니다. Container 기본 build는 `deploy/runpod/build_runtime.sh`를 사용합니다.
- `recover_dinov2.py`: `TORCH_HOME`에 고정 공식 source와 original weight를 복구하고 SHA-256을 검사합니다. 이 스크립트는 네트워크 다운로드를 수행합니다.
- `sam3d_smoke.py`: 공식 entrypoint/native imports, GPU availability 및 scratch RPATH 부재를 검사합니다.
- `sam3d_dino_smoke.py`: 실제 SAM3D Dino wrapper의 CUDA forward를 검사합니다.

도구 출력은 `.runtime/sam3d-recovery/`에 있습니다. 버전/import 검사는 실제 scene generation을 대체하지 않습니다. 복구 후 production 입력으로 `mapmaker.cli run`, artifact reference 비교와 browser E2E를 수행하세요.

## Failure evidence

Run별 `logs/remote_job.json`, `runpod_timing.json`, `remote_integrity.json`, `runpod_failure.json`과 worker 로그를 확인합니다. S3 quota 초과는 inference 완료 후 결과 업로드에서도 발생할 수 있습니다. 공간 확보 없이 재시도하지 마세요. API key와 S3 credentials는 서로 다릅니다.

Backend restart는 미완료 remote run의 취소를 시도하고 실패 상태를 기록합니다. 자동 재개와 S3 lifecycle 삭제는 구현되어 있지 않습니다. GPU 성공 reference와 실패 원인 로그는 cache와 구별하여 보존하세요. 과거 실제 GPU evidence는 [runpod_serverless_validation.json](runpod_serverless_validation.json)에 남아 있으며 이번 변경 코드의 검증 결과와 구분합니다.
