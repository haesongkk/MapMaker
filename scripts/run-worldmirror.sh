#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 INPUT_PATH [OUTPUT_PATH]" >&2
  exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$script_dir/mapmaker-env.sh"

input_path=$1
output_path=${2:-$MAPMAKER_OUTPUT_DIR/worldmirror-$(date -u +%Y%m%dT%H%M%SZ)}

python -m hyworld2.worldrecon.pipeline \
  --input_path "$input_path" \
  --strict_output_path "$output_path" \
  --enable_bf16 \
  --no_interactive

echo "Results: $output_path"
