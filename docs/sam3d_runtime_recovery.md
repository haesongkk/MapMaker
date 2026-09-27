# SAM3D runtime 복구 기록 (2026-09-27)

현재 상태 (후속 복구 완료): 공식 DINOv2 source/weight를 영구 cache에 복원했고,
실제 SAM3D Dino wrapper의 pretrained load 및 A100 forward가 통과했다.
sofa 회귀도 통과했다. pose 차이는 0, mesh 축 크기 차이는 최대 약 0.00124%이며
기존 renderer의 oblique preview에서도 같은 형태를 확인했다.

- DINO source: `7764ea0f912e53c92e82eb78a2a1631e92725fc8` (공식 facebookresearch/dinov2)
- 공식 weight: `https://dl.fbaipublicfiles.com/dinov2/dinov2_vitl14/dinov2_vitl14_reg4_pretrain.pth`
- SHA-256: `36e4deffbaef061a2576705b0c36f93621e2ae20bf6274694821b0b492551b51`
- cache: `.runtime/sam3d-torch/hub/`
- 실제 결과: `.runtime/sam3d-regression-restored-20260927/`
- 기존 source/weight format을 변환하지 않았으며 SAM3D source 및 `.venv-vision`은 변경하지 않았다.
- 최초 cold import 약 13분, 모델 초기화 약 1164초, sofa 추론·export 약 30.8초.
  이 실행의 네트워크 파일시스템 지연을 포함한 실측이며 이후 모든 실행의 예상 시간은 아니다.
- 다음 실행에는 컨테이너 CPU quota(약 12 cores)에 맞춰 OMP/MKL 기본 thread 수를 8로 제한한다.
  package/model version 변경은 없다. 웹 서버는 SAM3D worker를 유지해 다음 run에서 모델을 재사용한다.

```bash
python scripts/recover_dinov2.py
source scripts/sam3d_runtime_env.sh
"$SAM3D_PYTHON" scripts/sam3d_dino_smoke.py
```

## 영구 환경과 보존 대상

- 전용 venv: `/workspace/MapMaker/.venv-sam3d`
- base Python/CUDA: `experiments/image_first_scene_object_benchmark/model_setup/sam3d_objects/env`
- 두 경로를 모두 보존해야 한다. venv의 Python은 기존 conda Python을 참조한다.
- RAM++/SAM3의 `.venv-vision`은 변경하지 않는다.
- source/checkpoint/run 원본은 `experiments/image_first_scene_object_benchmark`에 보존한다.
- 설치·빌드 기록과 wheel: `.runtime/sam3d-recovery/` (git 제외)
- `/tmp`는 사용하지 않는다.

## 버전의 근거

기준은 최초 설치 목록이 아닌 **마지막 성공 후 목록**이다.

- 원본: `experiments/image_first_scene_object_benchmark/model_setup/sam3d_objects/resume_20260925/installed_packages.txt`
- 보존 사본: `configs/sam3d/successful-runtime-freeze.txt`
- 마지막 setuptools 수정 근거: 같은 디렉터리의 `setuptools_repair.json`
- 설치 순서 근거: `model_setup/sam3d_objects/install_local_build_dependencies.sh` 및 `resume_20260925/install/log.txt`

확인한 조합:

| 항목 | 값 |
|---|---|
| Python | 3.11.0 (기존 conda interpreter) |
| PyTorch | 2.5.1+cu121 |
| torchvision / torchaudio | 0.20.1+cu121 / 2.5.1+cu121 |
| CUDA toolkit | 12.1.105 (기존 nvcc) |
| setuptools | 69.5.1 (성공 시 최종 repair) |
| SAM3D source | f91db411c50efee93d8db7aeb323885650f6f722 |
| PyTorch3D source | 75ebeeaea0908c5527e7b1e305fbc7681382db47 |
| gsplat source | 2323de5905d5e90e035f792fe65bad0fedd413e7 |
| MoGe source (기존 SAM3D dependency) | a8c37341bc0325ca99b9d57981cc3bb2bd3e255b |
| utils3d source | 3913c65d81e05e47b9f367250cf8c0f7462a0900 |
| kaolin / flash-attn | 0.17.0 / 2.8.3 |

`pipeline.yaml` SHA-256:
`53c3d226b21df85c0bb3d16e6e4fa63abde0d6167525765eb929d02bfa9d358c`
기존 성공 로드 기록과 일치한다.
checkpoint 위치는 기존 `model_setup/sam3d_objects/repo/checkpoints/hf`이다.
SAM3D 본체 checkpoint와 object extraction 모델은 재사용했다. 누락된 공식 DINOv2 보조 weight만 추가로 복원했다.

## 실행 방법

repo root에서 실행한다.

```bash
mkdir -p .runtime/sam3d-recovery
set -o pipefail
bash scripts/recover_sam3d_runtime.sh 2>&1 | tee .runtime/sam3d-recovery/recovery.log
source scripts/sam3d_runtime_env.sh
"$SAM3D_PYTHON" scripts/sam3d_runtime_audit.py
```

복구 스크립트 끝에서 공식 `Inference`, `load_image`, `make_scene` import를 검사한다.
아래 regression은 import와 버전 확인 후 실행할 별도 gate이다.
이미 있는 결과 디렉터리를 덮어쓰지 않는다.

```bash
source scripts/sam3d_runtime_env.sh
"$SAM3D_PYTHON" scripts/sam3d_regression.py \
  --output .runtime/sam3d-regression-20260927 \
  > .runtime/sam3d-recovery/regression.log 2>&1
```

regression은 기존 `phase_c/main_living_room`의 `object_000_sofa`를 사용한다.
원본 RGB·mask hash와 pipeline hash를 확인한 뒤 공식
`Inference(..., compile=False)` → `inference(image, mask, seed=42)`를 호출한다.
`mesh.glb`, `pose.json`, `splat.ply`, provenance 및 bounds/pose 비교를 별도 출력한다.
이 테스트의 고정 object 선택은 regression 용도이며 production의 객체 목록 생성 방식이 아니다.

## 빌드 위치와 영구성

처음에는 모든 빌드를 영구 파일시스템에서 수행했으나, PyTorch3D 첫 CPU object
두 개가 각각 약 381초·443초 걸렸다. 네트워크 파일시스템에서 반복되는 header 접근을
줄이기 위해 `scripts/build_sam3d_native.sh`가 `/dev/shm/mapmaker-sam3d-build`를
컴파일 scratch로 사용한다.

- 설치된 Torch 코드·library는 수정하지 않고 참조한다.
- Torch/CUDA/CUB header는 원본 그대로 메모리에 복사한다.
- compiler는 기존 conda GCC/nvcc를 사용한다. CUDA target은 기존 A100의 compute/sm 80이다.
- Git source는 성공 기록의 commit으로 고정한다.
- `UV_LINK_MODE=copy`로 **영구 venv에 복사 설치**한다.
- 빌드된 wheel은 `.runtime/sam3d-recovery/wheels`에 보존한다.
- scratch는 runtime이 아니다. Pod 재시작 후 없어져도 설치된 환경이 scratch를 필요로 해서는 안 된다.

실제 메모리 include 경로가 build.ninja에 반영됐음을 확인했다.
첫 CPU object 두 개는 약 63초씩, CUDA object 두 개는 약 82초씩에 완료됐다.
이는 복구 빌드 진행 기록이며 모델 inference 성능 비교가 아니다.

## 설치 중 보완한 사항

- 원래 `uv venv --seed`가 제공하던 pip가 필요했으므로 성공 freeze의
  `pip==26.2.1`, 기존 build dependency `appdirs==1.4.4`를 bootstrap에 포함했다.
- `nvidia-pyindex==1.0.9`는 추론 라이브러리가 아니라 pip index 설정 installer이다.
  setup hook이 사용자/시스템 pip 설정까지 수정하므로 제외했다.
  필요한 기존 PyTorch/Kaolin index URL은 명령에 직접 지정한다.
- `jupyter-events==0.4.0`의 빈 dist-info/RECORD가 한 번 확인됐다.
  새 SAM3D venv의 해당 빈 metadata만 제거하고 같은 버전을 다시 설치해 복구했다.
  근거는 `.runtime/sam3d-recovery/metadata-repair.json` 및 `.log`에 남겼다.

- 중단된 초기 설치에서 8개 package의 RECORD에 기록된 파일 일부가 누락된 것을 확인했다.
  `file-audit-before-repair.json`에 누락 목록을 보존하고 해당 package만 동일 버전으로 재설치했다.
  재검사 결과 89,441개 설치 파일에서 누락이 없고, 성공 freeze 438개 항목의 버전/commit 대조도 통과했다.
  버전 변경 없이 복구했으며 `.venv-vision`은 수정하지 않았다.

## 현재 검증된 사실

- `torch-smoke.json`: Python 3.11.0, torch 2.5.1+cu121, CUDA 12.1,
  NVIDIA A100 80GB PCIe, CUDA available=true, 실제 GPU 행렬 연산 통과.
- `baseline-audit.json`: 거실 원본 frozen 파일 8개 hash 전부 일치.
- `baseline-mesh.json`: 기존 sofa GLB 로드 성공, 209020 vertices / 418048 faces,
  유한한 좌표 및 bounds 확인.
- `official-smoke.json`: 공식 Inference/load_image/make_scene import 성공. PyTorch3D/gsplat native library의 RPATH가 영구 conda 경로만 참조함을 확인.
- 메모리 빌드 scratch를 이름 변경하여 원래 경로를 없앤 상태에서 sofa regression을 시작했다.
- `dino-smoke.json`: 실제 SAM3D Dino wrapper의 pretrained ViT-L/14 registers load 및 CUDA forward 통과, output `[1,1370,1024]`, finite=true.
- `.runtime/sam3d-regression-restored-20260927/comparison.json`: 실제 sofa mesh/pose 생성 및 비교 통과. pose 동일, extent 최대 차이 약 0.00124%.
- 첫 production 웹 run `runs/fcb2e188019d4e7fbb76b9136e78d794`: 5개 object GLB, 독립 node scene.glb, 공식 Gaussian preview 생성. 실제 Chromium의 upload/generate/status/preview/toggle/orbit/zoom/pan/export 모두 통과.
- 최종 거실 6개 / 사과 2개 객체의 end-to-end 및 실제 웹 검증까지 통과했다. 결과는 [프로젝트 검증 보고서](sam3d_project_validation.md)에 기록했다.

## 해결된 과거 중단 원인

이전 턴에서는 DINOv2 Torch Hub cache와 weight가 없고 정확한 과거 Hub revision도 기록되지 않아 멈췄다. 후속 사용자 지시에 따라 공식 source의 고정 commit과 동일 `dinov2_vitl14_reg4_pretrain.pth`를 복원했다.

SAM3D `dino.py`가 호출하는 `torch.hub.load("facebookresearch/dinov2", "dinov2_vitl14_reg")`와 동일한 wrapper 경로에서 실제 pretrained load/forward를 검증했다. `TORCH_HOME`을 workspace의 영구 cache로 설정했고 source API나 weight format은 변경하지 않았다. preflight, 실제 sofa inference, pose/mesh 비교가 모두 통과했으므로 이 cache 문제는 해소됐다.
