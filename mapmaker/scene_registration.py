"""Bounded pose proposals from independent shared-depth observations.

No nonuniform deformation, category prior or per-image coordinates. Validation points
are withheld from fitting; observed-depth agreement is not metric ground truth.
"""
import numpy as np
import trimesh
from scipy.spatial.transform import Rotation
from .scene_proximity import closest_points


def propose_rigid_transform(mesh, observed, *, translation_fraction=.08, rotation_degrees=8.):
    """Fit a bounded rigid pose, retaining shape and validating withheld points.

    The fit does not authorize application: image displacement, collision and
    support regressions must still be checked by its caller.
    """
    return _propose_similarity(mesh,observed,translation_fraction,rotation_degrees,0.)


def propose_similarity_transform(mesh, observed, *, translation_fraction=.08,
                                 rotation_degrees=8., scale_fraction=.1, candidate_filter=None):
    """Experimental isotropic pose proposal; does not authorize scene mutation."""
    if not 0 <= scale_fraction < 1:
        raise ValueError('Scale fraction must be in [0, 1)')
    return _propose_similarity(mesh,observed,translation_fraction,rotation_degrees,scale_fraction,candidate_filter)


def _propose_similarity(mesh, observed, translation_fraction, rotation_degrees, scale_fraction, candidate_filter=None):
    cloud = np.asarray(observed, float)
    cloud = cloud[np.isfinite(cloud).all(-1)]
    if len(cloud) < 64:
        return None, dict(reason='insufficient_depth_observations')
    order = np.lexsort((cloud[:,2], cloud[:,1], cloud[:,0]))
    cloud = cloud[order][np.linspace(0, len(cloud)-1, min(512, len(cloud))).astype(int)]
    fit, validation = cloud[::2], cloud[1::2]
    scale = float(np.linalg.norm(np.ptp(mesh.vertices, axis=0)))
    if scale <= 1e-8:
        return None, dict(reason='degenerate_mesh')
    center = mesh.bounds.mean(0)
    budget = scale*translation_fraction
    transform = np.eye(4)
    history = []
    def distances(points, matrix):
        inverse = np.linalg.inv(matrix)
        local = trimesh.transform_points(points, inverse)
        closest, distance, _ = closest_points(mesh, local)
        factor=np.cbrt(np.linalg.det(matrix[:3,:3]))
        return trimesh.transform_points(closest, matrix), distance*factor
    def score(distance):
        values = np.sort(distance)[:max(1, int(len(distance)*.8))]
        return float(np.sqrt(np.mean(values**2)))
    _, before = distances(validation, transform)
    if score(before) < scale*.002:
        return None, dict(reason='already_matches_observed_depth')
    for _ in range(12):
        closest, distance = distances(fit, transform)
        keep = distance <= np.quantile(distance, .8)
        a, b = closest[keep], fit[keep]
        ca, cb = a.mean(0), b.mean(0)
        u, _, vh = np.linalg.svd((a-ca).T@(b-cb))
        rotation = vh.T@u.T
        if np.linalg.det(rotation) < 0:
            vh[-1] *= -1
            rotation = vh.T@u.T
        step = np.eye(4)
        factor=1.
        if scale_fraction:
            denominator=float(np.sum((a-ca)**2))
            if denominator <= 1e-12:
                break
            factor=float(np.sum(((a-ca)@rotation.T)*(b-cb))/denominator)
        if not np.isfinite(factor) or factor <= 0:
            break
        # An unconstrained ICP step can exceed the total motion budget while
        # a partial step remains useful. Backtrack on fit points only; withheld
        # validation and the caller's collision checks remain independent.
        rotvec = Rotation.from_matrix(rotation).as_rotvec()
        candidate = None
        for backtrack in range(16):
            alpha = 2.**-backtrack
            step[:3,:3] = np.exp(alpha*np.log(factor))*Rotation.from_rotvec(alpha*rotvec).as_matrix()
            step[:3,3] = ca+alpha*(cb-ca)-step[:3,:3]@ca
            trial = step@transform
            total_factor = float(np.cbrt(np.linalg.det(trial[:3,:3])))
            if total_factor <= 0 or abs(total_factor-1) > scale_fraction+1e-9:
                continue
            angle = np.rad2deg(np.arccos(np.clip((np.trace(trial[:3,:3]/total_factor)-1)/2, -1, 1)))
            displacement = np.linalg.norm(trimesh.transform_points(center[None], trial)[0]-center)
            if angle > rotation_degrees or displacement > budget:
                continue
            _, trial_distance = distances(fit, trial)
            if score(trial_distance) < score(distance):
                candidate = trial
                break
        if candidate is None:
            break
        if np.linalg.norm(candidate-transform) < 1e-6:
            break
        transform = candidate
        history.append(transform.copy())
    # Fit error decreases along this history. Prefer the latest candidate that
    # also passes independent depth and external constraints; a later rejected
    # optimum must not erase an earlier valid pose. No scene mutation here.
    candidates = list(reversed(history)) if candidate_filter and history else [transform]
    candidate_iterations = list(range(len(history), 0, -1)) if candidate_filter and history else [len(history)]
    fractions = [1.] * len(candidates)
    if candidate_filter and history:
        # Even the first accepted ICP fit step can cross a scene boundary.
        # Try shorter motions only after every full history candidate fails.
        # Interpolate about the mesh center so its displacement stays bounded;
        # independent depth, projection and swept collision criteria still apply.
        base = history[0]
        factor = float(np.cbrt(np.linalg.det(base[:3, :3])))
        rotvec = Rotation.from_matrix(base[:3, :3] / factor).as_rotvec()
        displacement = trimesh.transform_points(center[None], base)[0] - center
        for alpha in (.5, .25, .125, .0625):
            partial = np.eye(4)
            partial[:3, :3] = np.exp(alpha * np.log(factor)) * Rotation.from_rotvec(alpha * rotvec).as_matrix()
            partial[:3, 3] = center + alpha * displacement - partial[:3, :3] @ center
            candidates.append(partial)
            candidate_iterations.append(1)
            fractions.append(alpha)
    rejected = 0
    latest_evidence = None
    for index, transform in enumerate(candidates):
        _, after = distances(validation, transform)
        total_factor=float(np.cbrt(np.linalg.det(transform[:3,:3])))
        angle = float(np.rad2deg(np.arccos(np.clip((np.trace(transform[:3,:3]/total_factor)-1)/2, -1, 1))))
        evidence = dict(before=score(before), after=score(after), scale=scale,
            before_p90=float(np.quantile(before,.9)), after_p90=float(np.quantile(after,.9)),
            rotation_degrees=angle, scale_factor=total_factor, translation_budget=budget,
            center_displacement=float(np.linalg.norm(trimesh.transform_points(center[None], transform)[0]-center)),
            transform=transform.tolist(), validation_samples=len(validation),
            confidence_kind='withheld_depth_residual_not_metric_ground_truth')
        if latest_evidence is None:
            latest_evidence = evidence
        if (score(before)-score(after) < scale*.005 or score(after) > score(before)*.8
                or np.quantile(after,.9) > np.quantile(before,.9)):
            continue
        if candidate_filter is not None:
            if not candidate_filter(transform.copy()):
                rejected += 1
                continue
            evidence.update(candidate_filter_rejections=rejected,
                            selected_iteration=candidate_iterations[index], fitting_iterations=len(history))
            if fractions[index] != 1.:
                evidence['partial_step_fraction'] = fractions[index]
        return transform, dict(reason='bounded_similarity_depth_candidate' if scale_fraction else 'bounded_rigid_depth_candidate', **evidence)
    return None, dict(reason='candidate_constraints_rejected' if rejected else 'insufficient_independent_depth_improvement',
                      **latest_evidence, candidate_filter_rejections=rejected)


def propose_translation(mesh, observed, *, fraction=.08):
    observed=np.asarray(observed,float)
    observed=observed[np.isfinite(observed).all(-1)]
    if len(observed)<64:
        return None,dict(reason='insufficient_depth_observations')
    # Canonical ordering makes fitting independent of labels and point order.
    order=np.lexsort((observed[:,2],observed[:,1],observed[:,0]))
    observed=observed[order]
    observed=observed[np.linspace(0,len(observed)-1,min(384,len(observed))).astype(int)]
    fit,validation=observed[::2],observed[1::2]
    scale=float(np.linalg.norm(np.ptp(mesh.vertices,axis=0)))
    budget=scale*fraction
    if scale<=1e-8:
        return None,dict(reason='degenerate_mesh')
    def distances(points,delta):
        near,distance,_=closest_points(mesh,points-delta)
        return points-(near+delta),distance
    def score(distance):
        clipped=np.sort(distance)[:max(1,int(len(distance)*.8))]
        return float(np.sqrt(np.mean(clipped**2)))
    delta=np.zeros(3)
    _,before=distances(validation,delta)
    if score(before)<scale*.002:
        return None,dict(reason='already_matches_observed_depth',normalized_error=score(before)/scale)
    for _ in range(6):
        residual,distance=distances(fit,delta)
        keep=distance<=np.quantile(distance,.8)
        step=np.mean(residual[keep],axis=0)
        proposed=delta+step
        if np.linalg.norm(proposed)>budget:
            proposed*=budget/np.linalg.norm(proposed)
        if np.linalg.norm(proposed-delta)<scale*1e-5:
            break
        delta=proposed
    _,after=distances(validation,delta)
    improvement=score(before)-score(after)
    evidence=dict(before=score(before),after=score(after),improvement=improvement,
        budget=budget,translation=delta.tolist(),validation_samples=len(validation),
        before_p90=float(np.quantile(before,.9)),after_p90=float(np.quantile(after,.9)),
        confidence_kind='withheld_depth_residual_not_metric_ground_truth')
    if improvement<scale*.005 or score(after)>score(before)*.8 or np.quantile(after,.9)>np.quantile(before,.9):
        return None,dict(reason='insufficient_independent_depth_improvement',**evidence)
    return delta,dict(reason='bounded_depth_translation_candidate',**evidence)


def register_observed_geometry(scene, objects, run, points, placement, structure):
    from PIL import Image
    from .scene_collision import MeshIndex
    from .scene_geometry import triangles
    from .scene_ownership import composite_residuals
    from .scene_placement import object_vertices, bounds_of, update_transform
    from .scene_vanishing import fit_camera
    camera=fit_camera(points)
    if not camera['accepted']:
        return dict(changes=[],reason='camera_fit_rejected',camera=camera)
    h,w=points.shape[:2]
    masks={o['id']:np.asarray(Image.open(run/o['mask']).convert('L').resize((w,h),Image.Resampling.NEAREST))>0
           for o in objects if o.get('mask')}
    residuals=composite_residuals(masks,points)
    common=np.asarray(placement['common_transform'])
    projection=np.asarray(camera['matrix'])
    faces={o['id']:triangles(scene,o['id']) for o in objects}
    indices={}
    def index(oid):
        if oid not in indices:
            if len(indices)>=3:
                indices.pop(next(iter(indices)))
            indices[oid]=MeshIndex(faces[oid])
        return indices[oid]
    records=[];changes=[]
    for obj in objects:
        oid=obj['id']
        if oid not in masks:
            continue
        mask=residuals[oid][0] if oid in residuals else masks[oid]
        cloud=points[mask]
        valid=np.isfinite(cloud).all(-1) & (np.linalg.norm(cloud,axis=-1)>1e-6)
        if valid.sum()<64 or valid.mean()<.95:
            records.append(dict(object_id=oid,applied=False,reason='insufficient_reliable_mask_depth'))
            continue
        cloud=cloud[valid]
        cloud=cloud[::max(1,len(cloud)//2000)][:2000]
        world=trimesh.transform_points(cloud,common)
        target=index(oid)
        delta,evidence=propose_translation(target.mesh,world)
        record=dict(object_id=oid,applied=False,**evidence)
        records.append(record)
        if delta is None:
            continue
        raw_delta=common[:3,:3].T@delta
        before=cloud@projection.T;after=(cloud+raw_delta)@projection.T
        if np.any(abs(before[:,2])<1e-8) or np.any(abs(after[:,2])<1e-8):
            record['reason']='invalid_projection_after_translation';continue
        movement=np.linalg.norm(before[:,:2]/before[:,2,None]-after[:,:2]/after[:,2,None],axis=1)
        y,x=np.where(mask)
        pixel_budget=min(.03*np.hypot(w,h),.2*np.hypot(np.ptp(x),np.ptp(y)))
        record.update(projected_motion_p90=float(np.quantile(movement,.9)),pixel_budget=float(pixel_budget))
        if np.quantile(movement,.9)>pixel_budget:
            record['reason']='projected_motion_budget_exceeded';continue
        moved=faces[oid]+delta
        swept=np.stack([np.minimum(faces[oid].min((0,1)),moved.min((0,1))),
                        np.maximum(faces[oid].max((0,1)),moved.max((0,1)))])
        blocked=False;checks=[]
        for other in objects:
            sid=other['id']
            if sid==oid:
                continue
            sb=np.stack([faces[sid].min((0,1)),faces[sid].max((0,1))])
            if not np.all(np.minimum(swept[1],sb[1])-np.maximum(swept[0],sb[0])>1e-6):
                continue
            support=index(sid)
            before_counts=[support.penetration_samples(faces[oid],placement['contact_tolerance']),
                           target.penetration_samples(faces[sid],placement['contact_tolerance'])]
            after_counts=[support.penetration_samples(moved,placement['contact_tolerance']),
                          target.penetration_samples(faces[sid]-delta,placement['contact_tolerance'])]
            check=dict(other_id=sid,before_inside=before_counts,after_inside=after_counts)
            checks.append(check)
            known=all(value is not None for value in before_counts+after_counts)
            if known and any(a>b for a,b in zip(after_counts,before_counts)):
                blocked=True;record['reason']='increased_body_penetration';break
            if not known or not any(before_counts):
                hit=support.swept_collision(faces[oid],delta)
                check['swept_collision']=hit
                if hit is not False:
                    blocked=True;record['reason']='motion_collision_or_unknown';break
        record['collision_checks']=checks
        if blocked:
            continue
        for surface in structure.get('surfaces',[]):
            if 'normal' not in surface or np.dot(delta,surface['normal'])>=0:
                continue
            wall=MeshIndex(triangles(scene,surface['node']))
            if wall.swept_collision(faces[oid],delta,check_containment=False) is not False:
                blocked=True;record['reason']='room_surface_motion_collision_or_unknown';break
        if blocked:
            continue
        matrix=scene.graph[oid][0].copy();matrix[:3,3]+=delta
        scene.graph.update(frame_from=scene.graph.base_frame,frame_to=oid,matrix=matrix)
        update_transform(obj,matrix)
        bounds=bounds_of(object_vertices(scene,oid))
        obj['placement'].update(world_bounds_after=bounds.tolist(),world_center=bounds.mean(0).tolist(),
            world_bottom_center=[float(bounds[:,0].mean()),float(bounds[0,1]),float(bounds[:,2].mean())])
        obj['placement']['registration_translation']=delta.tolist()
        record['applied']=True
        faces[oid]=moved;indices.pop(oid,None)
        changes.append(record)
    return dict(changes=changes,records=records,camera=camera,uses_object_names=False,
        limitation='Bounded source-depth agreement; sampled penetration increases rejected; not metric pose ground truth')
