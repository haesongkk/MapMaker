"""Bounded, source-validated pose refinement and measured penetration repair."""
import hashlib
import numpy as np
from PIL import Image
import trimesh
from .scene_collision import MeshIndex, certified_penetration_repair,initial_penetration_evidence
from .scene_geometry import triangles
from .scene_ownership import composite_residuals
from .scene_projection import silhouette_evidence
from .scene_registration import propose_similarity_transform


def pose_collision_checks(moving, transform, bounds, oid, surface_ids, index, *, initial_cache=None, surface_planes=None):
    """Certify one candidate; reuse initial-state evidence within one object only.

    The caller must discard the cache whenever moving or fixed geometry changes.
    Candidate endpoint/path queries are always evaluated independently.
    """
    if initial_cache is None:
        initial_cache = {}
    end=trimesh.transform_points(moving.reshape(-1,3),transform).reshape(-1,3,3)
    factor=float(np.cbrt(np.linalg.det(transform[:3,:3])))
    angle=float(np.arccos(np.clip((np.trace(transform[:3,:3]/factor)-1)/2,-1,1)))
    center=bounds[oid].mean(0);radius=float(np.linalg.norm(moving-center,axis=-1).max())
    padding=radius*(max(1.,factor)*angle**2+2*abs(factor-1)*angle)/8+1e-9
    lower=np.minimum(moving.min((0,1)),end.min((0,1)))-padding
    upper=np.maximum(moving.max((0,1)),end.max((0,1)))+padding
    checks=[]
    for sid,other_bounds in bounds.items():
        if sid==oid or np.any(upper<other_bounds[0]) or np.any(lower>other_bounds[1]):continue
        fixed=index(sid);solid=sid not in surface_ids
        final=fixed.swept_collision(end,np.zeros(3),check_containment=solid)
        # A certified endpoint intersection also certifies a path intersection.
        # Avoid the expensive swept query for a candidate already ruled out.
        path=True if final is True else fixed.similarity_swept_collision(moving,transform,check_containment=solid)
        check=dict(other_id=sid,path_result='unknown' if path is None else 'intersection' if path else 'clear')
        if path is False:
            check.update(before='clear',after='clear')
        else:
            initial_key=(sid,'initial')
            if initial_key not in initial_cache:
                initial_cache[initial_key]=fixed.swept_collision(moving,np.zeros(3),check_containment=solid)
            initial=initial_cache[initial_key]
            check.update(before='unknown' if initial is None else 'intersection' if initial else 'clear',
                after='unknown' if final is None else 'intersection' if final else 'clear')
            if path is True and initial is True and final is False and solid:
                penetration_key=(sid,'penetration')
                if penetration_key not in initial_cache:
                    initial_cache[penetration_key]=initial_penetration_evidence(fixed,moving)
                check.update(initial_cache[penetration_key])
            elif path is True and initial is True and final is False and surface_planes and sid in surface_planes:
                from .scene_plane_penetration import planar_penetration_evidence
                plane=surface_planes[sid]
                check.update(planar_penetration_evidence(fixed,moving,end,plane['normal'],plane['tolerance']))
        checks.append(check)
        if check['after']!='clear' or check['path_result']=='unknown':break
    return checks


def refine_poses(run,scene,objects,points,placement,structure,*,strict_source=False):
    from .scene_placement import object_vertices,bounds_of,update_transform
    from .scene_run import write,sha
    from .scene_support_guard import support_preservation
    common=np.asarray(placement['common_transform']);inverse=np.linalg.inv(common)
    h,w=points.shape[:2]
    masks={o['id']:np.asarray(Image.open(run/o['mask']).convert('L').resize((w,h),Image.Resampling.NEAREST))>0
           for o in objects if o.get('mask')}
    residuals=composite_residuals(masks,points)
    faces={o['id']:triangles(scene,o['id']) for o in objects}
    surface_ids={s['node'] for s in structure.get('surfaces',[])}
    faces.update({sid:triangles(scene,sid) for sid in surface_ids})
    bounds={oid:np.array([f.min((0,1)),f.max((0,1))]) for oid,f in faces.items()}
    indices={}
    def index(oid):
        if oid not in indices:
            if len(indices)>=3:indices.pop(next(iter(indices)))
            indices[oid]=MeshIndex(faces[oid])
        return indices[oid]
    records=[];changes=[]
    ordered=sorted((o for o in objects if o['id'] in masks),key=lambda o:
        (-int(masks[o['id']].sum()),hashlib.sha256(np.packbits(masks[o['id']]).tobytes()).hexdigest()))
    for obj in ordered:
        oid=obj['id'];mask=masks[oid]
        write(run/'logs/pose_refinement_progress.json',dict(complete=False,changes=changes,
            processed=len(records),total=len(ordered),active_object_id=oid,
            outcomes=[dict(object_id=r['object_id'],applied=r['applied'],reason=r.get('reason')) for r in records]))
        observed=points[residuals[oid][0] if oid in residuals else mask]
        valid=np.isfinite(observed).all(-1)&(np.linalg.norm(observed,axis=-1)>1e-6)
        record=dict(object_id=oid,applied=False,starting_world_transform=scene.graph[oid][0].tolist())
        records.append(record)
        if valid.sum()<64 or valid.mean()<.95:
            record['reason']='insufficient_reliable_mask_depth';continue
        moving=faces[oid]
        # Choose fit/validation samples and motion bounds in the fixed input
        # camera frame. World-axis sorting and bounds change when room up changes.
        original=obj.get('placement',{}).get('original_matrix')
        if original is not None and np.allclose(scene.graph[oid][0],common@np.asarray(original),rtol=0,atol=1e-10):
            raw_before=triangles(scene,oid,root_transform=original)
        else:
            raw_before=trimesh.transform_points(moving.reshape(-1,3),inverse).reshape(-1,3,3)
        mesh=trimesh.Trimesh(raw_before.reshape(-1,3),np.arange(len(moving)*3).reshape(-1,3),process=True)
        projection_cache={};collision_cache={};collision_rejections=[]
        preservation_cache={};preservation_rejections=[];source_baseline={}
        initial_support_cache={}  # Discarded before any other object is refined.
        check_masks={'current':mask}
        if strict_source and obj.get('mask_expansion',{}).get('original_mask'):
            provenance=obj['mask_expansion'];path=(run/provenance['original_mask']).resolve()
            if run.resolve() not in path.parents or sha(path)!=provenance['original_sha256']:
                raise ValueError('Original mask provenance mismatch')
            check_masks['original']=np.asarray(Image.open(path).convert('L').resize((w,h),Image.Resampling.NEAREST))>0
        def preservation_allows(candidate):
            key=candidate.tobytes()
            if key in preservation_cache:return preservation_cache[key]['accepted']
            transform=common@candidate@inverse
            evidence=support_preservation(faces,[o['id'] for o in objects],list(surface_ids),oid,transform,
                placement.get('contact_tolerance',1e-6), initial_cache=initial_support_cache)
            result=dict(accepted=evidence['accepted'],support=evidence)
            if result['accepted'] and strict_source:
                from .reconstruction_evidence import assess_masks
                from .scene_supported_refinement import source_preserved as strict_preserved
                raw_after=trimesh.transform_points(raw_before.reshape(-1,3),candidate).reshape(-1,3,3)
                if not source_baseline:
                    source_baseline.update(assess_masks(raw_before,points,check_masks,visible_depth=True))
                after=assess_masks(raw_after,points,check_masks,visible_depth=True)
                result.update(accepted=all(strict_preserved(source_baseline[label],after[label]) for label in check_masks),
                    source=dict(before=source_baseline,after=after))
            preservation_cache[key]=result
            if not result['accepted']:preservation_rejections.append(dict(camera_transform=candidate.tolist(),**result))
            return result['accepted']
        initial_collision_cache={}  # Scene geometry stays fixed through this object's candidate search.
        def source_preserved(candidate):
            if 'before' not in projection_cache:
                projection_cache['before']=silhouette_evidence(raw_before,points,mask)
            raw=trimesh.transform_points(raw_before.reshape(-1,3),candidate).reshape(-1,3,3)
            after=silhouette_evidence(raw,points,mask)
            before=projection_cache['before']
            projection_cache['after']=after
            projection_cache['transform']=candidate.tolist()
            preserved=(before['accepted'] and after['accepted'] and
                    after['silhouette_iou']>=before['silhouette_iou'] and
                    after['mask_covered_fraction']>=before['mask_covered_fraction'])
            if not preserved:return False
            if not preservation_allows(candidate):return False
            transform=common@candidate@inverse
            checks=pose_collision_checks(moving,transform,bounds,oid,surface_ids,index,
                                         initial_cache=initial_collision_cache)
            collision_cache[candidate.tobytes()]=checks
            accepted=all(c['path_result']=='clear' for c in checks) or certified_penetration_repair(checks)
            if not accepted:
                collision_rejections.append(dict(camera_transform=candidate.tolist(),collision_checks=checks))
            return accepted
        transform,evidence=propose_similarity_transform(mesh,observed[valid],
                                                       candidate_filter=source_preserved)
        evidence['fitting_frame']='original_input_camera'
        record.update(evidence)
        if preservation_rejections:record['rejected_preservation_candidates']=preservation_rejections
        if collision_rejections:record['rejected_collision_candidates']=collision_rejections
        if transform is None:
            if evidence['reason']=='candidate_constraints_rejected':
                record.update(reason='pose_preservation_failed' if preservation_rejections else 'pose_collision_or_unknown' if collision_rejections else 'pose_degrades_source_projection',
                    before_projection=projection_cache['before'],
                    last_rejected_candidate=dict(transform=projection_cache['transform'],
                                                 projection=projection_cache['after']))
            continue
        if not preservation_allows(transform):
            record.update(reason='pose_preservation_failed',rejected_preservation_candidates=preservation_rejections)
            continue
        record['preservation']=preservation_cache[transform.tobytes()]
        evidence['camera_transform']=transform.tolist()
        selected_checks=collision_cache.get(transform.tobytes())
        transform=common@transform@inverse
        evidence['transform']=transform.tolist()
        record.update(evidence)
        end=trimesh.transform_points(moving.reshape(-1,3),transform).reshape(-1,3,3)
        raw_before=trimesh.transform_points(moving.reshape(-1,3),inverse).reshape(-1,3,3)
        raw_after=trimesh.transform_points(end.reshape(-1,3),inverse).reshape(-1,3,3)
        before=projection_cache.get('before')
        after=projection_cache.get('after')
        if before is None:before=silhouette_evidence(raw_before,points,mask)
        if after is None:after=silhouette_evidence(raw_after,points,mask)
        record.update(before_projection=before,after_projection=after)
        if (not before['accepted'] or not after['accepted'] or
            after['silhouette_iou']<before['silhouette_iou'] or
            after['mask_covered_fraction']<before['mask_covered_fraction']):
            record['reason']='pose_degrades_source_projection';continue
        checks=selected_checks if selected_checks is not None else pose_collision_checks(moving,transform,bounds,oid,surface_ids,index,
                                                                                         initial_cache=initial_collision_cache)
        record['collision_checks']=checks
        clear=all(c['path_result']=='clear' for c in checks)
        repair=certified_penetration_repair(checks)
        if not clear and not repair:
            record['reason']='pose_collision_or_unknown';continue
        matrix=transform@scene.graph[oid][0]
        scene.graph.update(frame_from=scene.graph.base_frame,frame_to=oid,matrix=matrix)
        update_transform(obj,matrix)
        b=bounds_of(object_vertices(scene,oid))
        obj['placement'].update(world_bounds_after=b.tolist(),world_center=b.mean(0).tolist(),
            world_bottom_center=[float(b[:,0].mean()),float(b[0,1]),float(b[:,2].mean())],
            world_up_after=(matrix[:3,1]/np.linalg.norm(matrix[:3,1])).tolist(),
            pose_depth_transform=transform.tolist(),pose_depth_prior_contact_count=len(obj['placement'].get('contacts',[])))
        record.update(applied=True,existing_penetration_repair=repair)
        changes.append(record);faces[oid]=end;bounds[oid]=b;indices.pop(oid,None)
        write(run/'logs/pose_refinement_progress.json',dict(changes=changes,processed=len(records),total=len(ordered)))
    write(run/'logs/pose_refinement_progress.json',dict(complete=True,changes=changes,
        processed=len(records),total=len(ordered),active_object_id=None,
        outcomes=[dict(object_id=r['object_id'],applied=r['applied'],reason=r.get('reason')) for r in records]))
    return dict(changes=changes,records=records,uses_object_names=False,
        limitation='Monocular depth and source projection are evidence, not metric ground truth; uncertain collisions abstain')
