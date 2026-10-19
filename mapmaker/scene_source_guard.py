"""Veto contact corrections that degrade the measured source view or depth."""
import numpy as np
from PIL import Image
import trimesh
from .scene_geometry import triangles
from .scene_projection import silhouette_evidence
from .scene_vanishing import fit_camera
from .scene_proximity import closest_points


def contact_source_guard(run, scene, meta, placement, points):
    camera = fit_camera(points)
    inverse = np.linalg.inv(placement['common_transform'])
    matrix = np.asarray(camera.get('matrix', np.eye(3)))
    h,w = points.shape[:2]
    def check(obj, delta):
        if not camera['accepted'] or not obj.get('mask'):
            return dict(accepted=False,reason='source_projection_unavailable')
        mask = np.asarray(Image.open(run/obj['mask']).convert('L').resize((w,h),Image.Resampling.NEAREST))>0
        faces = triangles(scene,obj['id'])
        raw = trimesh.transform_points(faces.reshape(-1,3),inverse).reshape(-1,3,3)
        shifted = raw+inverse[:3,:3]@np.asarray(delta)
        before = silhouette_evidence(raw,points,mask)
        after = silhouette_evidence(shifted,points,mask)
        evidence = dict(before_projection=before,after_projection=after,uses_object_names=False)
        if not before['accepted'] or not after['accepted']:
            return dict(evidence,accepted=False,reason='source_projection_unavailable')
        if (after['silhouette_iou']+1e-6 < before['silhouette_iou']
                or after['mask_covered_fraction']+1e-6 < before['mask_covered_fraction']):
            return dict(evidence,accepted=False,reason='contact_degrades_source_silhouette')
        cloud = points[mask]
        cloud = cloud[np.isfinite(cloud).all(-1) & (np.linalg.norm(cloud,axis=1)>1e-6)]
        if len(cloud)<64:
            return dict(evidence,accepted=False,reason='insufficient_contact_source_depth')
        order=np.lexsort((cloud[:,2],cloud[:,1],cloud[:,0]))
        cloud=cloud[order][np.linspace(0,len(cloud)-1,min(256,len(cloud))).astype(int)]
        raw_delta=inverse[:3,:3]@np.asarray(delta)
        projected_before=cloud@matrix.T
        projected_after=(cloud+raw_delta)@matrix.T
        if np.any(abs(projected_before[:,2])<1e-8) or np.any(abs(projected_after[:,2])<1e-8):
            return dict(evidence,accepted=False,reason='invalid_contact_source_projection')
        movement=np.linalg.norm(projected_after[:,:2]/projected_after[:,2,None]-
                                projected_before[:,:2]/projected_before[:,2,None],axis=1)
        y,x=np.where(mask)
        budget=min(.03*np.hypot(w,h),.2*np.hypot(np.ptp(x),np.ptp(y)))
        evidence.update(projected_motion_p90=float(np.quantile(movement,.9)),pixel_budget=float(budget))
        if np.quantile(movement,.9)>budget:
            return dict(evidence,accepted=False,reason='contact_source_motion_budget_exceeded')
        mesh=trimesh.Trimesh(raw.reshape(-1,3),np.arange(len(raw)*3).reshape(-1,3),process=False)
        _,before_distance,_=closest_points(mesh,cloud)
        _,after_distance,_=closest_points(mesh,cloud-raw_delta)
        scale=float(np.linalg.norm(np.ptp(raw.reshape(-1,3),axis=0)))
        tolerance=scale*.002
        rms=lambda values: float(np.sqrt(np.mean(np.sort(values)[:max(1,int(len(values)*.8))]**2)))
        evidence.update(depth_before=rms(before_distance),depth_after=rms(after_distance),
            depth_p90_before=float(np.quantile(before_distance,.9)),
            depth_p90_after=float(np.quantile(after_distance,.9)),depth_tolerance=tolerance)
        if (rms(after_distance)>rms(before_distance)+tolerance
                or np.quantile(after_distance,.9)>np.quantile(before_distance,.9)+tolerance):
            return dict(evidence,accepted=False,reason='contact_degrades_observed_depth')
        return dict(evidence,accepted=True,reason='contact_preserves_source_observations')
    return check
