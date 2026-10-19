"""Check source-view preservation before considering rigid-fit application."""
import argparse
from pathlib import Path
import numpy as np
from PIL import Image
import trimesh
from mapmaker.scene_geometry import triangles
from mapmaker.scene_projection import silhouette_evidence
from mapmaker.scene_run import read, write, sha


def main(source, proposals, output):
    digest = sha(source/'scene.glb')
    assert read(proposals)['source_scene_sha256'] == digest
    meta = read(source/'scene_metadata.json')
    scene = trimesh.load(source/'scene.glb', force='scene', process=False)
    points = np.load(source/meta['pointmap']['asset'])['points']
    inverse = np.linalg.inv(meta['placement']['common_transform'])
    objects = {o['id']: o for o in meta['objects']}
    reports = []
    for proposal in read(proposals)['proposals']:
        if not proposal['proposed']:
            continue
        oid = proposal['object_id']
        obj = objects[oid]
        faces = triangles(scene, oid)
        before_faces = trimesh.transform_points(faces.reshape(-1,3), inverse).reshape(-1,3,3)
        after_faces = trimesh.transform_points(faces.reshape(-1,3), inverse@np.asarray(proposal['transform'])).reshape(-1,3,3)
        mask = np.asarray(Image.open(source/obj['mask']).convert('L')) > 0
        before = silhouette_evidence(before_faces, points, mask)
        after = silhouette_evidence(after_faces, points, mask)
        compatible = (before['accepted'] and after['accepted']
            and after['silhouette_iou'] >= before['silhouette_iou']
            and after['mask_covered_fraction'] >= before['mask_covered_fraction'])
        reports.append(dict(object_id=oid, compatible=compatible, before=before, after=after))
        print(dict(object_id=oid, compatible=compatible, before=before.get('silhouette_iou'), after=after.get('silhouette_iou')), flush=True)
        write(output, dict(source_scene_sha256=digest, reports=reports, scope='Projection + independent depth evidence only; no collision certification'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--proposals', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    main(args.source, args.proposals, args.output)
