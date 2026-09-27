#!/usr/bin/env bash
set -euo pipefail
cd /opt/mapmaker
# Preserve the successful vision base (Python 3.12.3 / torch 2.8.0+cu128).
python -c 'import torch,sys; assert sys.version_info[:3] == (3,12,3); assert torch.__version__ == "2.8.0+cu128"'
python -m pip install --break-system-packages uv==0.9.0
uv venv --python "$(command -v python)" --system-site-packages .venv-vision
uv pip install --python .venv-vision/bin/python --no-deps -r configs/serverless/vision-overlay.txt
git clone https://github.com/facebookresearch/sam3.git /opt/sam3
git -C /opt/sam3 checkout 2345a4ad109ac29c569da749c91d84f10dc08c40
git clone https://github.com/xinyu1205/recognize-anything.git /opt/ram
git -C /opt/ram checkout 7cb804a8609e9f4b1a50b7f31436d2df40bb9481
uv pip install --python .venv-vision/bin/python --no-deps -e /opt/sam3 -e /opt/ram

micromamba env create -y -p /opt/sam3d-base -f configs/serverless/sam3d-conda.yml
uv venv --python /opt/sam3d-base/bin/python --seed .venv-sam3d
.venv-sam3d/bin/python -c 'import sys; assert sys.version_info[:3] == (3,11,0)'
git clone https://github.com/facebookresearch/sam-3d-objects.git /opt/sam3d
git -C /opt/sam3d checkout f91db411c50efee93d8db7aeb323885650f6f722
export CUDA_HOME=/opt/sam3d-base CONDA_PREFIX=/opt/sam3d-base
export PATH="/opt/mapmaker/.venv-sam3d/bin:$CUDA_HOME/bin:$PATH"
export CPATH="$CUDA_HOME/targets/x86_64-linux/include"
export LIBRARY_PATH="$CUDA_HOME/targets/x86_64-linux/lib"
export LD_LIBRARY_PATH="$LIBRARY_PATH:${LD_LIBRARY_PATH:-}"
export CC="$CUDA_HOME/bin/x86_64-conda-linux-gnu-gcc" CXX="$CUDA_HOME/bin/x86_64-conda-linux-gnu-g++"
export CUB_HOME="$CUDA_HOME/include" MAX_JOBS=4 FORCE_CUDA=1
export TORCH_CUDA_ARCH_LIST='8.0;8.6;8.9+PTX'
uv pip install --python .venv-sam3d/bin/python --no-deps --index-url https://download.pytorch.org/whl/cu121 \
    torch==2.5.1+cu121 torchvision==0.20.1+cu121 torchaudio==2.5.1+cu121
uv pip install --python .venv-sam3d/bin/python --no-deps \
    setuptools==69.5.1 hatchling==1.32.4 hatch-requirements-txt==0.4.1 ninja==1.13.2 \
    packaging==24.2 editables==0.6 wheel==0.48.0 numpy==1.26.4 pip==26.2.1 appdirs==1.4.4
python - <<'PY'
from pathlib import Path
lines = Path('configs/sam3d/successful-runtime-freeze.txt').read_text().splitlines()
special = ('torch==', 'torchvision==', 'torchaudio==', 'flash-attn==', 'kaolin==', 'nvidia-pyindex==', '-e ', 'pytorch3d @', 'gsplat @', 'moge @', 'utils3d @')
Path('/opt/sam3d-base.txt').write_text('\n'.join(x for x in lines if x and not x.startswith(special))+'\n')
Path('/opt/sam3d-native.txt').write_text('\n'.join(x for x in lines if x.startswith(('pytorch3d @', 'gsplat @', 'moge @', 'utils3d @', 'flash-attn==')))+'\n')
PY
uv pip install --python .venv-sam3d/bin/python --no-deps --no-build-isolation -r /opt/sam3d-base.txt
uv pip install --python .venv-sam3d/bin/python --no-deps \
    --find-links https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.5.1_cu121.html kaolin==0.17.0
uv pip install --python .venv-sam3d/bin/python --no-deps --no-build-isolation -r /opt/sam3d-native.txt
uv pip install --python .venv-sam3d/bin/python --no-deps --no-build-isolation -e /opt/sam3d
.venv-sam3d/bin/python /opt/sam3d/patching/hydra
mkdir -p /opt/mapmaker-models/.runtime/sam3d-torch/hub
git clone https://github.com/facebookresearch/dinov2.git /opt/mapmaker-models/.runtime/sam3d-torch/hub/facebookresearch_dinov2_main
git -C /opt/mapmaker-models/.runtime/sam3d-torch/hub/facebookresearch_dinov2_main checkout 7764ea0f912e53c92e82eb78a2a1631e92725fc8
