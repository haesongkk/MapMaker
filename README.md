# MapMaker — HY-World 2.0 single-GPU RunPod workflow

이 저장소는 Tencent의 HY-World 2.0을 RunPod 단일 NVIDIA GPU에서 설치하고 실행하기 위한 개인 fork입니다. RTX PRO 6000 Blackwell에서 이미지 한 장으로 파노라마, 탐색 경로, WorldStereo/WorldMirror, 3D Gaussian Splatting과 메시를 만드는 전체 과정을 검증했습니다.

> 공식 배포판이 아닙니다. 프로젝트 소개, 모델 구조, 라이선스와 인용 정보는 [원본 영문 README](README_UPSTREAM.md) 또는 [중문 README](README_zh.md)를 확인하세요.

## 이 fork의 변경 사항

- WorldStereo 종료 후 GPU 메모리를 해제하고 WorldMirror 실행
- 기존 비디오로 정렬과 내보내기만 재개하는 `--postprocess_only`
- 누락된 WorldMirror `name_map.json` completion marker 복구
- Hugging Face 캐시 경로 환경변수 지원
- 오프라인 WorldStereo T5 tokenizer 로딩 수정
- 단일 GPU 학습 종료 시 잘못된 distributed barrier 방지
- 검증된 RunPod 실행 스크립트와 패키지 버전 보관

## 검증 환경

| 항목 | 버전 |
|---|---|
| OS | Ubuntu 24.04.3 LTS |
| GPU | NVIDIA RTX PRO 6000 Blackwell Server Edition, 97,887 MiB |
| CUDA / GCC | CUDA 12.8.93 / GCC 13.3.0 |
| 메인 환경 | Python 3.11.13, PyTorch 2.7.1+cu128 |
| VLM 환경 | Python 3.12.3, PyTorch 2.11.0+cu128, vLLM 0.26.0 |
| uv | 0.9.0 |
| upstream 기준 | `df9988efb87bfc0f4947eb3889411cf957478b06` |

다른 GPU 세대에서는 FlashAttention과 custom gsplat CUDA 확장을 해당 compute capability에 맞게 다시 빌드해야 합니다. 아래 명령은 GPU 0 하나를 사용합니다.

# 설치

같은 저장소 볼륨을 다시 연결했다면 재설치하지 말고 [빠른 재실행](#빠른-재실행)으로 이동하세요.

## 1. 저장소와 디렉터리 준비

```bash
git clone --recursive https://github.com/haesongkk/MapMaker.git
cd MapMaker
git submodule update --init --recursive
source scripts/mapmaker-env.sh

```

실행 권한을 확인합니다.

```bash
chmod +x scripts/*.sh
```

## 2. uv와 Python 준비

RunPod 이미지에 `uv`가 없다면 설치합니다. 시스템에 Python 3.11과 3.12가 있어야 합니다.

```bash
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$MAPMAKER_TOOLS_DIR/bin" UV_NO_MODIFY_PATH=1 sh
export PATH="$MAPMAKER_TOOLS_DIR/bin:$PATH"
uv --version
python3.11 --version
python3.12 --version
```

## 3. 메인 환경 설치

```bash
uv venv --python /usr/bin/python3.11 $MAPMAKER_MAIN_VENV

uv pip install --python $MAPMAKER_MAIN_VENV/bin/python \
  torch==2.7.1 torchvision==0.22.1 \
  --index-url https://download.pytorch.org/whl/cu128

uv pip install --python $MAPMAKER_MAIN_VENV/bin/python \
  -r $MAPMAKER_ROOT/hyworld2/panogen/requirements.txt

uv pip install --python $MAPMAKER_MAIN_VENV/bin/python \
  -r $MAPMAKER_ROOT/requirements.txt

uv pip install --python $MAPMAKER_MAIN_VENV/bin/python \
  setuptools==78.1.0 ninja packaging
```

검증 당시 Git 의존성을 정확한 커밋으로 설치합니다.

```bash
uv pip install --python $MAPMAKER_MAIN_VENV/bin/python \
  --no-build-isolation \
  "nerfview @ git+https://github.com/nerfstudio-project/nerfview.git@4538024fe0d15fd1a0e4d760f3695fc44ca72787" \
  "fused-ssim @ git+https://github.com/rahul-goel/fused-ssim.git@328dc9836f513d00c4b5bc38fe30478b4435cbb5" \
  "spz @ git+https://github.com/nianticlabs/spz.git@5bf2945de1a003cee07133b1e495fe9c6ffdc7e7" \
  "pytorch3d @ git+https://github.com/facebookresearch/pytorch3d.git@e73a7e7bfc580d1f9225ad9ff7d2c753c320aabd" \
  "moge @ git+https://github.com/microsoft/MoGe.git@0286b495230a074aadf1c76cc5c679e943e5d1c6" \
  "utils3d @ git+https://github.com/EasternJournalist/utils3d.git@c5daf6f6c244d251f252102d09e9b7bcef791a38"
```

Blackwell에서는 CUDA architecture 12.0으로 네이티브 확장을 빌드합니다.

```bash
source scripts/mapmaker-env.sh
export TORCH_CUDA_ARCH_LIST=12.0
export MAX_JOBS=8

uv pip install --python $MAPMAKER_MAIN_VENV/bin/python \
  --no-build-isolation flash-attn==2.8.3.post1

git clone https://github.com/g-truc/glm.git \
  "$MAPMAKER_ROOT/hyworld2/worldgen/third_party/gsplat_maskgaussian/gsplat/cuda/csrc/third_party/glm"
git -C "$MAPMAKER_ROOT/hyworld2/worldgen/third_party/gsplat_maskgaussian/gsplat/cuda/csrc/third_party/glm" \
  checkout 33b4a621a697a305bc3a7610d290677b96beb181
uv pip install --python $MAPMAKER_MAIN_VENV/bin/python \
  --no-build-isolation -e \
  $MAPMAKER_ROOT/hyworld2/worldgen/third_party/gsplat_maskgaussian

uv pip install --python $MAPMAKER_MAIN_VENV/bin/python \
  --no-build-isolation \
  $MAPMAKER_ROOT/hyworld2/worldgen/third_party/navmesh
```


전체 성공 환경은 [메인 환경 고정 목록](environment/MAIN_ENV_FREEZE.txt)에 기록되어 있습니다.

## 4. vLLM 환경 설치

Qwen3-VL은 충돌을 피하기 위해 별도 환경에서 실행합니다.

```bash
uv venv --python /usr/bin/python3.12 $MAPMAKER_VLLM_VENV

uv pip install --python $MAPMAKER_VLLM_VENV/bin/python \
  torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 \
  --index-url https://download.pytorch.org/whl/cu128

uv pip install --python $MAPMAKER_VLLM_VENV/bin/python \
  vllm==0.26.0
```

전체 성공 환경은 [vLLM 환경 고정 목록](environment/VLLM_ENV_FREEZE.txt)에 기록되어 있습니다. 실행 스크립트는 필요한 CUDA 13 runtime 경로를 자동으로 설정합니다.

## 5. Hugging Face 인증과 모델 다운로드

`facebook/sam3` 사용 승인을 먼저 받은 후 로그인합니다. 토큰을 저장소에 기록하지 마세요.

```bash
source scripts/mapmaker-env.sh
hf auth login

hf download facebook/sam3
hf download Qwen/Qwen3-VL-8B-Instruct
hf download Qwen/Qwen-Image-Edit-2509
hf download Ruicheng/moge-2-vitl-normal
hf download Wan-AI/Wan2.1-I2V-14B-480P-Diffusers
hf download IDEA-Research/grounding-dino-tiny
hf download naver-iv/zim-anything-vitl
hf download facebook/dinov2-base
hf download hanshanxue/WorldStereo --include "worldstereo-memory-dmd/*"
hf download tencent/HY-World-2.0 \
  --include "HY-Pano-2.0/*" "HY-WorldMirror-2.0/*"
```

모델 캐시는 `$MAPMAKER_CACHE_DIR/huggingface`에 저장됩니다. 검증 환경에서는 약 202GB가 필요했습니다.

## 6. 설치 확인

```bash
source scripts/mapmaker-env.sh
python -c "import torch, cupy, diffusers, transformers, gsplat, flash_attn; print(torch.__version__, torch.cuda.get_device_name(0))"
bash -n $MAPMAKER_ROOT/scripts/*.sh
```

# 실행

아래 예시는 저장소에 포함된 A_MARCEAU 이미지를 3D world로 변환합니다.

## 빠른 재실행

설치와 캐시가 남아 있는 기존 볼륨에서는 환경을 불러온 뒤 바로 작업할 수 있습니다.
모든 명령은 저장소 루트에서 실행합니다.

```bash
source scripts/mapmaker-env.sh
nvidia-smi
```

이미 만들어진 A_MARCEAU 결과를 열려면 RunPod에서 TCP 8082 HTTP 서비스를 노출하고 실행합니다.

```bash
bash $MAPMAKER_ROOT/scripts/start-mapmaker-gs-viewer.sh
```

8082 페이지의 **장면 선택** 메뉴에서 `outputs/images/*/gs/ckpts/ckpt_7999_rank0.pt`가 있는 장면을 전환합니다. 장면을 선택하면 로딩 상태가 표시되고 카메라가 해당 장면의 초기 위치로 이동합니다. 장면 선택은 접속 중인 모든 사용자에게 함께 적용됩니다. 별도 갤러리 페이지는 필요하지 않습니다.

같은 메뉴의 **출력 형식**에서 다음 결과를 선택할 수 있습니다. 해당 장면에 존재하는 파일만 표시됩니다.

| 출력 형식 | 읽는 파일 | 표시 방식 |
|---|---|---|
| 학습 원본 · PT | `gs/ckpts/ckpt_7999_rank0.pt` | Gaussian 렌더링 |
| Gaussian · PLY | `gs/ply/point_cloud_7999.ply` | Gaussian 렌더링 |
| 압축 Gaussian · SPZ | `gs/ply/point_cloud_7999.spz` | 실제 SPZ 복원 후 Gaussian 렌더링 |
| 후처리 메시 | `gs/ply/fuse_post.ply` | 정점 색상을 포함한 삼각형 표면 |
| 단순화 메시 | `gs/ply/fuse_simplified.ply` | 삼각형 수를 줄인 표면 |

형식만 바꾸면 카메라 위치를 유지하고, 장면을 바꾸면 초기 위치로 이동합니다. 파일명과 Gaussian 또는 삼각형 개수도 표시합니다. RGB·Depth·Normal 모드는 Gaussian에 적용되며 메시에서는 비활성화됩니다. PT와 내보낸 PLY는 내보내기 필터링 때문에 Gaussian 개수가 다를 수 있습니다. SPZ는 PLY의 압축 결과입니다.


다른 체크포인트는 다음처럼 엽니다.

```bash
MAPMAKER_GS_PORT=8082 \
  bash $MAPMAKER_ROOT/scripts/start-mapmaker-gs-viewer.sh \
  $MAPMAKER_OUTPUT_DIR/a-marceau-worldgen-gs/ckpts/ckpt_7999_rank0.pt
```

## 1. 입력과 출력 경로

```bash
source scripts/mapmaker-env.sh

export INPUT_IMAGE=$MAPMAKER_ROOT/inputs/images/A_MARCEAU/image_0001.jpg
export PANO_OUTPUT=$MAPMAKER_OUTPUT_DIR/a-marceau-panorama.png
export SCENE_DIR=$MAPMAKER_OUTPUT_DIR/a-marceau-worldgen
export GS_RESULT_DIR=$MAPMAKER_OUTPUT_DIR/a-marceau-worldgen-gs

mkdir -p "$SCENE_DIR"
```

## 2. 입력 이미지를 360도 파노라마로 확장

```bash
cd $MAPMAKER_ROOT/hyworld2/panogen

python pipeline_with_qwen_image.py \
  --image "$INPUT_IMAGE" \
  --prompt "Expand this image into a seamless 360-degree equirectangular panorama while preserving its original artistic style, architecture, lighting, colors, and scene identity." \
  --seed 42 \
  --reproduce \
  --height 960 \
  --width 1920 \
  --num-inference-steps 40 \
  --save "$PANO_OUTPUT"

cp "$PANO_OUTPUT" "$SCENE_DIR/panorama.png"
```

입력이 이미 2:1 equirectangular 파노라마라면 이 단계를 생략하고 `panorama.png`로 복사합니다.

## 3. Qwen3-VL 서버 시작

별도 터미널에서 다음 서버를 시작하고 Stage 1과 2가 끝날 때까지 유지합니다.

```bash
bash $MAPMAKER_ROOT/scripts/start-mapmaker-vllm.sh
```

기본 포트는 8000, GPU 메모리 비율은 0.50입니다.

```bash
MAPMAKER_VLM_GPU_UTIL=0.45 \
  bash $MAPMAKER_ROOT/scripts/start-mapmaker-vllm.sh
curl http://127.0.0.1:8000/v1/models
```

## 4. Stage 1 — 경로 계획

다른 터미널에서 저장소 루트로 이동한 뒤 환경과 경로 변수를 다시 설정하고 실행합니다.

```bash
source scripts/mapmaker-env.sh
export SCENE_DIR=$MAPMAKER_OUTPUT_DIR/a-marceau-worldgen
cd $MAPMAKER_ROOT/hyworld2/worldgen

python traj_generate.py \
  --target_path "$SCENE_DIR" \
  --llm_addr 127.0.0.1 \
  --llm_port 8000 \
  --llm_name Qwen/Qwen3-VL-8B-Instruct \
  --apply_nav_traj \
  --apply_up_route \
  --apply_recon_iteration \
  --force_vlm
```

## 5. Stage 2 — 경로 렌더링과 캡션

```bash
torchrun --standalone --nproc_per_node=1 traj_render.py \
  --target_path "$SCENE_DIR" \
  --llm_addr 127.0.0.1 \
  --llm_port 8000 \
  --llm_name Qwen/Qwen3-VL-8B-Instruct
```

완료되면 vLLM 터미널에서 `Ctrl+C`로 서버를 종료합니다. Stage 3 전에 반드시 GPU 메모리를 비워야 합니다.

## 6. Stage 3 — WorldStereo와 WorldMirror

```bash
torchrun --standalone --nproc_per_node=1 video_gen.py \
  --target_path "$SCENE_DIR" \
  --local_files_only \
  --skip_exist
```

캐시가 없는 첫 실행이라면 `--local_files_only`를 제거합니다. 이 단계는 WorldStereo 비디오 생성, WorldMirror 깊이 추론, 정렬, 필터링과 `aligned_pcd.ply` 내보내기를 순서대로 수행합니다.

비디오는 모두 완성됐고 정렬과 내보내기만 다시 실행하려면:

```bash
torchrun --standalone --nproc_per_node=1 video_gen.py \
  --target_path "$SCENE_DIR" \
  --local_files_only \
  --skip_exist \
  --postprocess_only \
  --nframe 21
```

`--postprocess_only`에서는 필요한 비디오가 하나라도 없으면 `FileNotFoundError`가 발생합니다.

## 7. Stage 4 — Gaussian Splatting 데이터 생성

```bash
torchrun --standalone --nproc_per_node=1 gen_gs_data.py \
  --root_path "$SCENE_DIR" \
  --save_normal \
  --split_sky
```

## 8. Stage 5 — 단일 GPU 3DGS 학습

기존 결과를 보존하려면 매번 새로운 `GS_RESULT_DIR`을 사용하세요.

```bash
export GS_RESULT_DIR=$MAPMAKER_OUTPUT_DIR/a-marceau-worldgen-gs

PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
python -m world_gs_trainer default \
  --data_dir "$SCENE_DIR/gs_data" \
  --result_dir "$GS_RESULT_DIR" \
  --max_steps 8000 \
  --save_steps 8000 \
  --eval_steps 8000 \
  --ply_steps 8000 \
  --save_ply \
  --convert_to_spz \
  --disable_video \
  --disable_viewer \
  --use_scale_regularization \
  --antialiased \
  --depth_loss \
  --normal_loss \
  --sky_depth_from_pcd \
  --use_mask_gaussian \
  --mask_export_stochastic \
  --no-mask-export-anchor-protection \
  --use_anchor_protection \
  --export_mesh \
  --strategy.refine-start-iter 1200 \
  --strategy.refine-stop-iter 6000 \
  --strategy.refine-every 800 \
  --strategy.refine-scale2d-stop-iter 6000 \
  --strategy.reset-every 99990 \
  --strategy.grow-grad2d 0.0001 \
  --strategy.prune-scale3d 0.1
```

## 9. 결과 보기

```bash
MAPMAKER_GS_PORT=8082 \
  bash $MAPMAKER_ROOT/scripts/start-mapmaker-gs-viewer.sh \
  "$GS_RESULT_DIR/ckpts/ckpt_7999_rank0.pt"
```

RunPod의 8082 HTTP 프록시로 접속합니다. 뷰어의 `Load trajectory`에 `No existing paths found`가 표시되는 것은 정상입니다. 이 메뉴는 WorldGen 경로가 아니라 뷰어에서 별도로 저장한 카메라 경로를 읽습니다.

# 여러 장면 일괄 생성

설치와 모델 다운로드를 마친 뒤 다음 명령을 실행합니다. 실행 전에 GPU를 사용하는 뷰어와 별도 vLLM 서버를 종료하세요.

```bash
bash scripts/run-all-single-view.sh
```

기본 입력은 `inputs/images/<장면>/`이며, 각 폴더에서 파일명 순으로 첫 번째 이미지 한 장을 사용합니다. 출력은 `outputs/images/<장면>/`에 저장됩니다. 파노라마, 경로 생성·렌더링, WorldStereo/WorldMirror, 3DGS 데이터 생성, 8,000스텝 학습을 순서대로 실행하며 필요한 vLLM 서버를 자동으로 시작하고 종료합니다.

- 단계별 로그: `outputs/images/_batch_logs/`
- 완료 표시: `outputs/images/_batch_state/<장면>.<단계>.ok`
- 전체 완료 표시: `outputs/images/_batch_state/ALL_COMPLETE`

같은 명령을 다시 실행하면 완료 표시가 있는 단계를 건너뜁니다. 기존 파노라마와 최종 학습 체크포인트도 재사용합니다. 입력이나 설정을 바꿔 새로 생성할 때는 새 출력 디렉터리를 지정하세요.

```bash
MAPMAKER_BATCH_INPUT=/path/to/scenes \
MAPMAKER_BATCH_OUTPUT=/path/to/new-results \
MAPMAKER_MIN_FREE_GB=100 \
  bash scripts/run-all-single-view.sh
```

기본 여유 공간 기준은 100 GiB이며, 단계 시작 전에 이보다 적으면 중단합니다. 사용자 지정 출력의 장면 목록은 `show_gs.py`의 `--scene_root` 옵션으로 지정할 수 있습니다.

# WorldMirror만 실행

겹치는 이미지 디렉터리 또는 비디오를 입력으로 전달합니다.

```bash
bash $MAPMAKER_ROOT/scripts/run-worldmirror.sh $MAPMAKER_ROOT/my-images
```

출력 경로를 직접 지정할 수도 있습니다.

```bash
bash $MAPMAKER_ROOT/scripts/run-worldmirror.sh \
  $MAPMAKER_ROOT/my-images \
  $MAPMAKER_OUTPUT_DIR/my-scene
```

Gradio UI를 사용할 때는 RunPod에서 TCP 7860을 노출합니다.

```bash
bash $MAPMAKER_ROOT/scripts/start-worldmirror-ui.sh
```

# 중단 후 재개

- Stage 1과 2가 끝났다면 vLLM을 종료하고 Stage 3부터 실행합니다.
- Stage 3은 `--skip_exist`로 기존 비디오 생성을 건너뜁니다.
- 비디오가 모두 있으면 `--postprocess_only --nframe 21`로 정렬부터 재개합니다.
- Stage 4가 끝났다면 `$SCENE_DIR/gs_data/cameras.json`을 확인하고 Stage 5부터 실행합니다.
- Stage 5를 다시 돌릴 때는 기존 결과를 덮어쓰지 않도록 새 `--result_dir`을 사용합니다.

# 데이터 보관과 용량

Git에 포함되는 것은 소스, 스크립트와 패키지 목록뿐입니다. 다음 항목은 별도로 보관해야 합니다.

| 경로 | 내용 |
|---|---|
| `$MAPMAKER_CACHE_DIR/huggingface` | 모델 가중치와 Hugging Face 인증 |
| `$MAPMAKER_VENVS_DIR` | Python 실행 환경 |
| `$MAPMAKER_OUTPUT_DIR` | 비디오, 포인트 클라우드, 체크포인트, PLY/SPZ와 메시 |

모델 가중치, 토큰, 가상환경과 생성 결과는 용량 또는 보안 문제로 Git에 포함하지 않습니다. 소스 커밋만으로 기존 생성 결과가 복구되지는 않습니다. 중요한 결과는 별도 볼륨이나 객체 스토리지에 백업하세요.

# 문제 해결

- 메인 환경의 `uv pip check`는 검증된 설치에서도 `hf-gradio`와 `gradio-client` 선언 버전 불일치, `decord` 플랫폼 메타데이터 경고를 표시합니다. 핵심 import와 MP4 디코딩은 검증했으며, vLLM 환경의 `uv pip check`는 통과했습니다.
- `libcudart.so.13 not found`: vLLM을 직접 실행하지 말고 `scripts/start-mapmaker-vllm.sh`를 사용합니다.
- Stage 3 OOM: vLLM이 종료됐는지 `nvidia-smi`로 확인합니다.
- 다른 GPU에서 CUDA extension 오류: `TORCH_CUDA_ARCH_LIST`를 GPU에 맞추고 FlashAttention과 gsplat을 재빌드합니다.
- Hugging Face gated model 오류: `facebook/sam3` 승인을 확인하고 `hf auth login`을 다시 실행합니다.
- 기존 성공 환경에서는 패키지를 일괄 업그레이드하지 말고 새 venv에서 먼저 시험합니다.
- `git clean -fdx`는 캐시되지 않은 빌드 의존성을 지울 수 있으므로 실행하지 않습니다.

# Upstream 및 라이선스

이 fork는 [Tencent-Hunyuan/HY-World-2.0](https://github.com/Tencent-Hunyuan/HY-World-2.0)을 기반으로 합니다. 원본 저작권, 모델 사용 조건, 라이선스와 인용 방법은 [License.txt](License.txt)와 [원본 README](README_UPSTREAM.md)를 따릅니다.

# 원본 Gaussian 객체 편집 — A_MARCEAU

학습 원본 Gaussian의 외관을 보존하면서 객체별 변환·복제·삭제를 지원하는 Blender 4.5 장면 생성 경로는 [Gaussian 객체 편집 안내](docs/gaussian-editable-scene.md)를 참고하세요. 실행은 `bash scripts/run-gaussian-object-scene.sh`, 생성된 장면 열기는 `bash scripts/start-blender-editable.sh`입니다. 모델·입력·Blender와 애드온 준비가 필요합니다.

현재 검증 대상은 A_MARCEAU입니다. 일반 폴리곤/UV 메시가 아니며 작은 물체와 가려진 경계에는 자동 분리 오차가 남습니다.
