"""Approximate source-view silhouette audit; diagnostic only, never deletes meshes.

Full mesh silhouettes include hidden surfaces and occluded parts. Consequently
outside-mask pixels are not automatically errors or grounds for suppression.
"""
import argparse
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
import trimesh
from mapmaker.scene_geometry import triangles
from mapmaker.scene_run import read, write
from mapmaker.scene_vanishing import fit_camera


def audit(run):
    meta = read(run/'scene_metadata.json')
    points = np.load(run/meta['pointmap']['asset'])['points']
    camera = fit_camera(points)
    if not camera['accepted']:
        return dict(accepted=False, camera=camera)
    height, width = points.shape[:2]
    ratio = min(1., 192/max(height, width))
    shape = (max(1, round(width*ratio)), max(1, round(height*ratio)))
    projection = np.asarray(camera['matrix'])
    inverse = np.linalg.inv(meta['placement']['common_transform'])
    scene = trimesh.load(run/meta['scene_asset'], force='scene', process=False)
    rows = []
    for obj in meta['objects']:
        if obj['status'] != 'generated':
            continue
        faces = triangles(scene, obj['id'])
        faces = faces @ inverse[:3, :3].T + inverse[:3, 3]
        finite = np.isfinite(faces).all((1, 2)) & (abs(faces[..., 2]).min(1) > 1e-6)
        # Ignore camera-plane crossings rather than inventing a near clip.
        finite &= (faces[..., 2].min(1)*faces[..., 2].max(1)) > 0
        faces = faces[finite]
        uv = (faces/faces[..., 2, None]) @ projection.T
        uv = uv[..., :2]*ratio
        inside = (uv.max(1) >= 0).all(1) & (uv.min(1) < np.array(shape)).all(1)
        canvas = Image.new('1', shape)
        draw = ImageDraw.Draw(canvas)
        for face in uv[inside]:
            draw.polygon([tuple(v) for v in face], fill=1)
        predicted = np.asarray(canvas, bool)
        mask = np.asarray(Image.open(run/obj['mask']).convert('L').resize(shape, Image.Resampling.NEAREST)) > 0
        intersection = int((predicted & mask).sum())
        rows.append(dict(object_id=obj['id'], mask_pixels=int(mask.sum()),
            silhouette_pixels=int(predicted.sum()),
            mask_covered_fraction=intersection/max(1, int(mask.sum())),
            silhouette_outside_mask_fraction=int((predicted & ~mask).sum())/max(1, int(predicted.sum())),
            silhouette_iou=intersection/max(1, int((predicted | mask).sum()))))
    return dict(accepted=True, camera=camera, diagnostic_resolution=shape, objects=rows,
        limitations=['No occlusion correction or depth testing',
                    'Hidden geometry may legitimately project outside visible instance masks',
                    'Coarse rasterization and camera-plane crossings limit accuracy'],
        changes_applied=False, automatic_quality_pass=None)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.run)
    write(args.output, report)
    for row in report.get('objects', []):
        print(row, flush=True)
