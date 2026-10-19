"""Read-only mesh/source-depth plane comparison; never changes a scene."""
import argparse
from pathlib import Path
import numpy as np
from PIL import Image
import trimesh
from mapmaker.scene_run import read, write


def plane(points):
    points = points[np.isfinite(points).all(-1)]
    if len(points) < 64:
        return None
    points = points[np.linspace(0, len(points)-1, min(4000, len(points))).astype(int)]
    center = np.median(points, axis=0)
    eig, vectors = np.linalg.eigh(np.cov((points-center).T))
    normal = vectors[:, 0]
    scale = float(np.linalg.norm(np.ptp(points, axis=0)))
    if scale < 1e-9:
        return None
    return dict(center=center.tolist(), normal=normal.tolist(), scale=scale,
        normalized_residual_p95=float(np.quantile(abs((points-center)@normal), .95)/scale),
        second_axis_fraction=float(eig[1]/max(eig[2], 1e-12)), samples=len(points))


def audit(run):
    meta = read(run/'scene_metadata.json')
    points = np.load(run/meta['pointmap']['asset'])['points']
    height, width = points.shape[:2]
    rows = []
    for obj in meta['objects']:
        if obj['status'] != 'generated':
            continue
        mask = np.asarray(Image.open(run/obj['mask']).resize((width, height), Image.Resampling.NEAREST)) > 0
        cloud = points[mask]
        cloud = cloud[np.isfinite(cloud).all(-1) & (np.linalg.norm(cloud, axis=-1) > 1e-6)]
        observed = plane(cloud)
        asset = trimesh.load(run/obj['asset'], force='scene', process=False)
        matrix = np.asarray(obj.get('placement', {}).get('original_matrix', obj['transform']['matrix']))
        chunks = []
        for node in asset.graph.nodes_geometry:
            transform, geometry = asset.graph[node]
            vertices = asset.geometry[geometry].vertices
            chunks.append(trimesh.transform_points(vertices[::max(1, len(vertices)//4000)], matrix@transform))
        generated = plane(np.concatenate(chunks))
        row = dict(object_id=obj['id'], observed=observed, generated=generated)
        if observed and generated:
            dot = float(np.dot(observed['normal'], generated['normal']))
            row['normal_angle_degrees'] = float(np.degrees(np.arccos(np.clip(abs(dot), 0, 1))))
            row['signed_plane_offset'] = float(np.dot(np.subtract(generated['center'], observed['center']), observed['normal']))
            row['both_planar'] = all(p['normalized_residual_p95'] < .02 and p['second_axis_fraction'] > .03 for p in (observed, generated))
        rows.append(row)
        print({k:v for k,v in row.items() if k not in ('observed', 'generated')}, flush=True)
    return dict(changes_applied=False, uses_object_names=False, objects=rows,
        limitation='Observed monocular depth is not ground truth; planarity alone does not authorize replacement or motion')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    write(args.output, audit(args.run))
