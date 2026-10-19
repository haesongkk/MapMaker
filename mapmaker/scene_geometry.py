"""Bounded CPU geometry queries. Unknown geometry is never certified clear."""
import numpy as np
import trimesh


def wall_contact(vertices, faces, normal, point):
    """Bounded normal translation to a finite plane with a broad contact patch.

    Used for walls and ceilings; the inward plane normal determines direction.
    """
    normal = np.asarray(normal, dtype=float)
    distance = (vertices-np.asarray(point))@normal
    size = np.ptp(vertices, axis=0)
    limit = max(np.linalg.norm(size)*.04, 1e-6)
    gap = float(distance.min())
    if abs(gap) > limit or np.median(distance) <= 0:
        return None
    # Use the actual wall triangles, not its infinite fitted plane.
    rotation = trimesh.geometry.align_vectors(normal, [0,1,0])
    local = trimesh.transform_points(vertices, rotation)
    wall = trimesh.transform_points(faces.reshape(-1,3), rotation).reshape(-1,3,3)
    near = local[distance <= gap+max(np.ptp(distance)*.1, 1e-6)]
    lower, upper = near.min(axis=0), near.max(axis=0)
    footprint = (upper-lower)[[0,2]]
    if np.any(footprint < np.ptp(local, axis=0)[[0,2]]*.5):
        return None
    center = (lower+upper)[[0,2]]/2
    queries = [center] + [center+footprint*[x,z]*.35 for x in (-1,1) for z in (-1,1)]
    if any(surface_height(wall, p) is None for p in queries):
        return None
    return -gap*normal


def triangles(scene, oid, *, root_transform=None):
    result = []
    for node in scene.graph.nodes_geometry:
        parent = node
        while parent not in (oid, scene.graph.base_frame):
            parent = scene.graph.transforms.parents.get(parent, scene.graph.base_frame)
        if parent == oid:
            matrix, name = scene.graph[node]
            if root_transform is not None:
                relative, _ = scene.graph.get(frame_to=node, frame_from=oid)
                matrix = np.asarray(root_transform) @ relative
            mesh = scene.geometry[name]
            result.append(trimesh.transform_points(mesh.vertices, matrix)[mesh.faces])
    return np.concatenate(result) if result else np.empty((0, 3, 3))


class HorizontalSurface:
    """Reusable triangle index; exact barycentric queries on open or closed meshes."""
    def __init__(self, faces):
        a, b, c = faces[:, 0], faces[:, 1], faces[:, 2]
        normal = np.cross(b-a, c-a)
        den = (b[:, 2]-c[:, 2])*(a[:, 0]-c[:, 0]) + (c[:, 0]-b[:, 0])*(a[:, 2]-c[:, 2])
        valid = (abs(normal[:, 1]) >= .85*np.linalg.norm(normal, axis=1)) & (abs(den) > 1e-12)
        self.a, self.b, self.c, self.den = a[valid], b[valid], c[valid], den[valid]
        selected = faces[valid][:, :, [0, 2]]
        self.lower, self.upper = selected.min(axis=1), selected.max(axis=1)

    def height(self, xz, maximum=None):
        hit = np.all((xz >= self.lower-1e-7) & (xz <= self.upper+1e-7), axis=1)
        if not hit.any():
            return None
        a, b, c, den = self.a[hit], self.b[hit], self.c[hit], self.den[hit]
        u = ((b[:, 2]-c[:, 2])*(xz[0]-c[:, 0]) + (c[:, 0]-b[:, 0])*(xz[1]-c[:, 2]))/den
        v = ((c[:, 2]-a[:, 2])*(xz[0]-c[:, 0]) + (a[:, 0]-c[:, 0])*(xz[1]-c[:, 2]))/den
        inside = (u >= -1e-7) & (v >= -1e-7) & (u+v <= 1+1e-7)
        heights = u*a[:, 1] + v*b[:, 1] + (1-u-v)*c[:, 1]
        if maximum is not None:
            inside &= heights <= maximum
        return float(heights[inside].max()) if inside.any() else None


def surface_height(faces, xz, *, maximum=None):
    """Highest actual near-horizontal triangle beneath a vertical ray."""
    return HorizontalSurface(faces).height(xz, maximum)


def contact_footprint(vertices, *, grid=5, max_tilt_degrees=0.):
    """Sample actual low geometry, not corners of an empty enclosing rectangle.

    Equal-weight spatial cells limit tessellation bias; preserve separate feet.
    """
    lower, upper = vertices.min(axis=0), vertices.max(axis=0)
    if not 0 <= max_tilt_degrees <= 8:
        raise ValueError('Foot sampling tilt must be between 0 and 8 degrees')
    band = max((upper[1]-lower[1])*.05, 1e-7)
    band += np.tan(np.deg2rad(max_tilt_degrees))*np.linalg.norm((upper-lower)[[0,2]])
    low = vertices[vertices[:, 1] <= lower[1] + band]
    extent = np.maximum(np.ptp(low[:, [0, 2]], axis=0), 1e-9)
    cells = np.minimum(((low[:, [0, 2]]-low[:, [0, 2]].min(axis=0))/extent*grid).astype(int), grid-1)
    samples = []
    for cell in np.unique(cells, axis=0):
        group = low[np.all(cells == cell, axis=1)]
        # Select a real lowest vertex, deterministic under vertex reordering.
        order = np.lexsort((group[:, 2], group[:, 0], group[:, 1]))
        samples.append(group[order[0]])
    return np.asarray(samples)


def inside_support_polygon(points, center, *, margin=0.):
    """Convex support polygon test without requiring a surface at its center."""
    pts = sorted(set(map(tuple, np.asarray(points))))
    if len(pts) < 3:
        return False
    cross = lambda a, b, c: float((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))
    halves = []
    for ordered in (pts, pts[::-1]):
        hull = []
        for p in ordered:
            while len(hull) >= 2 and cross(hull[-2], hull[-1], p) <= 0:
                hull.pop()
            hull.append(p)
        halves.append(hull[:-1])
    hull = halves[0]+halves[1]
    if len(hull) < 3:
        return False
    return all(cross(a, b, center) >= margin * np.linalg.norm(np.subtract(b, a)) - 1e-9
               for a, b in zip(hull, hull[1:]+hull[:1]))


def support_translation(vertices, faces, limit, tolerance, *, surface=None):
    """Infer bounded vertical contact from actual feet, including open surfaces.

    Only actual high contacts bear load: an overhang need not have support at
    every footprint cell. The load-bearing polygon must strictly enclose center.
    The center is a geometric bounds proxy, not a measured mass center.
    """
    samples = contact_footprint(vertices)
    bottom = float(vertices[:, 1].min())
    surface = surface if surface is not None else HorizontalSurface(faces)
    heights = [surface.height(p[[0, 2]], maximum=bottom+limit) for p in samples]
    evidence = dict(queries=len(heights), missing_queries=sum(h is None for h in heights))
    known = np.asarray([h is not None for h in heights])
    if known.sum() < 3:
        return None, dict(reason='missing_support_surface', **evidence)
    samples = samples[known]
    offsets = np.asarray([h for h in heights if h is not None])-samples[:, 1]
    spread = float(np.ptp(offsets))
    evidence.update(offset_spread=spread, tolerance=float(tolerance))
    shift = float(np.max(offsets))
    if abs(shift) > limit:
        return None, dict(reason='support_shift_out_of_bounds', shift=shift, limit=float(limit), **evidence)
    center = (vertices.min(axis=0)+vertices.max(axis=0))[[0, 2]]/2
    contacting = samples[offsets >= shift - tolerance][:, [0, 2]]
    evidence['load_bearing_queries'] = len(contacting)
    # Do not balance a body on one corner/edge simply because its enclosing
    # footprint was broad. Require the actual high contacts to enclose center.
    margin = max(float(np.ptp(vertices, axis=0)[[0, 2]].max()) * .01, 1e-9)
    if not inside_support_polygon(contacting, center, margin=margin):
        reason = ('missing_support_surface' if evidence['missing_queries'] else
                  'nonuniform_support_height' if spread > tolerance else 'unstable_support_polygon')
        return None, dict(reason=reason, **evidence)
    return np.array([0., shift, 0.]), dict(reason='observed_foot_surface_contact', shift=shift, **evidence)


def sampled_penetration(faces_a, faces_b, tolerance):
    """Positive result proves sampled points are inside closed B, not an exact volume.

    A negative result does NOT prove disjointness. Open meshes return unknown.
    Chunked solid-angle winding avoids optional spatial-index dependencies.
    """
    if len(faces_b) > 250000:
        return None  # Explicit unknown when the bounded CPU budget is exceeded.
    mesh = trimesh.Trimesh(vertices=faces_b.reshape(-1, 3),
        faces=np.arange(len(faces_b)*3).reshape(-1, 3), process=True)
    if not mesh.is_watertight or not mesh.is_winding_consistent:
        return None
    samples = np.concatenate([faces_a.reshape(-1, 3), faces_a.mean(axis=1)])
    samples = samples[::max(1, len(samples)//48)][:48]
    lower, upper = mesh.bounds
    samples = samples[np.all((samples > lower+tolerance) & (samples < upper-tolerance), axis=1)]
    count = 0
    for p in samples:
        total = 0.
        for start in range(0, len(faces_b), 8192):
            a, b, c = (faces_b[start:start+8192]-p).transpose(1, 0, 2)
            la, lb, lc = [np.linalg.norm(v, axis=1) for v in (a, b, c)]
            numerator = np.einsum('ij,ij->i', a, np.cross(b, c))
            denominator = la*lb*lc + np.einsum('ij,ij->i', a,b)*lc + np.einsum('ij,ij->i', b,c)*la + np.einsum('ij,ij->i', c,a)*lb
            total += np.sum(2*np.arctan2(numerator, denominator))
        if abs(total) > 2*np.pi:
            count += 1
    return count
