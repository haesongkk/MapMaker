"""Sequential source-validated static overlap repair at scene finalization."""
import hashlib
import numpy as np
import trimesh
from PIL import Image

from .scene_geometry import triangles
from .scene_overlap import OverlapSnapshot
from .scene_ownership import composite_residuals
from .scene_pose_search import SourceDepthScreen, translation_alternatives
from .scene_projection import silhouette_evidence
from .scene_support_guard import support_preservation


def refine_overlaps(run, scene, objects, points, placement, structure, *, strict_source=False):
    """Do not compose certificates from an earlier scene snapshot.

    This repairs reconstruction endpoints, not animated collision-free paths.
    Support checks preserve detected geometric contacts, not unknown real-world
    supports. The optional native engine is required when this stage is enabled.
    """
    import manifold3d  # Fail before edits if the explicitly enabled engine is absent.
    from .scene_placement import object_vertices, bounds_of, update_transform
    from .scene_run import write

    common = np.asarray(placement['common_transform'])
    inverse = np.linalg.inv(common)
    h, w = points.shape[:2]
    masks = {o['id']: np.asarray(Image.open(run/o['mask']).convert('L').resize(
        (w, h), Image.Resampling.NEAREST)) > 0 for o in objects if o.get('mask')}
    residuals = composite_residuals(masks, points)
    poses = {r['object_id']: r for r in placement.get('pose_refinement', {}).get('records', [])}
    surfaces = structure.get('surfaces', [])
    ids = [o['id'] for o in objects]+[s['node'] for s in surfaces]
    support_surfaces = [s['node'] for s in surfaces]
    records, changes = [], []
    report = dict(records=records, changes=changes, uses_object_names=False, complete=False,
        scope='static_reconstruction_endpoint_not_collision_free_motion',
        support_scope='preserves_detected_contacts_not_unknown_physical_supports')
    ordered = sorted((o for o in objects if o['id'] in masks), key=lambda o:
        (-int(masks[o['id']].sum()), hashlib.sha256(np.packbits(masks[o['id']]).tobytes()).hexdigest()))
    faces = snapshot = None
    for obj in ordered:
        oid = obj['id']
        pose = poses.get(oid, {})
        if pose.get('applied') or not pose.get('rejected_collision_candidates'):
            continue
        # Original camera candidates are invalid after a prior contact edit.
        # Compare against the pose fitter's recorded starting world transform.
        start = pose.get('starting_world_transform')
        if start is None or not np.allclose(scene.graph[oid][0], start, rtol=0, atol=1e-10):
            records.append(dict(object_id=oid, applied=False, reason='candidate_origin_changed_or_unrecorded'))
            continue
        if snapshot is None:
            faces = {key: triangles(scene, key) for key in ids}
            snapshot = OverlapSnapshot(faces)
        seed = None
        for number, proposal in enumerate(pose['rejected_collision_candidates']):
            matrix = np.asarray(proposal['camera_transform'])
            for check in proposal['collision_checks']:
                if check.get('before')!='intersection' or check['other_id'] not in faces:
                    continue
                measured = snapshot.measure_pair(oid, check['other_id'], common@matrix@inverse)
                if (measured['available'] and measured['before']>0 and measured['relative_before']>1e-9
                        and measured['after']<=measured['before']*.8
                        and measured['relative_after']<=measured['relative_before']*.8):
                    seed = number, matrix
                    break
            if seed is not None:
                break
        if seed is None:
            continue
        record = dict(object_id=oid, seed=seed[0], applied=False, candidates=[])
        records.append(record)
        raw = trimesh.transform_points(faces[oid].reshape(-1, 3), inverse).reshape(-1, 3, 3)
        mesh = trimesh.Trimesh(raw.reshape(-1, 3), np.arange(len(raw)*3).reshape(-1, 3), process=True)
        observed = points[residuals[oid][0] if oid in residuals else masks[oid]]
        try:
            depth = SourceDepthScreen(mesh, observed)
        except ValueError:
            record['reason'] = 'insufficient_reliable_depth'
            continue
        before = silhouette_evidence(raw, points, masks[oid])
        source_masks = {'current': masks[oid]}
        source_before = {}
        if strict_source:
            from .scene_run import sha
            from .reconstruction_evidence import assess_masks
            from .scene_supported_refinement import source_preserved
            expansion = obj.get('mask_expansion', {})
            if expansion:
                path = (run/expansion['original_mask']).resolve()
                if not path.is_relative_to(run.resolve()) or sha(path)!=expansion['original_sha256']:
                    raise ValueError('Original mask provenance mismatch')
                source_masks['original'] = np.asarray(Image.open(path).convert('L').resize(
                    (w,h), Image.Resampling.NEAREST)) > 0
        for candidate, provenance in translation_alternatives(seed[1], mesh):
            row = dict(provenance, depth=depth.assess(candidate), accepted=False)
            record['candidates'].append(row)
            if not row['depth']['accepted']:
                continue
            shifted = trimesh.transform_points(raw.reshape(-1, 3), candidate).reshape(-1, 3, 3)
            after = silhouette_evidence(shifted, points, masks[oid])
            row.update(before_projection=before, after_projection=after)
            if not (before['accepted'] and after['accepted'] and after['silhouette_iou']>=before['silhouette_iou']
                    and after['mask_covered_fraction']>=before['mask_covered_fraction']):
                row['reason'] = 'source_projection'
                continue
            transform = common@candidate@inverse
            row['overlap'] = snapshot.assess(oid, transform)
            if not row['overlap']['accepted']:
                continue
            row['support'] = support_preservation(faces, [o['id'] for o in objects], support_surfaces,
                oid, transform, placement['contact_tolerance'])
            if not row['support']['accepted']:
                row['reason'] = 'support_regression'
                continue
            if strict_source:
                if not source_before:
                    source_before = assess_masks(raw,points,source_masks,visible_depth=True)
                source_after = assess_masks(shifted,points,source_masks,visible_depth=True)
                row['source_preservation'] = dict(before=source_before,after=source_after,
                    accepted=all(source_preserved(source_before[label],source_after[label]) for label in source_masks))
                if not row['source_preservation']['accepted']:
                    row['reason'] = 'strict_source_regression'
                    continue
            matrix = transform@scene.graph[oid][0]
            scene.graph.update(frame_from=scene.graph.base_frame, frame_to=oid, matrix=matrix)
            update_transform(obj, matrix)
            bounds = bounds_of(object_vertices(scene, oid))
            obj['placement'].update(world_bounds_after=bounds.tolist(), world_center=bounds.mean(0).tolist(),
                world_bottom_center=[float(bounds[:, 0].mean()), float(bounds[0, 1]), float(bounds[:, 2].mean())],
                world_up_after=(matrix[:3, 1]/np.linalg.norm(matrix[:3, 1])).tolist(),
                pose_depth_transform=transform.tolist(),
                pose_depth_prior_contact_count=len(obj['placement'].get('contacts', [])))
            row.update(accepted=True, camera_transform=candidate.tolist(), transform=transform.tolist())
            record.update(applied=True, selected_candidate=len(record['candidates'])-1)
            changes.append(dict(object_id=oid, transform=transform.tolist(), camera_transform=candidate.tolist()))
            # Only an accepted edit invalidates this immutable snapshot. Reuse
            # it across abstentions, but never across two accepted edits.
            faces = snapshot = None
            break
        write(run/'logs/overlap_refinement_progress.json', report)
        # A subsequent object rebuilds the snapshot after every accepted edit.
    report['complete'] = True
    write(run/'logs/overlap_refinement.json', report)
    return report
