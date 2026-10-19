"""Sequential supported-pose refinement with independent source/contact/path gates."""
import hashlib
import numpy as np
import trimesh
from PIL import Image
from .scene_run import write,sha
from .scene_geometry import triangles,support_translation
from .scene_contact_pose import contact_pose_candidates
from .scene_supported_pose import supported_pose_candidates
from .reconstruction_evidence import assess_masks
from .scene_support_guard import support_preservation
from .scene_object_support import measured_support_plane
from .scene_pose_refinement import pose_collision_checks
from .scene_collision import MeshIndex,certified_penetration_repair


def source_preserved(before,after):
    if not before.get('accepted') or not after.get('accepted'):return False
    a,b=before.get('projection',{}),after.get('projection',{})
    if not a.get('accepted') or not b.get('accepted'):return False
    for key in ('mask_covered_fraction','silhouette_iou'):
        if b.get(key,-1)<a.get(key,0):return False
    for key in ('normalized_depth_median','normalized_depth_p90'):
        if key not in before or key not in after or not np.isfinite(after[key]) or after[key]>before[key]:return False
    a,b=before.get('visible_depth',{}),after.get('visible_depth',{})
    if not a.get('available') or not b.get('available') or min(a.get('matched_rays',0),b.get('matched_rays',0))<64:return False
    if b.get('hit_fraction',0)<a.get('hit_fraction',0):return False
    return all(a.get(k) is not None and b.get(k) is not None and np.isfinite(b[k]) and b[k]<=a[k]
               for k in ('normalized_median','normalized_p90'))


def support_seed_assessment(vertices, fixed, limit, tolerance):
    """Expose why a finite support did or did not produce a repair proposal."""
    delta, contact = support_translation(vertices, fixed, limit, tolerance)
    evidence = dict(contact=contact, seed_diagnostics=[])
    if delta is not None and np.linalg.norm(delta) <= tolerance:
        return [], dict(evidence, reason='already_supported')
    seeds = []
    if delta is not None:
        # A level floating object has no tilt to fit. Retain its measured
        # translation as a proposal, subject to the same downstream gates.
        motion = float(np.linalg.norm(delta))
        budget = min(float(limit), float(np.linalg.norm(np.ptp(vertices,axis=0))*.08))
        if motion <= budget:
            transform = np.eye(4);transform[:3,3] = delta
            remaining, settled = support_translation(vertices+delta, fixed, limit, tolerance)
            if remaining is not None and np.linalg.norm(remaining) <= tolerance:
                seeds.append((transform, dict(method='foot_surface_gap_translation',
                    maximum_vertex_motion=motion, motion_budget=budget, contact=settled,
                    requires_source_and_collision_validation=True, uses_object_names=False)))
    seeds.extend(contact_pose_candidates(vertices, fixed, limit, tolerance,
                                        diagnostics=evidence['seed_diagnostics']))
    evidence.update(reason='pose_seeds_available' if seeds else 'no_admissible_pose_seed',
                    seed_count=len(seeds))
    return seeds, evidence


def refine_supported_poses(run,scene,objects,points,placement,structure):
    from .scene_placement import object_vertices,bounds_of,update_transform
    tolerance=placement['contact_tolerance'];common=np.asarray(placement['common_transform']);inverse=np.linalg.inv(common)
    surfaces=structure.get('surfaces',[]);surface_ids={s['node'] for s in surfaces}
    supports=[s for s in surfaces if s.get('normal',[0,0,0])[1]>.96 and s.get('point') is not None]
    plane_info={s['node']:dict(normal=s['normal'],tolerance=tolerance) for s in surfaces if s.get('normal') is not None}
    object_ids=[o['id'] for o in objects]
    masks={o['id']:np.asarray(Image.open(run/o['mask']).convert('L').resize(points.shape[1::-1],Image.Resampling.NEAREST))>0 for o in objects if o.get('mask')}
    ordered=sorted((o for o in objects if o['id'] in masks),key=lambda o:hashlib.sha256(np.packbits(masks[o['id']]).tobytes()).hexdigest())
    report=dict(complete=False,records=[],changes=[],uses_object_names=False)
    faces={k:triangles(scene,k) for k in object_ids+list(surface_ids)}
    bounds={k:np.array([f.min((0,1)),f.max((0,1))]) for k,f in faces.items()};indices={}
    def index(k):
        if k not in indices:indices[k]=MeshIndex(faces[k])
        return indices[k]
    for obj in ordered:
        oid=obj['id'];moving=faces[oid];vertices=moving.reshape(-1,3);limit=np.linalg.norm(np.ptp(vertices,axis=0))*.08
        record=dict(object_id=oid,applied=False,candidates=[],support_assessments=[]);report['records'].append(record)
        if limit<=1e-9:
            record['reason']='degenerate_geometry';continue
        mesh=None;baseline=None
        candidates = list(supports)
        # Refresh object planes from current geometry after each accepted edit.
        # Ordering follows mask pixels, never labels or inferred object classes.
        for other in ordered:
            sid = other['id']
            if sid == oid:
                continue
            if (np.any(bounds[oid][1][[0,2]] < bounds[sid][0][[0,2]])
                    or np.any(bounds[sid][1][[0,2]] < bounds[oid][0][[0,2]])
                    or bounds[sid][0,1] >= bounds[oid][:,1].mean()):
                continue
            plane, evidence = measured_support_plane(vertices, faces[sid], limit, tolerance)
            if plane is None:
                record['support_assessments'].append(dict(surface_id=sid, **evidence))
            else:
                candidates.append(dict(node=sid, **plane, object_support_evidence=evidence))
        for surface in candidates:
            fixed=faces[surface['node']]
            if np.any(bounds[oid][1][[0,2]]<bounds[surface['node']][0][[0,2]]) or np.any(bounds[surface['node']][1][[0,2]]<bounds[oid][0][[0,2]]):
                record['support_assessments'].append(dict(surface_id=surface['node'],reason='outside_support_bounds'))
                continue
            seeds,assessment=support_seed_assessment(vertices,fixed,limit,tolerance)
            record['support_assessments'].append(dict(surface_id=surface['node'],**assessment,
                object_support_evidence=surface.get('object_support_evidence')))
            if not seeds:continue
            if mesh is None:
                mesh=trimesh.Trimesh(vertices,np.arange(len(vertices)).reshape(-1,3),process=False)
                check_masks={'current':masks[oid]}
                provenance=obj.get('mask_expansion',{})
                if provenance.get('original_mask'):
                    path=run/provenance['original_mask']
                    if sha(path)!=provenance['original_sha256']:raise ValueError('Original mask provenance mismatch')
                    check_masks['original']=np.asarray(Image.open(path).convert('L').resize(points.shape[1::-1],Image.Resampling.NEAREST))>0
                raw=trimesh.transform_points(vertices,inverse).reshape(-1,3,3)
                baseline=assess_masks(raw,points,check_masks,visible_depth=True)
                fitmask=check_masks.get('original',check_masks['current'])
                observed=trimesh.transform_points(points[fitmask],common)
            for seed,seed_evidence in seeds:
                for transform,evidence in supported_pose_candidates(mesh,seed,observed,fixed,surface['normal'],surface['point'],tolerance):
                    row=dict(surface_id=surface['node'],proposal=evidence,seed=seed_evidence,accepted=False)
                    record['candidates'].append(row)
                    end=trimesh.transform_points(vertices,transform).reshape(-1,3,3)
                    raw=trimesh.transform_points(end.reshape(-1,3),inverse).reshape(-1,3,3)
                    after=assess_masks(raw,points,check_masks,visible_depth=True)
                    row['source']=dict(before=baseline,after=after)
                    if not all(source_preserved(baseline[k],after[k]) for k in baseline):
                        row['reason']='source_regression';continue
                    row['support']=support_preservation(faces,object_ids,list(surface_ids),oid,transform,tolerance)
                    if not row['support']['accepted']:
                        row['reason']='existing_support_regression';continue
                    checks=pose_collision_checks(moving,transform,bounds,oid,surface_ids,index,surface_planes=plane_info)
                    row['collision_checks']=checks
                    if not (all(c['path_result']=='clear' for c in checks) or certified_penetration_repair(checks)):
                        row['reason']='collision_or_unknown';continue
                    matrix=transform@scene.graph[oid][0]
                    scene.graph.update(frame_from=scene.graph.base_frame,frame_to=oid,matrix=matrix)
                    update_transform(obj,matrix);b=bounds_of(object_vertices(scene,oid))
                    obj['placement'].update(world_bounds_after=b.tolist(),world_center=b.mean(0).tolist(),
                        world_bottom_center=[float(b[:,0].mean()),float(b[0,1]),float(b[:,2].mean())],
                        world_up_after=(matrix[:3,1]/np.linalg.norm(matrix[:3,1])).tolist())
                    row.update(accepted=True,transform=transform.tolist());record['applied']=True
                    report['changes'].append(dict(object_id=oid,transform=transform.tolist()))
                    faces[oid]=end;bounds[oid]=b;indices.pop(oid,None)
                    break
                if record['applied']:break
            if record['applied']:break
        if not record['applied']:
            record['reason']=('all_candidates_rejected' if record['candidates'] else
                              'no_admissible_pose_seed' if record['support_assessments'] else
                              'no_evidenced_horizontal_surface')
            if record['support_assessments'] and all(a['reason']=='already_supported' for a in record['support_assessments']):
                record['reason']='already_supported'
        write(run/'logs/supported_refinement_progress.json',report)
    report['complete']=True;write(run/'logs/supported_refinement.json',report)
    return report
