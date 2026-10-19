"""First-hit depth evidence in the original camera frame, independent of labels."""
import numpy as np


def visible_depth_evidence(mesh, observed, scale, *, maximum_samples=256):
    points=np.asarray(observed,float)
    if points.ndim!=2 or points.shape[1]!=3 or not np.isfinite(points).all():
        raise ValueError('Expected finite camera-space observations')
    if not np.isfinite(scale) or scale<=0 or maximum_samples<1:
        raise ValueError('Expected positive scale and sample budget')
    distance=np.linalg.norm(points,axis=1)
    valid=distance>1e-8
    points=points[valid];distance=distance[valid]
    if not len(points):return dict(available=False,reason='no_camera_rays')
    order=np.lexsort((points[:,2],points[:,1],points[:,0]))
    ids=order[np.linspace(0,len(points)-1,min(maximum_samples,len(points))).astype(int)]
    points,distance=points[ids],distance[ids]
    # Query every crossing and reduce explicitly: mesh winding and backend hit
    # ordering must not select a hidden/back surface as the visible observation.
    locations,rays,_=mesh.ray.intersects_location(np.zeros_like(points),points/distance[:,None],multiple_hits=True)
    first=np.full(len(points),np.inf)
    if len(rays):np.minimum.at(first,rays,np.linalg.norm(locations,axis=1))
    hit=np.isfinite(first)
    if not hit.any():return dict(available=True,rays=len(points),hit_fraction=0.,matched_rays=0,normalized_median=None,normalized_p90=None)
    residual=(first[hit]-distance[hit])/scale
    return dict(available=True,rays=len(points),matched_rays=int(hit.sum()),hit_fraction=float(hit.mean()),
        normalized_median=float(np.median(abs(residual))),normalized_p90=float(np.quantile(abs(residual),.9)),
        normalized_signed_median=float(np.median(residual)),
        method='nearest_positive_camera_ray_surface',
        scope='Estimated visible depth agreement; no hidden-shape or physical support certificate')
