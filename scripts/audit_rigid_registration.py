"""Read-only rigid-fit proposals on real recovered meshes; never applies them."""
import argparse
from pathlib import Path
import numpy as np
from PIL import Image
import trimesh
from mapmaker.scene_geometry import triangles
from mapmaker.scene_ownership import composite_residuals
from mapmaker.scene_registration import propose_rigid_transform, propose_similarity_transform
from mapmaker.scene_run import read, write, sha


def main(source, output, similarity=False):
    meta = read(source/'scene_metadata.json')
    digest = sha(source/'scene.glb')
    points = np.load(source/meta['pointmap']['asset'])['points']
    scene = trimesh.load(source/'scene.glb', force='scene', process=False)
    objects = [o for o in meta['objects'] if o['status'] == 'generated']
    masks = {o['id']: np.asarray(Image.open(source/o['mask']).resize(points.shape[1::-1], Image.Resampling.NEAREST)) > 0 for o in objects}
    residuals = composite_residuals(masks, points)
    reports = []
    for obj in objects:
        oid = obj['id']
        cloud = points[residuals[oid][0] if oid in residuals else masks[oid]]
        cloud = cloud[np.isfinite(cloud).all(-1) & (np.linalg.norm(cloud,axis=1)>1e-6)]
        cloud = trimesh.transform_points(cloud, np.asarray(meta['placement']['common_transform']))
        faces = triangles(scene, oid)
        mesh = trimesh.Trimesh(faces.reshape(-1,3), np.arange(len(faces)*3).reshape(-1,3), process=True)
        transform, report = (propose_similarity_transform if similarity else propose_rigid_transform)(mesh, cloud)
        reports.append(dict(object_id=oid, proposed=transform is not None, **report))
        print(dict(object_id=oid, proposed=transform is not None, reason=report['reason']), flush=True)
        write(output, dict(source=str(source), source_scene_sha256=digest, proposals=reports, source_unchanged=sha(source/'scene.glb')==digest,
            scope='Withheld observed-depth fit only; collision, image alignment, support and quality not certified'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--similarity', action='store_true')
    args = parser.parse_args()
    main(args.source, args.output, args.similarity)
