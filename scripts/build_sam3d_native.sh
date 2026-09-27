#!/usr/bin/env bash
# Build scratch may be volatile; every installed package and retained wheel is persistent.
set -euo pipefail
source "$(dirname "$0")/sam3d_runtime_env.sh"
cd "$SAM3D_PROJECT_ROOT"
# This wheel was already built from the recorded release; reuse the persistent cache.
uv pip install --python "$SAM3D_PYTHON" --no-deps --no-build-isolation flash-attn==2.8.3
export SAM3D_BUILD_SCRATCH=/dev/shm/mapmaker-sam3d-build
"$SAM3D_PYTHON" - <<'PY'
from pathlib import Path
import os, shutil
root = Path(os.environ['SAM3D_PROJECT_ROOT']) if 'SAM3D_PROJECT_ROOT' in os.environ else Path.cwd()
scratch = Path(os.environ['SAM3D_BUILD_SCRATCH'])
source = root / '.venv-sam3d/lib/python3.11/site-packages/torch'
shadow = scratch / 'python/torch'
shadow.mkdir(parents=True, exist_ok=True)
for p in source.iterdir():
    if p.name != 'include' and not (shadow / p.name).exists():
        (shadow / p.name).symlink_to(p, target_is_directory=p.is_dir())
cuda = Path(os.environ['CONDA_PREFIX'])
(scratch / 'cuda').mkdir(exist_ok=True)
for p in cuda.iterdir():
    if p.name != 'include' and not (scratch / 'cuda' / p.name).exists():
        (scratch / 'cuda' / p.name).symlink_to(p, target_is_directory=p.is_dir())
if not (scratch / 'cuda/lib64').exists():
    (scratch / 'cuda/lib64').symlink_to(cuda / 'targets/x86_64-linux/lib', target_is_directory=True)
if not (scratch / '.headers-ready').exists():
    print('Copying unchanged compiler headers to memory scratch', flush=True)
    shutil.copytree(source / 'include', shadow / 'include', symlinks=True, dirs_exist_ok=True)
    shutil.copytree(cuda / 'targets/x86_64-linux/include', scratch / 'cuda/include', symlinks=True, dirs_exist_ok=True)
    if not (scratch / 'cuda/include/cub').exists():
        shutil.copytree(cuda / 'include/cub', scratch / 'cuda/include/cub', symlinks=True)
    (scratch / '.headers-ready').touch()
# Match PyTorch3D's original CONDA_PREFIX/include CUB selection exactly.
if not (scratch / '.cub-ready').exists():
    shutil.copytree(cuda / 'include/cub', scratch / 'cub/cub', symlinks=True, dirs_exist_ok=True)
    (scratch / '.cub-ready').touch()
lines = (root / '.runtime/sam3d-recovery/native.txt').read_text().splitlines()
(root / '.runtime/sam3d-recovery/native-git.txt').write_text('\n'.join(x for x in lines if not x.startswith('flash-attn')) + '\n')
PY
export PYTHONPATH="$SAM3D_BUILD_SCRATCH/python${PYTHONPATH:+:$PYTHONPATH}"
export CUDA_HOME="$SAM3D_BUILD_SCRATCH/cuda"
export CPATH="$CUDA_HOME/include"
export CUB_HOME="$SAM3D_BUILD_SCRATCH/cub"
export TMPDIR="$SAM3D_BUILD_SCRATCH/tmp"
export UV_CACHE_DIR="$SAM3D_BUILD_SCRATCH/uv"
# Force real copies across filesystems; the persistent venv must never point into RAM.
export UV_LINK_MODE=copy
mkdir -p "$TMPDIR" "$UV_CACHE_DIR"
"$SAM3D_PYTHON" - <<'PY'
import torch
from torch.utils.cpp_extension import include_paths
print('Unchanged build torch:', torch.__version__, torch.__file__, flush=True)
print('Build includes:', include_paths(cuda=True), flush=True)
assert torch.__version__ == '2.5.1+cu121'
assert include_paths()[0].startswith('/dev/shm/mapmaker-sam3d-build/')
PY
uv pip install --python "$SAM3D_PYTHON" --no-deps --no-build-isolation \
  -r .runtime/sam3d-recovery/native-git.txt
"$SAM3D_PYTHON" - <<'PY'
from pathlib import Path
import hashlib, json, os, shutil
out = Path('.runtime/sam3d-recovery/wheels')
out.mkdir(exist_ok=True)
rows = []
for p in Path(os.environ['UV_CACHE_DIR']).rglob('*.whl'):
    dest = out / p.name
    shutil.copy2(p, dest)
    rows.append({'file': str(dest), 'sha256': hashlib.sha256(dest.read_bytes()).hexdigest()})
Path('.runtime/sam3d-recovery/native-build.json').write_text(json.dumps({
    'requirements': Path('.runtime/sam3d-recovery/native-git.txt').read_text(),
    'scratch': os.environ['SAM3D_BUILD_SCRATCH'], 'persistent_environment': os.environ['SAM3D_PYTHON'],
    'install_link_mode': 'copy', 'versions_changed': False, 'wheels': rows}, indent=2))
PY
