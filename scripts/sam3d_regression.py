"""Replay one frozen successful object through the unchanged official Inference API.

Run after sourcing scripts/sam3d_runtime_env.sh. Writes a separate run; never
changes the historical input, masks, meshes, or pose. This is a regression test,
not the production object extraction path.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'experiments/image_first_scene_object_benchmark'


def write(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from sam3d_checkpoint_preflight import check
    check()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    baseline = BASE / 'runs/sam3d/phase_c/main_living_room'
    repo = Path(os.environ['SAM3D_REPO'])
    sys.path.insert(0, str(repo / 'notebook'))
    from inference import Inference, load_image
    import torch
    import trimesh

    method = json.loads((baseline / 'segmentation/method.json').read_text())
    record = next(x for x in method['masks'] if x['slug'] == 'object_000_sofa')
    source = baseline / 'input/rgb.png'
    mask_path = baseline / record['mask']
    assert sha(mask_path) == record['mask_sha256']
    config = repo / 'checkpoints/hf/pipeline.yaml'
    original_load = json.loads((BASE / 'execution/sam3d_local_model_load.json').read_text())
    assert sha(config) == original_load['pipeline_sha256']
    provenance = dict(input=str(source), mask=str(mask_path), input_sha256=sha(source),
                      mask_sha256=sha(mask_path), pipeline_sha256=sha(config),
                      seed=42, compile=False, python=sys.version, torch=torch.__version__,
                      cuda=torch.version.cuda, gpu=torch.cuda.get_device_name(0))
    write(output / 'provenance.json', provenance)
    start = time.monotonic()
    inference = Inference(str(config), compile=False)
    provenance['load_seconds'] = time.monotonic() - start
    start = time.monotonic()
    result = inference(load_image(str(source)), np.asarray(Image.open(mask_path)) > 0, seed=42)
    if result.get('glb') is None:
        raise RuntimeError('Official Inference returned no mesh')
    result['glb'].export(str(output / 'mesh.glb'))
    pose = {key: result[key].detach().cpu().tolist() for key in ('rotation','translation','scale')}
    write(output / 'pose.json', pose)
    result['gs'].save_ply(str(output / 'splat.ply'))
    provenance['inference_export_seconds'] = time.monotonic() - start
    write(output / 'provenance.json', provenance)
    old_dir = baseline / 'reconstruction/object_000_sofa'
    old_pose = json.loads((old_dir / 'pose.json').read_text())
    old_mesh = trimesh.load(old_dir / 'mesh.glb', force='scene', process=False)
    new_mesh = trimesh.load(output / 'mesh.glb', force='scene', process=False)
    geometry = list(new_mesh.geometry.values())
    healthy = all(len(m.vertices) and len(m.faces) and np.isfinite(m.vertices).all() for m in geometry)
    deltas = {key: float(np.max(np.abs(np.asarray(pose[key])-np.asarray(old_pose[key])))) for key in pose}
    ratios = (new_mesh.extents / old_mesh.extents).tolist()
    comparison = dict(mesh_valid=bool(geometry and healthy), old_bounds=old_mesh.bounds.tolist(),
                      new_bounds=new_mesh.bounds.tolist(), extent_ratios=ratios,
                      old_pose=old_pose, new_pose=pose, pose_max_abs_differences=deltas,
                      old_mesh_sha256=sha(old_dir / 'mesh.glb'), new_mesh_sha256=sha(output / 'mesh.glb'),
                      visual_review='pending')
    write(output / 'comparison.json', comparison)
    assert comparison['mesh_valid']
    assert all(np.isfinite(np.asarray(v)).all() for v in pose.values())
    assert (np.asarray(pose['scale']) > 0).all()
    print(json.dumps(comparison, indent=2))


if __name__ == '__main__':
    main()
