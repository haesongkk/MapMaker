"""Sequentially revalidate experimental candidates into a separate local run."""
import argparse
import hashlib
from pathlib import Path
import shutil
import numpy as np
import trimesh
from PIL import Image

from mapmaker.scene_run import read, write, sha
from mapmaker.scene_transfer import safe_name
from mapmaker.scene_geometry import triangles
from mapmaker.scene_overlap import OverlapSnapshot
from mapmaker.scene_pose_search import SourceDepthScreen
from mapmaker.scene_projection import silhouette_evidence
from mapmaker.scene_support_guard import support_preservation
from mapmaker.scene_ownership import composite_residuals
from mapmaker.scene_placement import object_vertices, bounds_of, update_transform, group_export_nodes


def replay(source, proposals, target):
    source, target = source.resolve(), target.resolve()
    if target.exists() or target.is_relative_to(source):
        raise ValueError('Expected a new output directory outside the source run')
    meta, proposed = read(source/'scene_metadata.json'), read(proposals)
    digest = sha(source/'scene.glb')
    if not proposed['complete'] or proposed['scene_sha256'] != digest:
        raise ValueError('Proposals must be complete and match the source scene')
    info = meta['pointmap']
    if sha(source/info['asset']) != info['sha256'] or info['frame'] != 'sam3d_pytorch3d_camera':
        raise ValueError('Pointmap hash or frame mismatch')
    with np.load(source/info['asset'], allow_pickle=False) as archive:
        points = archive['points']
    scene = trimesh.load(source/'scene.glb', force='scene', process=False)
    common = np.asarray(meta['placement']['common_transform'])
    inverse = np.linalg.inv(common)
    objects = {o['id']: o for o in meta['objects'] if o['status']=='generated'}
    h, w = points.shape[:2]
    masks = {key: np.asarray(Image.open(source/o['mask']).convert('L').resize((w, h), Image.Resampling.NEAREST))>0
             for key, o in objects.items()}
    residuals = composite_residuals(masks, points)
    selected = {r['object_id']: next(c for c in r['candidates'] if c['accepted'])
                for r in proposed['records'] if r['accepted']}
    order = sorted(selected, key=lambda key: (-int(masks[key].sum()), hashlib.sha256(np.packbits(masks[key]).tobytes()).hexdigest()))
    surfaces = meta.get('structure', {}).get('surfaces', [])
    ids = list(objects)+[s['node'] for s in surfaces]
    floors = [s['node'] for s in surfaces if s['kind']=='floor']
    records = []
    for oid in order:
        obj = objects[oid]
        record = dict(object_id=oid, applied=False)
        records.append(record)
        if obj['placement'].get('pose_depth_transform') is not None:
            record['reason'] = 'already_refined_origin'
            continue
        faces = {key: triangles(scene, key) for key in ids}
        candidate = np.asarray(selected[oid]['camera_transform'])
        transform = common@candidate@inverse
        raw = trimesh.transform_points(faces[oid].reshape(-1, 3), inverse).reshape(-1, 3, 3)
        mesh = trimesh.Trimesh(raw.reshape(-1, 3), np.arange(len(raw)*3).reshape(-1, 3), process=True)
        depth = SourceDepthScreen(mesh, points[residuals[oid][0] if oid in residuals else masks[oid]]).assess(candidate)
        record['depth'] = depth
        if not depth['accepted']:
            record['reason'] = 'depth_revalidation'
            continue
        before = silhouette_evidence(raw, points, masks[oid])
        after = silhouette_evidence(trimesh.transform_points(raw.reshape(-1, 3), candidate).reshape(-1, 3, 3), points, masks[oid])
        record.update(before_projection=before, after_projection=after)
        if not (before['accepted'] and after['accepted'] and after['silhouette_iou']>=before['silhouette_iou']
                and after['mask_covered_fraction']>=before['mask_covered_fraction']):
            record['reason'] = 'projection_revalidation'
            continue
        # Rebuild from current geometry after every earlier move; certificates
        # for the original immutable snapshot cannot be composed blindly.
        overlap = OverlapSnapshot(faces).assess(oid, transform)
        record['overlap'] = overlap
        if not overlap['accepted']:
            record['reason'] = 'overlap_revalidation'
            continue
        support = support_preservation(faces, list(objects), floors, oid, transform, meta['placement']['contact_tolerance'])
        record['support'] = support
        if not support['accepted']:
            record['reason'] = 'support_regression'
            continue
        matrix = transform@scene.graph[oid][0]
        scene.graph.update(frame_from=scene.graph.base_frame, frame_to=oid, matrix=matrix)
        update_transform(obj, matrix)
        bounds = bounds_of(object_vertices(scene, oid))
        obj['placement'].update(world_bounds_after=bounds.tolist(), world_center=bounds.mean(0).tolist(),
            world_bottom_center=[float(bounds[:, 0].mean()), float(bounds[0, 1]), float(bounds[:, 2].mean())],
            world_up_after=(matrix[:3, 1]/np.linalg.norm(matrix[:3, 1])).tolist(),
            pose_depth_transform=transform.tolist(), pose_depth_prior_contact_count=len(obj['placement'].get('contacts', [])))
        record.update(applied=True, transform=transform.tolist(), reason='sequential_source_overlap_support_checks_passed')
        print('APPLIED', oid, flush=True)
    target.mkdir(parents=True)
    files = {meta['input_image'], info['asset']}
    for obj in meta['objects']:
        files.update(obj[key] for key in ('mask', 'asset') if obj.get(key))
        review = obj.get('reconstruction_review', {})
        for key in ('original_artifact', 'alternative_artifact'):
            if review.get(key):
                files.update(review[key][field] for field in ('asset', 'pose'))
    for name in files:
        safe_name(name)
        (target/name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source/name, target/name)
    groups = group_export_nodes(scene, list(objects.values()), surfaces)
    scene.export(target/'scene.glb')
    meta['assembly'].update(groups=groups, bounds=scene.bounds.tolist(), geometry_nodes=len(scene.graph.nodes_geometry))
    meta['placement']['scene_sha256'] = sha(target/'scene.glb')
    evidence = dict(source_scene_sha256=digest, proposals_sha256=sha(proposals), records=records,
                    fresh_gpu_inference=False, quality_gate_passed=False, production_integration=False)
    meta['placement']['overlap_replay'] = evidence
    write(target/'scene_metadata.json', meta)
    write(target/'logs/overlap_replay.json', evidence)
    write(target/'status.json', dict(stage='done', message='Local overlap experiment; quality gate not passed'))
    assert sha(source/'scene.glb') == digest
    print('COMPLETE', sum(r['applied'] for r in records), 'changes;', str(target), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--proposals', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    args = parser.parse_args()
    replay(args.source, args.proposals, args.target)
