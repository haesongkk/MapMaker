# Build with: docker build --platform linux/amd64 -f deploy/runpod/Dockerfile .
# No model weights or credentials enter the image.
FROM mambaorg/micromamba:2.3.3@sha256:e583f8e151fd1ebbc78b05cf4feb37ddbb518892dbabf6c0c03ea8ad613bc519 AS mamba
FROM runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404@sha256:4d1721e62b56d345c83b4fd6090664be6daf9312caab5b2e76f23d8231941851 AS builder
COPY --from=mamba /bin/micromamba /usr/local/bin/micromamba
WORKDIR /opt/mapmaker
COPY configs configs
COPY deploy/runpod/build_runtime.sh /opt/build_runtime.sh
RUN bash /opt/build_runtime.sh
COPY mapmaker mapmaker
COPY scripts scripts
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra serverless --extra remote && \
    mkdir -p .runtime/sam3d-recovery && \
    .venv-sam3d/bin/python scripts/sam3d_runtime_audit.py

# Export only installed environments and pinned sources. The builder's conda/uv
# downloads and native compiler intermediates are not part of the runtime image.
FROM runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404@sha256:4d1721e62b56d345c83b4fd6090664be6daf9312caab5b2e76f23d8231941851
WORKDIR /opt/mapmaker
COPY --from=builder /opt/mapmaker /opt/mapmaker
COPY --from=builder /opt/sam3d-base /opt/sam3d-base
COPY --from=builder /opt/sam3d /opt/sam3d
COPY --from=builder /opt/sam3 /opt/sam3
COPY --from=builder /opt/ram /opt/ram
COPY --from=builder /opt/mapmaker-models /opt/mapmaker-models
ENV MAPMAKER_BACKEND=local \
    SAM3D_REPO=/opt/sam3d \
    SAM3D_PYTHON=/opt/mapmaker/.venv-sam3d/bin/python \
    MAPMAKER_VISION_PYTHON=/opt/mapmaker/.venv-vision/bin/python \
    MAPMAKER_SAM3D_BASE=/opt/sam3d-base \
    CUDA_HOME=/opt/sam3d-base \
    MAPMAKER_MODEL_ROOT=/opt/mapmaker-models \
    TORCH_HOME=/opt/mapmaker-models/.runtime/sam3d-torch \
    HF_HOME=/opt/mapmaker-models/huggingface \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    MAPMAKER_SCRATCH=/tmp/mapmaker-jobs \
    OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 PYTHONUNBUFFERED=1
RUN .venv-sam3d/bin/python scripts/sam3d_runtime_audit.py && \
    .venv-sam3d/bin/python -c 'import torch, flash_attn, pytorch3d._C; print("SAM3D native imports OK", torch.__version__)' && \
    .venv-vision/bin/python -c 'import torch, ram, sam3; print("Vision imports OK", torch.__version__)'
ENTRYPOINT ["/opt/mapmaker/.venv/bin/python", "-m", "mapmaker.serverless_worker"]
