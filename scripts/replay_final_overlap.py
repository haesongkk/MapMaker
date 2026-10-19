"""Ablate only final overlap repair on verified exported geometry, not fresh inference."""
import argparse
import copy
from pathlib import Path
import shutil

import numpy as np
import trimesh

from mapmaker.scene_run import read, write, sha
from mapmaker.scene_placement import bounds_of, object_vertices, update_transform, group_export_nodes


def restore_before_overlap(scene, meta):
    """Validate every recorded edit before undoing any of them."""
    placement = meta['placement']
    report = placement['overlap_refinement']
    if not report.get('complete'):
        raise ValueError('Incomplete overlap stage')
    poses = {r['object_id']: r for r in placement['pose_refinement']['records']}
    objects = {o['id']: o for o in meta['objects'] if o['status'] == 'generated'}
    changes = report['changes']
    applied = [r for r in report['records'] if r.get('applied')]
    if (len({r['object_id'] for r in changes}) != len(changes)
            or len(applied) != len(changes)
            or {r['object_id'] for r in applied} != {r['object_id'] for r in changes}):
        raise ValueError('Inconsistent overlap application records')
    records = {r['object_id']: r for r in applied}
    planned = []
    for change in changes:
        oid = change['object_id']
        pose = poses[oid]
        record = records[oid]
        selected = record['candidates'][record['selected_candidate']]
        before = np.asarray(pose['starting_world_transform'])
        transform = np.asarray(change['transform'])
        if (pose.get('applied') or not selected['accepted']
                or not np.allclose(transform, selected['transform'], atol=1e-12, rtol=0)
                or not np.allclose(scene.graph[oid][0], transform @ before, atol=1e-8, rtol=0)
                or not np.allclose(objects[oid]['transform']['matrix'], scene.graph[oid][0], atol=1e-8, rtol=0)):
            raise ValueError('Overlap origin or recorded final transform mismatch')
        planned.append((objects[oid], before))
    for obj, before in planned:
        scene.graph.update(frame_from=scene.graph.base_frame, frame_to=obj['id'], matrix=before)
        update_transform(obj, before)
        bounds = bounds_of(object_vertices(scene, obj['id']))
        obj['placement'].update(world_bounds_after=bounds.tolist(), world_center=bounds.mean(0).tolist(),
            world_bottom_center=[float(bounds[:,0].mean()),float(bounds[0,1]),float(bounds[:,2].mean())],
            world_up_after=(before[:3,1]/np.linalg.norm(before[:3,1])).tolist())
        obj['placement'].pop('pose_depth_transform', None)
        obj['placement'].pop('pose_depth_prior_contact_count', None)
    placement.pop('overlap_refinement')
    return [obj['id'] for obj, _ in planned]


def replay(source, target, *, replay_contacts=False, strict_source=False):
    from mapmaker.scene_overlap_refinement import refine_overlaps
    source, target = Path(source).resolve(), Path(target).resolve()
    if target.exists() or target.is_relative_to(source):
        raise ValueError('Expected new output outside the source')
    meta = read(source/'scene_metadata.json')
    if replay_contacts and meta['placement']['contacts']['changes']:
        raise ValueError('Contact replay requires an unchanged original contact stage')
    if sha(source/'scene.glb') != meta['placement']['scene_sha256']:
        raise ValueError('Final scene hash mismatch')
    if meta['pointmap'].get('frame') != 'sam3d_pytorch3d_camera':
        raise ValueError('Expected original SAM3D camera pointmap')
    files = {meta['input_image']: meta['input_sha256'], meta['pointmap']['asset']: meta['pointmap']['sha256']}
    for obj in meta['objects']:
        expansion = obj.get('mask_expansion', {})
        if expansion:
            files[expansion['original_mask']] = expansion['original_sha256']
        for key in ('mask', 'asset'):
            if obj.get(key):
                files[obj[key]] = obj[key+'_sha256']
        for entry in ('original_artifact', 'alternative_artifact'):
            artifact = obj.get('reconstruction_review', {}).get(entry)
            if artifact:
                files[artifact['asset']] = artifact['sha256']
                files[artifact['pose']] = artifact['pose_sha256']
    for name, digest in files.items():
        path = (source/name).resolve()
        if not path.is_relative_to(source) or sha(path) != digest:
            raise ValueError('Source asset hash or path mismatch')
    scene = trimesh.load(source/'scene.glb', force='scene', process=False)
    original_report = copy.deepcopy(meta['placement']['overlap_refinement'])
    restored = restore_before_overlap(scene, meta)
    target.mkdir(parents=True)
    for name in files:
        (target/name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source/name, target/name)
    write(target/'overlap_ablation_provenance.json', dict(source=str(source), source_scene_sha256=sha(source/'scene.glb'),
        restored_ids=restored, previous_overlap=original_report, fresh_gpu_inference=False,
        exported_geometry=True, contacts_replayed=replay_contacts, strict_source=strict_source,
        limitation=('Contact and overlap replay of exported meshes; does not rerun extraction, pose or room recovery'
            if replay_contacts else 'Stage-only replay of exported meshes; does not rerun extraction, pose, contacts or room recovery'),
        implementation_sha256={str(p):sha(p) for p in Path('mapmaker').glob('*.py')}))
    with np.load(source/meta['pointmap']['asset'], allow_pickle=False) as archive:
        points = archive['points']
    objects = [o for o in meta['objects'] if o['status']=='generated']
    if replay_contacts:
        from mapmaker.scene_contacts import improve_contacts
        from mapmaker.scene_source_guard import contact_source_guard
        guard = contact_source_guard(target, scene, meta, meta['placement'], points)
        improve_contacts(scene, objects, meta['placement'], meta['structure'], source_guard=guard)
        write(target/'logs/contact_replay.json', meta['placement']['contacts'])
    meta['placement']['overlap_refinement'] = refine_overlaps(target, scene, objects, points, meta['placement'], meta['structure'],
                                                            strict_source=strict_source)
    groups = group_export_nodes(scene, objects, meta['structure']['surfaces'])
    scene.export(target/'scene.glb')
    meta['assembly'].update(bounds=scene.bounds.tolist(), geometry_nodes=len(scene.graph.nodes_geometry), groups=groups)
    meta['placement']['scene_sha256'] = sha(target/'scene.glb')
    meta['placement']['overlap_ablation'] = True
    write(target/'scene_metadata.json', meta)
    print(dict(run=target.name, restored=len(restored), changes=len(meta['placement']['overlap_refinement']['changes'])), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--replay-contacts', action='store_true',
        help='Also rerun contacts with the source guard; requires zero original contact edits')
    parser.add_argument('--strict-source', action='store_true',
        help='Require current and original mask visible-depth preservation for overlap edits')
    args = parser.parse_args()
    replay(args.source, args.output, replay_contacts=args.replay_contacts, strict_source=args.strict_source)
