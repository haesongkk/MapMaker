#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/sam3d_runtime_env.sh"
cd "$SAM3D_PROJECT_ROOT"
exec "$SAM3D_PYTHON" -m mapmaker.scene_reconstruct "$@"
