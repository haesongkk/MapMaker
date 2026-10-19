"""Finite triangle collision queries with explicit bounded-work abstention."""
import numpy as np
import trimesh
from itertools import combinations
from .scene_proximity import closest_points


def certified_penetration_repair(checks):
    """A blocked path may repair a measured initial collision, never an unknown.

    Caller must cover every possible blocker using conservative motion bounds.
    These are reconstruction pose corrections, not collision-free robot motion.
    """
    return bool(checks and all(c['after']=='clear' for c in checks) and
        any(c['before']=='intersection' for c in checks) and
        all(c['path_result']=='clear' or
            (c['path_result']=='intersection' and c['before']=='intersection'
             and c.get('penetration_confirmed') is True) for c in checks))


def initial_penetration_evidence(fixed, moving):
    """Distinguish finite-depth intrusion from mere touching; zero abstains."""
    scale=min(float(np.linalg.norm(np.ptp(moving.reshape(-1,3),axis=0))),
              float(np.linalg.norm(fixed.mesh.extents)))
    tolerance=max(scale*.002,1e-9)
    forward=fixed.penetration_samples(moving,tolerance,count=256)
    reverse=None
    if forward is None or forward==0:
        reverse=MeshIndex(moving).penetration_samples(fixed.faces,tolerance,count=256)
    confirmed=bool(any(v is not None and v>0 for v in (forward,reverse)))
    result=dict(penetration_confirmed=confirmed,
        initial_inside_samples=[forward,reverse],penetration_tolerance=tolerance,
        penetration_method='positive_inside_samples_beyond_boundary_tolerance; zero_or_unknown_abstains')
    if not confirmed:
        # Sparse interior samples can miss a shallow but real closed-body
        # intersection. A verified Boolean volume is independent evidence;
        # open/non-manifold bodies and missing optional engines still abstain.
        try:
            from .scene_overlap import OverlapSnapshot
            snapshot=OverlapSnapshot({'moving':moving,'fixed':fixed.faces})
            measured=snapshot.measure_pair('moving','fixed',np.eye(4))
            volume_floor=max(scale**3*1e-12,1e-18)
            result['closed_volume_evidence']=dict(measured,minimum_certified_volume=volume_floor)
            if measured['available'] and measured['before']>volume_floor:
                result.update(penetration_confirmed=True,penetration_method='verified_positive_closed_boolean_volume')
        except (ImportError,ValueError,RuntimeError) as error:
            result['closed_volume_evidence']=dict(available=False,reason=type(error).__name__)
    return result


def rigid_triangle_hull_hits(start, end, fixed, padding=0.):
    """Conservative SAT for endpoint triangle hulls, expanded by an arc bound."""
    start, end, fixed = np.asarray(start, float), np.asarray(end, float), np.asarray(fixed, float)
    hull = np.concatenate([start, end], axis=1)
    origin = hull[:, :1]
    hull, fixed = hull-origin, fixed-origin
    edge_pairs = np.asarray(list(combinations(range(6), 2)))
    triples = np.asarray(list(combinations(range(6), 3)))
    edges = hull[:, edge_pairs[:,1]]-hull[:, edge_pairs[:,0]]
    normals = np.cross(hull[:,triples[:,1]]-hull[:,triples[:,0]],
                       hull[:,triples[:,2]]-hull[:,triples[:,0]])
    other_edges = fixed[:,[1,2,0]]-fixed
    other_normal = np.cross(other_edges[:,0], other_edges[:,1])
    axes = np.concatenate([normals, other_normal[:,None],
        np.cross(edges[:,:,None], other_edges[:,None]).reshape(-1,45,3),
        np.cross(other_normal[:,None], edges),
        np.cross(other_normal[:,None], other_edges)], axis=1)
    lengths = np.linalg.norm(axes, axis=-1)
    axes = np.divide(axes, lengths[...,None], out=np.zeros_like(axes), where=lengths[...,None]>1e-12)
    a = np.einsum('nvc,nac->nav', hull, axes)
    b = np.einsum('nvc,nac->nav', fixed, axes)
    separated = ((a.max(-1)+padding < b.min(-1)-1e-9) |
                 (b.max(-1) < a.min(-1)-padding-1e-9)) & (lengths>1e-12)
    return ~separated.any(-1)


def swept_triangle_hits(a, delta, b, tolerance=1e-9):
    """SAT for a translated triangle's convex sweep against fixed triangles.

    Includes in-plane separating axes for zero-motion/coplanar cases. Touching
    counts as a collision; this routine never certifies a near miss as clear.
    """
    a, b = np.asarray(a, float), np.asarray(b, float)
    delta = np.broadcast_to(np.asarray(delta, float), (len(a), 3))
    ea, eb = a[:, [1,2,0]]-a, b[:, [1,2,0]]-b
    na, nb = np.cross(ea[:,0], ea[:,1]), np.cross(eb[:,0], eb[:,1])
    moving_edges = np.concatenate([ea, delta[:,None]], axis=1)
    axes = np.concatenate([na[:,None], nb[:,None], np.cross(ea, delta[:,None]),
        np.cross(moving_edges[:,:,None], eb[:,None]).reshape(-1,12,3),
        np.cross(na[:,None], ea), np.cross(nb[:,None], eb)], axis=1)
    lengths = np.linalg.norm(axes, axis=-1)
    axes = np.divide(axes, lengths[...,None], out=np.zeros_like(axes), where=lengths[...,None]>1e-12)
    # Translation to a local origin avoids cancellation for far-away scenes.
    origin = a[:,0:1]
    av = np.concatenate([a-origin, a+delta[:,None]-origin], axis=1)
    bv = b-origin
    pa = np.einsum('nvc,nac->nav', av, axes)
    pb = np.einsum('nvc,nac->nav', bv, axes)
    separated = ((pa.max(-1) < pb.min(-1)-tolerance) |
                 (pb.max(-1) < pa.min(-1)-tolerance)) & (lengths>1e-12)
    return ~separated.any(-1)


class MeshIndex:
    def __init__(self, faces):
        faces = np.asarray(faces, float)
        self.mesh = trimesh.Trimesh(vertices=faces.reshape(-1,3),
            faces=np.arange(len(faces)*3).reshape(-1,3), process=True)
        self.faces = self.mesh.triangles
        self.lower, self.upper = self.faces.min(1), self.faces.max(1)
        self.tree = self.mesh.triangles_tree

    def _candidate_intersections(self, lower, upper, candidates):
        """Ordered broad-phase queries with bounded bulk-result allocation.

        A group count bounds each member's result size. Dense groups and older
        spatial-index bindings retain the scalar query; no query is approximated.
        """
        for offset in range(0, len(candidates), 128):
            group = candidates[offset:offset+128]
            envelope = np.r_[lower[group].min(0), upper[group].max(0)]
            count = self.tree.count(envelope)
            if count == 0:
                continue
            bulk = None
            if count * len(group) <= 100000:
                try:
                    bulk = self.tree.intersection_v(lower[group], upper[group])
                except (AttributeError, TypeError, NotImplementedError):
                    # Some bindings lack bulk queries or reject resizing on
                    # their NumPy version. The established scalar path is exact.
                    pass
            if bulk is None:
                for i in group:
                    ids = np.asarray(list(self.tree.intersection(np.r_[lower[i], upper[i]])), int)
                    if len(ids):
                        yield i, ids
            else:
                ids, counts = bulk
                position = 0
                for i, size in zip(group, counts):
                    size = int(size)
                    if size:
                        yield i, ids[position:position+size]
                    position += size

    def first_foot_contact(self, moving, delta, tolerance):
        """Refine a downward sampled contact to the first finite mesh contact.

        Only a clear initial state and a foot-only first intersection qualify.
        The correction must remain within the caller's existing contact tolerance;
        an enclosure obstruction cannot become a new support candidate.
        """
        moving, delta = np.asarray(moving, float), np.asarray(delta, float)
        if delta[1] >= 0 or np.any(delta[[0, 2]] != 0):
            return None, {'reason': 'not_downward_contact'}
        if self.swept_collision(moving, np.zeros(3), check_containment=False) is not False:
            return None, {'reason': 'initial_contact_not_clear'}
        if self.swept_collision(moving, delta, check_containment=False) is not True:
            return None, {'reason': 'no_certified_contact_bracket'}
        low, high = 0., 1.
        for _ in range(24):
            mid = (low + high) / 2
            hit = self.swept_collision(moving, delta * mid, check_containment=False)
            if hit is None:
                return None, {'reason': 'contact_search_unknown'}
            if hit:
                high = mid
            else:
                low = mid
        adjustment = float(np.linalg.norm(delta * (1 - low)))
        if low <= 0 or adjustment > tolerance:
            return None, {'reason': 'contact_adjustment_out_of_bounds', 'adjustment': adjustment}
        bottom, top = moving[:, :, 1].min(), moving[:, :, 1].max()
        # Clip long side triangles at the foot boundary: keeping whole faces
        # would misclassify their bottom edges as body contact on coarse meshes.
        body_vertices, body_faces, _ = trimesh.intersections.slice_faces_plane(
            moving.reshape(-1, 3), np.arange(len(moving)*3).reshape(-1, 3),
            np.array([0., 1., 0.]), np.array([0., bottom + .1 * (top - bottom), 0.]))
        body = body_vertices[body_faces]
        if len(body) and self.swept_collision(body, delta * high, check_containment=False) is not False:
            return None, {'reason': 'first_contact_not_confined_to_foot'}
        return delta * low, dict(reason='finite_mesh_first_foot_contact',
            safe_fraction=low, contact_fraction=high, adjustment=adjustment,
            tolerance=float(tolerance))

    def penetration_samples(self, moving, tolerance, count=64):
        """Area-spaced surface samples with measured depth inside a closed mesh.

        Positive counts are evidence; zero is not a disjointness certificate.
        """
        if not self.mesh.is_watertight or not self.mesh.is_winding_consistent:
            return None
        area = trimesh.triangles.area(moving)
        cumulative = np.cumsum(area)
        if not len(area) or cumulative[-1] <= 0:
            return None
        ids = np.searchsorted(cumulative, (np.arange(count)+.5)/count*cumulative[-1])
        points = moving[ids].mean(1)
        inside = self.mesh.contains(points)
        if not inside.any():
            return 0
        _, distance, _ = closest_points(self.mesh, points[inside])
        return int(np.count_nonzero(distance > tolerance))

    def swept_collision(self, moving, delta, *, max_pairs=100000, check_containment=True):
        """True: collision; False: clear closed bodies; None: unknown/budget.

        All moving faces whose swept bounds overlap are queried, not a vertex
        sample. Enclosed disconnected bodies are checked separately afterward.
        """
        moving = np.asarray(moving, float)
        lower = moving.min(1) + np.minimum(delta, 0)
        upper = moving.max(1) + np.maximum(delta, 0)
        bounds = self.mesh.bounds
        candidates = np.flatnonzero(np.all((upper >= bounds[0]) & (lower <= bounds[1]), axis=1))
        pairs = 0
        for i, ids in self._candidate_intersections(lower, upper, candidates):
            pairs += len(ids)
            if pairs > max_pairs:
                return None
            if len(ids) and swept_triangle_hits(np.broadcast_to(moving[i], (len(ids),3,3)), delta, self.faces[ids]).any():
                return True
        if not check_containment:
            return False
        return self._containment_collision(moving)

    def _containment_collision(self, moving):
        # An open fixed surface has no certified interior. Avoid rebuilding the
        # potentially very large moving topology when the result is already
        # unknown under the existing containment policy.
        if not self.mesh.is_watertight:
            return None
        other = trimesh.Trimesh(vertices=moving.reshape(-1,3),
            faces=np.arange(len(moving)*3).reshape(-1,3), process=True)
        if not other.is_watertight:
            return None
        for inner, outer in ((other, self.mesh), (self.mesh, other)):
            components = trimesh.graph.connected_components(inner.edges_unique,
                nodes=np.arange(len(inner.vertices)), min_len=1)
            points = inner.vertices[[component[0] for component in components]]
            if outer.contains(points).any():
                return True
        return False

    def rigid_swept_collision(self, moving, transform, *, max_pairs=100000, check_containment=True):
        """Bounded rigid motion; chord hulls inflated to enclose rotation arcs.

        Unknown remains unknown for unclassified open bodies. This function
        does not weaken the existing solid-containment policy.
        """
        return self._pose_swept_collision(moving,transform,max_pairs=max_pairs,
            check_containment=check_containment,allow_scale=False)

    def similarity_swept_collision(self, moving, transform, *, max_pairs=100000, check_containment=True):
        """Uniform scaling and rotation with a conservative curved-path bound."""
        return self._pose_swept_collision(moving,transform,max_pairs=max_pairs,
            check_containment=check_containment,allow_scale=True)

    def _pose_swept_collision(self, moving, transform, *, max_pairs, check_containment, allow_scale):
        from scipy.spatial.transform import Rotation
        moving, transform = np.asarray(moving, float), np.asarray(transform, float)
        if transform.shape != (4,4):
            raise ValueError('Expected a finite rigid transform')
        r = transform[:3,:3]
        factor=float(np.cbrt(np.linalg.det(r))) if allow_scale else 1.
        if (not np.isfinite(transform).all()
                or factor <= 0
                or not np.allclose(r.T@r, np.eye(3)*factor**2, atol=1e-7)
                or not np.isclose(np.linalg.det(r), factor**3, atol=1e-7)
                or not np.allclose(transform[3], [0,0,0,1])):
            raise ValueError('Expected a finite rigid transform')
        vector = Rotation.from_matrix(r/factor).as_rotvec()
        angle = np.linalg.norm(vector)
        center = (moving.min((0,1))+moving.max((0,1)))/2
        translation = r@center+transform[:3,3]-center
        radius = float(np.linalg.norm(moving-center, axis=-1).max())
        steps = max(1, int(np.ceil(angle/np.deg2rad(2))))
        # For p(t)=s(t)R(t)p, ||p''|| <= radius*(s_max*angle²+2*|ds|*angle).
        # The chord interpolation error on a segment is bounded by M*h²/8.
        padding = radius*(max(1.,factor)*angle**2+2*abs(factor-1)*angle)/(8*steps**2)+1e-9
        start = moving
        pairs = 0
        for step in range(1, steps+1):
            t = step/steps
            end = (1+(factor-1)*t)*(moving-center)@Rotation.from_rotvec(vector*t).as_matrix().T+center+translation*t
            lower = np.minimum(start.min(1),end.min(1))-padding
            upper = np.maximum(start.max(1),end.max(1))+padding
            bounds = self.mesh.bounds
            candidates = np.flatnonzero(np.all((upper >= bounds[0]) & (lower <= bounds[1]), axis=1))
            for i, ids in self._candidate_intersections(lower, upper, candidates):
                pairs += len(ids)
                if pairs > max_pairs:
                    return None
                for batch in range(0, len(ids), 256):
                    selected = ids[batch:batch+256]
                    if rigid_triangle_hull_hits(np.broadcast_to(start[i],(len(selected),3,3)),
                            np.broadcast_to(end[i],(len(selected),3,3)), self.faces[selected], padding).any():
                        return True
            start = end
        return self._containment_collision(moving) if check_containment else False
