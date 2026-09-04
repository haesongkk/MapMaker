#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$script_dir/mapmaker-env.sh"

exec python -m hyworld2.worldrecon.gradio_app \
  --host 0.0.0.0 \
  --port "${MAPMAKER_PORT:-7860}" \
  --enable_bf16
