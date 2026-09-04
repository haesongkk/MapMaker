#!/usr/bin/env bash

# Resolve every persistent path from the repository location.
_mapmaker_script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
export MAPMAKER_ROOT="$(cd -- "$_mapmaker_script_dir/.." && pwd -P)"
unset _mapmaker_script_dir

export MAPMAKER_TOOLS_DIR="$MAPMAKER_ROOT/.tools"
export MAPMAKER_VENVS_DIR="$MAPMAKER_ROOT/.venvs"
export MAPMAKER_MAIN_VENV="$MAPMAKER_VENVS_DIR/main"
export MAPMAKER_VLLM_VENV="$MAPMAKER_VENVS_DIR/vllm"
export MAPMAKER_CACHE_DIR="$MAPMAKER_ROOT/.cache"
export MAPMAKER_OUTPUT_DIR="$MAPMAKER_ROOT/outputs"

export VIRTUAL_ENV="$MAPMAKER_MAIN_VENV"
export PATH="$VIRTUAL_ENV/bin:$MAPMAKER_TOOLS_DIR/bin:/usr/local/cuda/bin:$PATH"
export HF_HOME="$MAPMAKER_CACHE_DIR/huggingface"
export HUGGINGFACE_HUB_CACHE="$HF_HOME/hub"
export TORCH_HOME="$MAPMAKER_CACHE_DIR/torch"
export TORCH_EXTENSIONS_DIR="$MAPMAKER_CACHE_DIR/torch_extensions"
export UV_CACHE_DIR="$MAPMAKER_CACHE_DIR/uv"
export UV_DATA_DIR="$MAPMAKER_TOOLS_DIR/uv-data"
export UV_PYTHON_INSTALL_DIR="$MAPMAKER_TOOLS_DIR/python"
export UV_TOOL_DIR="$MAPMAKER_TOOLS_DIR/uv-tools"
export UV_TOOL_BIN_DIR="$MAPMAKER_TOOLS_DIR/bin"
export XDG_CACHE_HOME="$MAPMAKER_CACHE_DIR/xdg"
export PIP_CACHE_DIR="$MAPMAKER_CACHE_DIR/pip"
export TRITON_CACHE_DIR="$MAPMAKER_CACHE_DIR/triton"
export CUDA_CACHE_PATH="$MAPMAKER_CACHE_DIR/cuda"
export CUPY_CACHE_DIR="$MAPMAKER_CACHE_DIR/cupy"
export MPLCONFIGDIR="$MAPMAKER_CACHE_DIR/matplotlib"
export HF_ASSETS_CACHE="$MAPMAKER_CACHE_DIR/huggingface/assets"
export TMPDIR="$MAPMAKER_ROOT/.tmp"
export CUDA_HOME=/usr/local/cuda
export PYTHONPATH="$MAPMAKER_ROOT${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p \
  "$MAPMAKER_TOOLS_DIR/bin" \
  "$MAPMAKER_VENVS_DIR" \
  "$HF_HOME" \
  "$MAPMAKER_CACHE_DIR/vllm" \
  "$TORCH_HOME" \
  "$TORCH_EXTENSIONS_DIR" \
  "$UV_CACHE_DIR" \
  "$UV_DATA_DIR" \
  "$UV_PYTHON_INSTALL_DIR" \
  "$UV_TOOL_DIR" \
  "$XDG_CACHE_HOME" \
  "$PIP_CACHE_DIR" \
  "$TRITON_CACHE_DIR" \
  "$CUDA_CACHE_PATH" \
  "$CUPY_CACHE_DIR" \
  "$MPLCONFIGDIR" \
  "$HF_ASSETS_CACHE" \
  "$TMPDIR" \
  "$MAPMAKER_OUTPUT_DIR"

cd "$MAPMAKER_ROOT"
