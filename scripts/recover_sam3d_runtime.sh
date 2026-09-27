#!/usr/bin/env bash
# Replay the final successful freeze, including the setuptools repair.
set -euo pipefail
source "$(dirname "$0")/sam3d_runtime_env.sh"
cd "$SAM3D_PROJECT_ROOT"
test "$(git -C "$SAM3D_REPO" rev-parse HEAD)" = f91db411c50efee93d8db7aeb323885650f6f722
test -f "$SAM3D_REPO/checkpoints/hf/pipeline.yaml"
if [ ! -x "$SAM3D_PYTHON" ]; then
  uv venv --python "$CONDA_PREFIX/bin/python" .venv-sam3d
fi
"$SAM3D_PYTHON" -c 'import sys; assert sys.version_info[:3] == (3,11,0), sys.version'
uv pip install --python "$SAM3D_PYTHON" --no-deps \
  --index-url https://download.pytorch.org/whl/cu121 \
  torch==2.5.1+cu121 torchvision==0.20.1+cu121 torchaudio==2.5.1+cu121
uv pip install --python "$SAM3D_PYTHON" --no-deps \
  setuptools==69.5.1 hatchling==1.32.4 hatch-requirements-txt==0.4.1 \
  ninja==1.13.2 packaging==24.2 editables==0.6 wheel==0.48.0 numpy==1.26.4 \
  pip==26.2.1 appdirs==1.4.4
"$SAM3D_PYTHON" - <<'PY'
from pathlib import Path
lines = Path('configs/sam3d/successful-runtime-freeze.txt').read_text().splitlines()
special = ('torch==', 'torchvision==', 'torchaudio==', 'flash-attn==', 'kaolin==', 'nvidia-pyindex==', '-e ', 'pytorch3d @', 'gsplat @', 'moge @', 'utils3d @')
# nvidia-pyindex is an index-configuration installer, not an inference library.
# Its setup hook edits user/system pip configuration; use explicit index URLs instead.
base = [line for line in lines if line and not line.startswith(special)]
native = [line for line in lines if line.startswith(('pytorch3d @', 'gsplat @', 'moge @', 'utils3d @', 'flash-attn=='))]
Path('.runtime/sam3d-recovery/base.txt').write_text('\n'.join(base) + '\n')
Path('.runtime/sam3d-recovery/native.txt').write_text('\n'.join(native) + '\n')
PY
uv pip install --python "$SAM3D_PYTHON" --no-deps --no-build-isolation \
  -r .runtime/sam3d-recovery/base.txt
uv pip install --python "$SAM3D_PYTHON" --no-deps \
  --find-links https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.5.1_cu121.html kaolin==0.17.0
bash scripts/build_sam3d_native.sh
uv pip install --python "$SAM3D_PYTHON" --no-deps --no-build-isolation -e "$SAM3D_REPO"
"$SAM3D_PYTHON" "$SAM3D_REPO/patching/hydra"
uv pip freeze --python "$SAM3D_PYTHON" > .runtime/sam3d-recovery/restored-freeze.txt
"$SAM3D_PYTHON" "$SAM3D_PROJECT_ROOT/scripts/sam3d_runtime_audit.py"
"$SAM3D_PYTHON" "$SAM3D_PROJECT_ROOT/scripts/sam3d_file_audit.py"
"$SAM3D_PYTHON" "$SAM3D_PROJECT_ROOT/scripts/sam3d_smoke.py"

# Restore the authorized, pinned official auxiliary dependency.
"$SAM3D_PYTHON" "$SAM3D_PROJECT_ROOT/scripts/recover_dinov2.py"
"$SAM3D_PYTHON" "$SAM3D_PROJECT_ROOT/scripts/sam3d_checkpoint_preflight.py"
