#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$script_dir/mapmaker-env.sh"

# Port 8081 is occupied by the base RunPod nginx service in this image.
viewer_port="${MAPMAKER_GS_PORT:-8082}"
checkpoint="${1:-$MAPMAKER_OUTPUT_DIR/images/A_MARCEAU/gs/ckpts/ckpt_7999_rank0.pt}"

if [[ ! -f "$checkpoint" ]]; then
  echo "Checkpoint not found: $checkpoint" >&2
  exit 1
fi

cd "$MAPMAKER_ROOT/hyworld2/worldgen"
exec python show_gs.py \
  --scene_root "$MAPMAKER_OUTPUT_DIR/images" \
  --port "$viewer_port" \
  --gpu_id 0 \
  --ckpt "$checkpoint"
