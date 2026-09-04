#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$script_dir/mapmaker-env.sh"

MODEL_NAME=${MAPMAKER_VLM_MODEL:-Qwen/Qwen3-VL-8B-Instruct}
PORT=${MAPMAKER_VLM_PORT:-8000}
GPU_UTIL=${MAPMAKER_VLM_GPU_UTIL:-0.50}

export VIRTUAL_ENV="$MAPMAKER_VLLM_VENV"
export PATH="$MAPMAKER_VLLM_VENV/bin:$PATH"
export VLLM_CACHE_ROOT="$MAPMAKER_CACHE_DIR/vllm"
export VLLM_USE_FLASHINFER_SAMPLER=0
export LD_LIBRARY_PATH="$MAPMAKER_VLLM_VENV/lib/python3.12/site-packages/nvidia/cu13/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

exec "$MAPMAKER_VLLM_VENV/bin/vllm" serve "$MODEL_NAME" \
  --served-model-name "$MODEL_NAME" \
  --host 0.0.0.0 \
  --port "$PORT" \
  --tensor-parallel-size 1 \
  --max-model-len 32768 \
  --gpu-memory-utilization "$GPU_UTIL" \
  --trust-remote-code
