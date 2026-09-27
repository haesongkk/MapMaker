"""Deployment paths; model storage is independent of code and run storage."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "experiments/image_first_scene_object_benchmark"
MODEL_ROOT = Path(os.environ.get("MAPMAKER_MODEL_ROOT", ROOT)).resolve()


def configured(name, default):
    return Path(os.environ.get(name, default)).expanduser().resolve()


SAM3D_REPO = configured("SAM3D_REPO", BENCH / "model_setup/sam3d_objects/repo")
SAM3D_CHECKPOINT = configured(
    "MAPMAKER_SAM3D_CHECKPOINT",
    MODEL_ROOT / "sam3d/pipeline.yaml" if "MAPMAKER_MODEL_ROOT" in os.environ
    else SAM3D_REPO / "checkpoints/hf/pipeline.yaml",
)
RAM_CHECKPOINT = configured(
    "MAPMAKER_RAM_CHECKPOINT", MODEL_ROOT / "checkpoints/ram_plus_swin_large_14m.pth"
)
SAM3_CHECKPOINT = configured(
    "MAPMAKER_SAM3_CHECKPOINT", MODEL_ROOT / "sam3/sam3.pt"
    if "MAPMAKER_MODEL_ROOT" in os.environ else
    ROOT.parent / ".cache/huggingface/hub/models--facebook--sam3/snapshots/3c879f39826c281e95690f02c7821c4de09afae7/sam3.pt",
)
DINO_PROVENANCE = configured(
    "MAPMAKER_DINO_PROVENANCE", MODEL_ROOT / ".runtime/sam3d-recovery/dinov2-restoration.json"
)
# Keep the venv executable path: resolving its symlink launches the base Python
# without the venv's site-packages on Linux.
VISION_PYTHON = Path(os.environ.get(
    "MAPMAKER_VISION_PYTHON", ROOT / ".venv-vision/bin/python"
)).expanduser().absolute()
