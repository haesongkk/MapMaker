"""One resident model shared by initial and expanded reconstruction policies."""
import sys
from .runtime_paths import SAM3D_CHECKPOINT
from .scene_run import SAM3D_REPO

_model = None


def model():
    global _model
    if _model is None:
        sys.path.insert(0, str(SAM3D_REPO / 'notebook'))
        from inference import Inference
        _model = Inference(str(SAM3D_CHECKPOINT), compile=False)
    return _model


def prepare():
    import torch
    from loguru import logger
    torch.cuda.reset_peak_memory_stats()
    logger.remove()
    logger.add(sys.stderr)
    instance = model()
    from inference import load_image
    return instance, load_image
