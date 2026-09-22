from __future__ import annotations

import numpy as np
import trimesh


def fit_plane(
    points: np.ndarray,
    normals: np.ndarray | None = None,
    iterations: int = 500,
    tolerance: float = 0.06,
    seed: int = 0,
) -> dict | None:
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    pts = pts[np.isfinite(pts).all(axis=1)]
    if len(pts) < 100:
        return None
    rng = np.random.default_rng(seed)
    best = np.zeros(len(pts), dtype=bool)
    best_normal = None
    for _ in range(iterations):
        sample = pts[rng.choice(len(pts), 3, replace=False)]
        n = np.cross(sample[1] - sample[0], sample[2] - sample[0])
        length = np.linalg.norm(n)
        if length < 1e-8:
            continue
        n /= length
        inliers = np.abs((pts - sample[0]) @ n) < tolerance
        if inliers.sum() > best.sum():
            best, best_normal = inliers, n
    if best_normal is None or best.sum() < max(100, len(pts) * 0.15):
        return None
    center = np.median(pts[best], axis=0)
    _, _, vt = np.linalg.svd(pts[best] - center, full_matrices=False)
    n = vt[-1]
    if n[1] > 0:
        n = -n
    return {
        "normal": n.tolist(),
        "offset": float(-n @ center),
        "inlier_fraction": float(best.mean()),
        "center": center.tolist(),
    }


def make_depth_mesh(
    rgb: np.ndarray,
    points: np.ndarray,
    valid: np.ndarray,
    excluded: np.ndarray | None = None,
    stride: int = 3,
    discontinuity: float = 0.15,
) -> trimesh.Trimesh:
    h, w = valid.shape
    ys = np.arange(0, h, stride)
    xs = np.arange(0, w, stride)
    grid = points[np.ix_(ys, xs)]
    colors = rgb[np.ix_(ys, xs)]
    good = valid[np.ix_(ys, xs)].astype(bool)
    if excluded is not None:
        good &= ~excluded[np.ix_(ys, xs)]
    good &= np.isfinite(grid).all(axis=-1) & (grid[..., 2] > 0)
    gh, gw = good.shape
    faces = []
    for y in range(gh - 1):
        for x in range(gw - 1):
            for a, b, c in (
                ((y, x), (y + 1, x), (y, x + 1)),
                ((y + 1, x + 1), (y, x + 1), (y + 1, x)),
            ):
                if not (good[a] and good[b] and good[c]):
                    continue
                z = np.array([grid[a][2], grid[b][2], grid[c][2]])
                if z.max() - z.min() > discontinuity * np.median(z):
                    continue
                faces.append([a[0] * gw + a[1], b[0] * gw + b[1], c[0] * gw + c[1]])
    return trimesh.Trimesh(
        vertices=grid.reshape(-1, 3),
        faces=faces,
        vertex_colors=np.column_stack(
            (colors.reshape(-1, 3), np.full(gh * gw, 255, dtype=np.uint8))
        ),
        process=False,
    )


def initial_transform(
    mesh: trimesh.Trimesh, points: np.ndarray, mask: np.ndarray
) -> np.ndarray:
    selected = points[mask.astype(bool)]
    selected = selected[np.isfinite(selected).all(axis=1) & (selected[:, 2] > 0)]
    if len(selected) < 25:
        raise ValueError("Object mask has too few valid depth pixels")
    center = np.median(selected, axis=0)
    lo, hi = np.quantile(selected, [0.05, 0.95], axis=0)
    target_extent = np.maximum(hi - lo, 1e-3)
    source_extent = np.maximum(mesh.extents, 1e-3)
    scale = np.clip(np.median(target_extent / source_extent), 0.01, 100)
    matrix = np.eye(4)
    matrix[:3, :3] *= scale
    matrix[:3, 3] = center - scale * mesh.bounding_box.centroid
    return matrix


def refine_transform_to_mask(
    mesh: trimesh.Trimesh,
    points: np.ndarray,
    mask: np.ndarray,
    intrinsics: np.ndarray,
    initial: np.ndarray,
) -> tuple[np.ndarray, float, str]:
    """Choose an isotropic or bounded XY fit by source-view silhouette agreement."""
    from .validation import render_silhouette

    height, width = mask.shape
    selected = points[mask.astype(bool)]
    selected = selected[np.isfinite(selected).all(axis=1) & (selected[:, 2] > 0)]
    center = np.median(selected, axis=0)
    lo, hi = np.quantile(selected, [0.05, 0.95], axis=0)
    target_extent = np.maximum(hi - lo, 1e-3)
    source_extent = np.maximum(mesh.extents, 1e-3)
    base_scale = float(initial[0, 0])
    xy_scales = np.clip(
        target_extent[:2] / source_extent[:2], base_scale * 0.5, base_scale * 2.0
    )
    alternative = np.eye(4)
    alternative[:3, :3] = np.diag([*xy_scales, base_scale])
    alternative[:3, 3] = center - alternative[:3, :3] @ mesh.bounding_box.centroid

    def score(matrix: np.ndarray) -> float:
        projected = render_silhouette(mesh, matrix, intrinsics, height, width) > 0
        union = np.logical_or(projected, mask).sum()
        return float(np.logical_and(projected, mask).sum() / union) if union else 0.0

    base_score = score(initial)
    xy_score = score(alternative)
    return (
        (alternative, xy_score, "bounded_xy")
        if xy_score > base_score
        else (initial, base_score, "isotropic")
    )


def optimize_transform(mesh, points, mask, intrinsics):
    """Fit canonical Y-up objects using yaw, anisotropic size and XYZ translation.

    Coarse pixel silhouettes guide optimization; depth residual prevents moving an
    object toward the camera merely to increase its projected size.
    """
    from scipy.optimize import minimize
    from .raster import render_scene
    import cv2

    selected = points[mask & np.isfinite(points).all(-1) & (points[..., 2] > 0)]
    if len(selected) < 25:
        raise ValueError("Too few valid object samples")
    h, w = mask.shape
    factor = min(1.0, 192 / w)
    sh, sw = round(h * factor), round(w * factor)
    target = (
        cv2.resize(mask.astype(np.uint8), (sw, sh), interpolation=cv2.INTER_NEAREST) > 0
    )
    k = intrinsics.copy()
    k[0] *= sw / w
    k[1] *= sh / h
    observed_depth = cv2.resize(
        points[..., 2].astype(np.float32), (sw, sh), interpolation=cv2.INTER_NEAREST
    )
    proxy = (
        mesh.simplify_quadric_decimation(face_count=2500)
        if len(mesh.faces) > 2500
        else mesh.copy()
    )
    proxy.visual = trimesh.visual.ColorVisuals(
        proxy, vertex_colors=np.full((len(proxy.vertices), 4), 255, dtype=np.uint8)
    )
    center = np.median(selected, axis=0)
    lo, hi = np.quantile(selected, [0.02, 0.98], axis=0)
    extent = np.maximum(hi - lo, 0.02)
    canonical = np.diag([1.0, -1.0, -1.0])
    local_center = mesh.bounding_box.centroid
    cache_scene = trimesh.Scene(proxy)
    node = next(iter(cache_scene.graph.nodes_geometry))

    def matrix(p):
        angle = p[0]
        rot = (
            np.array(
                [
                    [np.cos(angle), 0, np.sin(angle)],
                    [0, 1, 0],
                    [-np.sin(angle), 0, np.cos(angle)],
                ]
            )
            @ canonical
        )
        rotated_extent = np.ptp(mesh.bounding_box.vertices @ rot.T, axis=0)
        scale = extent / np.maximum(rotated_extent, 1e-4) * np.exp(p[1:4])
        m = np.eye(4)
        m[:3, :3] = np.diag(scale) @ rot
        m[:3, 3] = center + extent * p[4:7] - m[:3, :3] @ local_center
        return m

    def evaluate(p, report=False):
        m = matrix(p)
        cache_scene.graph.update(frame_to=node, matrix=m)
        _, depth, owners, _ = render_scene(cache_scene, k, sw, sh)
        predicted = owners >= 0
        # An observed foreground object can hide a complete mesh. Do not fit
        # permanent holes into a tabletop just because cups/books occlude it.
        occluded = (
            ~target
            & np.isfinite(observed_depth)
            & (observed_depth > 0)
            & (depth > observed_depth + 0.02 * center[2])
        )
        predicted &= ~occluded
        union = (predicted | target).sum()
        overlap = predicted & target
        iou = float(overlap.sum() / max(union, 1))
        valid_depth = overlap & np.isfinite(observed_depth) & (observed_depth > 0)
        residual = (
            float(
                np.median(np.abs(depth[valid_depth] - observed_depth[valid_depth]))
                / center[2]
            )
            if valid_depth.any()
            else 1.0
        )
        if report:
            return m, iou, residual
        return 1 - iou + 0.35 * residual + 0.005 * float(np.square(p[1:4]).sum())

    bounds = (
        [(-np.pi, np.pi)] + [(-0.5, 0.5)] * 3 + [(-0.4, 0.4), (-0.4, 0.4), (-0.5, 0.5)]
    )
    starts = []
    for yaw in [-np.pi, -np.pi / 2, 0, np.pi / 2]:
        p = np.zeros(7)
        p[0] = yaw
        starts.append((evaluate(p), p))
    start = min(starts, key=lambda v: v[0])[1]
    result = minimize(
        evaluate,
        start,
        method="Powell",
        bounds=bounds,
        options={"maxiter": 12, "maxfev": 350, "xtol": 0.015, "ftol": 0.002},
    )
    best = result.x if evaluate(result.x) < evaluate(start) else start
    m, iou, residual = evaluate(best, True)
    return m, iou, residual
