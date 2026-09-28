"""Read-only checkpoint check; recover missing official DINO files with recover_dinov2.py."""
from pathlib import Path
import json
import os

ROOT = Path(__file__).resolve().parents[1]


def check():
    repo = Path(os.environ.get('SAM3D_REPO', ROOT / 'experiments/image_first_scene_object_benchmark/model_setup/sam3d_objects/repo'))
    checkpoint = Path(os.environ.get('MAPMAKER_SAM3D_CHECKPOINT', Path(os.environ['MAPMAKER_MODEL_ROOT']) / 'sam3d/pipeline.yaml' if 'MAPMAKER_MODEL_ROOT' in os.environ else repo / 'checkpoints/hf/pipeline.yaml'))
    torch_home = Path(os.environ.get('TORCH_HOME', Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'torch'))
    hub = torch_home / 'hub'
    required = {
        'pipeline': checkpoint,
        'dino_torch_hub_source': hub / 'facebookresearch_dinov2_main/hubconf.py',
        'dino_pretrained_weight': hub / 'checkpoints/dinov2_vitl14_reg4_pretrain.pth',
    }
    for name in ('ss_generator', 'ss_decoder', 'slat_generator', 'slat_decoder_mesh', 'slat_decoder_gs', 'slat_decoder_gs_4'):
        required[name] = checkpoint.parent / (name + '.ckpt')
    missing = {name: str(path) for name, path in required.items() if not path.is_file()}
    report = {'passed': not missing, 'torch_home': str(torch_home),
              'required': {name: str(path) for name, path in required.items()},
              'missing': missing, 'official_dependency_restoration_authorized': True,
              'note': 'Use scripts/recover_dinov2.py for the pinned official source and original official weight. Import success is not reconstruction success.'}
    output = ROOT / '.runtime/sam3d-recovery/checkpoint-preflight.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    if missing:
        raise RuntimeError('Checkpoint preflight blocked before inference: ' + json.dumps(missing))
    return report


if __name__ == '__main__':
    print(json.dumps(check(), indent=2))
