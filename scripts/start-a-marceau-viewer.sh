#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$script_dir/mapmaker-env.sh"
exec "$script_dir/start-mapmaker-gs-viewer.sh" \
  "$MAPMAKER_OUTPUT_DIR/a-marceau-worldgen-gs/ckpts/ckpt_7999_rank0.pt"
