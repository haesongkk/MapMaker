"""Direction-independent sampled contact retention evidence, not deletion authority."""
import numpy as np
import trimesh
from .scene_proximity import closest_points


def contact_retention(removed_faces, retained_faces, other_faces, tolerance, *, samples=512):
    """Check that measured near-contact points remain near the retained mesh.

    Unlike a vertical support test this also detects wall and side contacts.
    Sampling cannot prove that no unsampled contact exists; an empty set is
    explicitly inconclusive. Callers still need identity and geometry evidence.
    """
    arrays=[np.asarray(f,float) for f in (removed_faces,retained_faces,other_faces)]
    if any(f.ndim!=3 or f.shape[1:]!=(3,3) or not len(f) or not np.isfinite(f).all() for f in arrays):
        raise ValueError('Expected nonempty finite triangles')
    if not np.isfinite(tolerance) or tolerance<=0 or samples<1:
        raise ValueError('Expected positive tolerance and sample count')
    old,new,other=arrays
    lower=old.min((0,1))-tolerance;upper=old.max((0,1))+tolerance
    relevant=other[np.all(other.max(1)>=lower,axis=1)&np.all(other.min(1)<=upper,axis=1)]
    if not len(relevant):
        return dict(status='no_nearby_bounds',observed_contacts=0,suppression_authorized=False)
    points=np.unique(np.concatenate([relevant.reshape(-1,3),relevant.mean(1)]),axis=0)
    points=points[np.linspace(0,len(points)-1,min(samples,len(points))).astype(int)]
    def mesh(f):return trimesh.Trimesh(f.reshape(-1,3),np.arange(len(f)*3).reshape(-1,3),process=False)
    _,before,_=closest_points(mesh(old),points)
    contact=before<=tolerance
    if not contact.any():
        return dict(status='no_sampled_contact',sampled_points=len(points),observed_contacts=0,suppression_authorized=False)
    _,after,_=closest_points(mesh(new),points[contact])
    lost=after>tolerance
    return dict(status='sampled_contact_lost' if lost.any() else 'sampled_contacts_retained',
        sampled_points=len(points),observed_contacts=int(contact.sum()),lost_contacts=int(lost.sum()),
        maximum_before_distance=float(before[contact].max()),maximum_after_distance=float(after.max()),
        suppression_authorized=False,scope='sampled_surface_proximity_not_physical_support_or_exhaustive_proof')
