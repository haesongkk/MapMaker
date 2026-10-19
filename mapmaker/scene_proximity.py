"""Exact triangle proximity with bounded point batches and one vertex index.

The closest-point reduction follows trimesh.proximity.closest_point (MIT):
Copyright (c) 2023 Michael Dawson-Haggerty

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
import numpy as np
from scipy.spatial import cKDTree
import trimesh
from trimesh.constants import tol


def closest_points(mesh, points, *, pair_budget=262144, prune=False):
    """Preserve exact triangle queries and ties; bound simultaneous candidates.

    A single point may require every face. Otherwise the worst-case candidate
    count is bounded by pair_budget. No triangles or observation points are
    dropped. Reuse indices through trimesh's geometry-invalidated cache.
    Bounding-box distance can exclude only triangles outside the vertex-distance
    upper bound, including the existing normal-tie tolerance. Ambiguous ties use
    the original complete candidate list to preserve triangle IDs exactly.
    Pruning is opt-in: tie-heavy real meshes can cost more than the baseline.
    """
    points = np.asanyarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise ValueError('Expected finite points with shape (n, 3)')
    if pair_budget < 1 or not len(mesh.faces):
        raise ValueError('Expected a positive budget and nonempty triangle mesh')
    if not len(points):
        return np.empty((0,3)), np.empty(0), np.empty(0,dtype=np.int64)
    tree = mesh._cache['mapmaker_proximity_vertex_tree']
    if tree is None:
        tree = cKDTree(mesh.vertices[mesh.referenced_vertices])
        mesh._cache['mapmaker_proximity_vertex_tree'] = tree
    spatial = mesh.triangles_tree
    faces = mesh.triangles.view(np.ndarray)
    use_pruning = prune and len(faces) >= 4096
    if use_pruning:
        boxes = mesh._cache['mapmaker_proximity_triangle_boxes']
        if boxes is None:
            boxes = (faces.min(axis=1), faces.max(axis=1))
            mesh._cache['mapmaker_proximity_triangle_boxes'] = boxes
        lower, upper = boxes
    batch = max(1, min(32, int(pair_budget)//len(faces)))
    results = []
    vector_supported=mesh._cache['mapmaker_proximity_vector_supported']
    for start in range(0,len(points),batch):
        query = points[start:start+batch]
        radius = tree.query(query)[0].reshape(-1,1)+tol.merge
        bounds = np.column_stack((query-radius,query+radius))
        try:
            if vector_supported is False:
                candidates = [list(spatial.intersection(b)) for b in bounds]
            else:
                ids, counts = spatial.intersection_v(bounds[:,:3],bounds[:,3:])
                candidates = np.array_split(ids,np.cumsum(counts)[:-1])
        except TypeError:
            # Some Rtree/NumPy combinations fail when growing the vector
            # result buffer. Do not repeat that failed query on every batch.
            # Geometry mutation invalidates this flag along with the index.
            vector_supported=False
            candidates = [list(spatial.intersection(b)) for b in bounds]
        except Exception:
            candidates = [list(spatial.intersection(b)) for b in bounds]
        if not use_pruning:
            results.append(_reduce(mesh,faces,query,candidates))
            continue
        filtered = []
        for point, bound, ids in zip(query, radius[:,0], candidates):
            ids = np.asarray(ids, dtype=np.int64)
            if len(ids) < 64:
                filtered.append(ids)
                continue
            gap = np.maximum(np.maximum(lower[ids]-point, point-upper[ids]), 0.)
            squared = np.einsum('ij,ij->i', gap, gap)
            magnitude = max(1., bound*bound, float(np.max(np.abs(point)))**2,
                            float(np.max(np.abs(mesh.bounds)))**2)
            threshold = bound*bound + tol.merge + 64*np.finfo(float).eps*magnitude
            filtered.append(ids[squared <= threshold])
        result, ambiguous = _reduce(mesh,faces,query,filtered,with_ties=True)
        for i in np.flatnonzero(ambiguous):
            if len(filtered[i]) == len(candidates[i]):
                continue
            original = _reduce(mesh,faces,query[i:i+1],[candidates[i]])
            for k in range(3):
                result[k][i] = original[k][0]
        results.append(result)
    if vector_supported is False:
        mesh._cache['mapmaker_proximity_vector_supported']=False
    return tuple(np.concatenate([part[k] for part in results]) for k in range(3))


def _reduce(mesh, faces, points, candidates, *, with_ties=False):
    counts = list(map(len,candidates))
    if not all(counts):
        raise ValueError('No candidate triangle for a finite observation')
    all_candidates = np.concatenate(candidates).astype(np.int64,copy=False)
    query_points = points[np.repeat(np.arange(len(points)),counts)]
    close = trimesh.triangles.closest_point(faces[all_candidates],query_points)
    vectors = query_points-close
    distance = trimesh.util.diagonal_dot(vectors,vectors)
    splits = np.cumsum(counts)[:-1]
    groups = np.array_split(distance,splits)
    best = np.int64([d.argsort()[:2] if len(d)>1 else [0,0] for d in groups])
    best[1:] += splits.reshape(-1,1)
    two_distances = distance[best]
    two_candidates = all_candidates[best]
    result_close = close[best[:,0]].copy()
    result_ids = two_candidates[:,0].copy()
    result_distance = two_distances[:,0].copy()
    ties = (np.ptp(two_distances,axis=1)<tol.merge)&np.all(abs(two_distances)>tol.merge,axis=1)
    normals = mesh.face_normals[two_candidates[ties]]
    directions = vectors[best[ties]]/two_distances[ties].reshape(-1,2,1)**.5
    choice = (normals*directions).sum(axis=2).argmax(axis=1)
    result_ids[ties] = two_candidates[ties,choice]
    result_distance[ties] = two_distances[ties,choice]
    result_close[ties] = close[best[ties,choice]]
    result = (result_close,np.sqrt(result_distance),result_ids)
    if with_ties:
        return result, (np.ptp(two_distances,axis=1)<tol.merge)&(np.asarray(counts)>1)
    return result
