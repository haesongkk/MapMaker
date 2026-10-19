"""Read-only search for source-preserving overlap repairs in any saved scene.

Requires the geometry extra. Reports candidates, never edits the input scene or
claims full quality; support and visual validation remain separate.
"""
import argparse
from pathlib import Path
import numpy as np
import trimesh
from PIL import Image

from mapmaker.scene_run import read, write, sha
from mapmaker.scene_geometry import triangles
from mapmaker.scene_overlap import OverlapSnapshot
from mapmaker.scene_pose_search import SourceDepthScreen, translation_alternatives
from mapmaker.scene_projection import silhouette_evidence
from mapmaker.scene_ownership import composite_residuals


def search(run, output):
    meta = read(run/'scene_metadata.json')
    scene = trimesh.load(run/'scene.glb', force='scene', process=False)
    common = np.asarray(meta['placement']['common_transform'])
    inverse = np.linalg.inv(common)
    pointmap_hash = sha(run/meta['pointmap']['asset'])
    if pointmap_hash != meta['pointmap']['sha256'] or meta['pointmap']['frame'] != 'sam3d_pytorch3d_camera':
        raise ValueError('Pointmap frame or hash mismatch')
    with np.load(run/meta['pointmap']['asset'], allow_pickle=False) as archive:
        points = archive['points']
    h, w = points.shape[:2]
    objects = {o['id']: o for o in meta['objects'] if o['status']=='generated'}
    masks = {key: np.asarray(Image.open(run/obj['mask']).convert('L').resize((w, h), Image.Resampling.NEAREST))>0
             for key, obj in objects.items()}
    residuals = composite_residuals(masks, points)
    ids = list(objects)+[s['node'] for s in meta['structure']['surfaces']]
    faces = {key: triangles(scene, key) for key in ids}
    snapshot = OverlapSnapshot(faces)
    records = []
    report = dict(scene_sha256=sha(run/'scene.glb'), pointmap_sha256=pointmap_hash, records=records, complete=False,
                  quality_passed=False, production_integration=False, uses_object_names=False,
                  limitation='Independent candidates on one immutable snapshot; do not apply together without sequential revalidation. Support and visual validation still required. Open meshes represent measured surfaces, not inferred solids.')
    for pose in meta['placement']['pose_refinement']['records']:
        oid = pose['object_id']
        if pose.get('applied') or oid not in objects:
            continue
        seed = None
        for number, proposal in enumerate(pose.get('rejected_collision_candidates', [])):
            for check in proposal['collision_checks']:
                if check.get('before')!='intersection':
                    continue
                matrix = np.asarray(proposal['camera_transform'])
                evidence = snapshot.measure_pair(oid, check['other_id'], common@matrix@inverse)
                if (evidence['available'] and evidence['before']>0 and evidence['relative_before']>1e-9
                        and evidence['after']<=evidence['before']*.8
                        and evidence['relative_after']<=evidence['relative_before']*.8):
                    seed = (number, matrix, evidence)
                    break
            if seed is not None:
                break
        if seed is None:
            continue
        print('SEED', oid, seed[0], flush=True)
        record = dict(object_id=oid, seed=seed[0], seed_pair=seed[2], candidates=[], accepted=False)
        records.append(record)
        raw = trimesh.transform_points(faces[oid].reshape(-1, 3), inverse).reshape(-1, 3, 3)
        mesh = trimesh.Trimesh(raw.reshape(-1, 3), np.arange(len(raw)*3).reshape(-1, 3), process=True)
        observed = points[residuals[oid][0] if oid in residuals else masks[oid]]
        try:
            depth = SourceDepthScreen(mesh, observed)
        except ValueError:
            record['reason'] = 'insufficient_reliable_depth'
            write(output, report)
            continue
        before_projection = silhouette_evidence(raw, points, masks[oid])
        for candidate, provenance in translation_alternatives(seed[1], mesh):
            row = dict(provenance, depth=depth.assess(candidate), accepted=False)
            record['candidates'].append(row)
            if not row['depth']['accepted']:
                continue
            shifted = trimesh.transform_points(raw.reshape(-1, 3), candidate).reshape(-1, 3, 3)
            after_projection = silhouette_evidence(shifted, points, masks[oid])
            row.update(before_projection=before_projection, after_projection=after_projection)
            if not (before_projection['accepted'] and after_projection['accepted']
                    and after_projection['silhouette_iou']>=before_projection['silhouette_iou']
                    and after_projection['mask_covered_fraction']>=before_projection['mask_covered_fraction']):
                row['reason'] = 'source_projection'
                continue
            row['overlap'] = snapshot.assess(oid, common@candidate@inverse)
            row['accepted'] = row['overlap']['accepted']
            if row['accepted']:
                row['camera_transform'] = candidate.tolist()
                record['accepted'] = True
                break
            write(output, report)
        print('SCREENED', oid, 'candidates', len(record['candidates']), 'accepted', record['accepted'], flush=True)
        write(output, report)
    report['complete'] = True
    write(output, report)
    print('COMPLETE', len(records), 'seeds;', sum(r['accepted'] for r in records), 'candidates survive source/endpoint screens', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    search(args.run, args.output)
