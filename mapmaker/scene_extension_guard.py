"""Abstain on conflicting inferred plane additions without deleting baseline faces."""
import numpy as np
import trimesh
from .scene_collision import MeshIndex


def triangle_keys(faces):
    return [tuple(sorted(map(tuple, face))) for face in faces]


def guard_plane_extension(baseline, candidate, obstacles, normal, point, tolerance, *, localize_conflicts=False):
    """Keep complete added components only when finite body checks are clear.

    Baseline geometry is immutable, including earlier inferred regions. This
    certifies additions only; existing intersections still require repair.
    """
    normal=np.asarray(normal,float);point=np.asarray(point,float)
    if normal.shape!=(3,) or point.shape!=(3,) or not np.isfinite(point).all() or not np.isclose(np.linalg.norm(normal),1) or tolerance<=0:
        raise ValueError('Expected a finite plane and positive tolerance')
    old=set(triangle_keys(baseline.triangles));keys=triangle_keys(candidate.triangles)
    if not old.issubset(set(keys)):
        raise ValueError('Candidate must preserve every baseline triangle')
    added=np.array([k not in old for k in keys]);ids=np.flatnonzero(added)
    adjacency=candidate.face_adjacency
    adjacency=adjacency[added[adjacency].all(axis=1)]
    components=trimesh.graph.connected_components(adjacency,nodes=ids,min_len=1)
    keep=np.ones(len(keys),bool);records=[];indices={}
    bodies=[np.asarray(f,float) for f in obstacles]
    for component in components:
        faces=candidate.triangles[component];lo,hi=faces.min((0,1)),faces.max((0,1));checks=[]
        retained=np.ones(len(component),bool)
        for i,body in enumerate(bodies):
            if not len(body):continue
            if body.ndim!=3 or body.shape[1:]!=(3,3) or not np.isfinite(body).all():
                raise ValueError('Expected finite obstacle triangles')
            if np.any(body.max((0,1))<lo) or np.any(hi<body.min((0,1))):continue
            signed=(body.reshape(-1,3)-point)@normal
            if signed.min()>=-tolerance or signed.max()<=tolerance:continue
            if i not in indices:indices[i]=MeshIndex(body)
            # The inferred patch is intentionally open. Symmetric closed-body
            # containment would always be unknown even for a watertight object.
            # After a clear boundary test, one point certifies the interior
            # state of this connected patch relative to a closed object.
            index=indices[i]
            hit=index.swept_collision(faces,np.zeros(3),check_containment=False)
            if hit is False:
                if index.mesh.is_watertight and index.mesh.is_winding_consistent:
                    try:hit=bool(index.mesh.contains(faces[0,:1]).any())
                    except (ImportError,ValueError):hit=None
                else:hit=None
            checks.append(dict(obstacle_index=i,result='unknown' if hit is None else 'intersection' if hit else 'clear'))
            if hit is not False:
                if not localize_conflicts:
                    retained[:]=False
                else:
                    # Each remaining triangle must independently pass. A
                    # connected addition can cross several unrelated objects;
                    # one conflict must not erase distant proven-clear faces.
                    lower,upper=body.min((0,1)),body.max((0,1))
                    clear_boundary=[]
                    for j in np.flatnonzero(retained):
                        f=faces[j:j+1]
                        if np.any(f.max((0,1))<lower) or np.any(upper<f.min((0,1))):continue
                        blocked=index.swept_collision(f,np.zeros(3),check_containment=False)
                        if blocked is False:
                            if index.mesh.is_watertight and index.mesh.is_winding_consistent:
                                clear_boundary.append(j)
                            else:blocked=None
                        if blocked is not False:retained[j]=False
                    if clear_boundary:
                        # Batch ray queries; each triangle still has its own
                        # independently certified clear boundary above.
                        try:
                            inside=index.mesh.contains(faces[clear_boundary,0])
                            retained[np.asarray(clear_boundary)[inside]]=False
                        except (ImportError,ValueError):retained[clear_boundary]=False
        accepted=all(c['result']=='clear' for c in checks)
        keep[component]=retained
        records.append(dict(triangles=len(component),accepted=accepted,retained_triangles=int(retained.sum()),checks=checks))
    result=candidate.copy();result.update_faces(keep);result.remove_unreferenced_vertices()
    assert old.issubset(set(triangle_keys(result.triangles)))
    return result,dict(components=records,baseline_triangles=len(baseline.faces),
        proposed_added_triangles=len(ids),retained_added_triangles=int(np.count_nonzero(keep&added)),
        rejected_added_triangles=int(np.count_nonzero(~keep)),baseline_preserved=True,
        uses_object_names=False,localize_conflicts=localize_conflicts,scope='inferred_additions_only_existing_intersections_not_certified')
