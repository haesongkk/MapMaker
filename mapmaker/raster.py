"""Deterministic CPU rasterizer with perspective-correct attributes and a z buffer."""

from __future__ import annotations

import numpy as np
from numba import njit


@njit(cache=True)
def rasterize(vertices, faces, attributes, texture, k, canvas, depth, owners, owner):
    """Rasterize camera-space triangles. Attributes are UV or RGB; samples at pixel centers."""
    height, width = depth.shape
    textured = attributes.shape[1] == 2
    for face_index, face in enumerate(faces):
        # Clip near plane, carrying attributes along the clipped edges.
        nattr = attributes.shape[1]
        polygon = np.empty((5, 3 + nattr), np.float64)
        count = 0
        for edge in range(3):
            a, b = face[edge], face[(edge + 1) % 3]
            za, zb = vertices[a, 2], vertices[b, 2]
            if za >= 0.05:
                polygon[count, :3] = vertices[a]
                polygon[count, 3:] = attributes[a]
                count += 1
            if (za >= 0.05) != (zb >= 0.05):
                t = (0.05 - za) / (zb - za)
                polygon[count, :3] = vertices[a] + t * (vertices[b] - vertices[a])
                polygon[count, 3:] = attributes[a] + t * (attributes[b] - attributes[a])
                count += 1
        for tri in range(1, count - 1):
            p = polygon[np.array([0, tri, tri + 1])]
            z = p[:, 2]
            x = k[0, 0] * p[:, 0] / z + k[0, 2]
            y = k[1, 1] * p[:, 1] / z + k[1, 2]
            den = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
            if abs(den) < 1e-12:
                continue
            x0, x1 = (
                max(0, int(np.ceil(x.min()))),
                min(width - 1, int(np.floor(x.max()))),
            )
            y0, y1 = (
                max(0, int(np.ceil(y.min()))),
                min(height - 1, int(np.floor(y.max()))),
            )
            for v in range(y0, y1 + 1):
                for u in range(x0, x1 + 1):
                    a = ((y[1] - y[2]) * (u - x[2]) + (x[2] - x[1]) * (v - y[2])) / den
                    b = ((y[2] - y[0]) * (u - x[2]) + (x[0] - x[2]) * (v - y[2])) / den
                    c = 1 - a - b
                    if min(a, b, c) < -1e-8:
                        continue
                    invz = a / z[0] + b / z[1] + c / z[2]
                    d = 1 / invz
                    if d >= depth[v, u]:
                        continue
                    attr = (
                        a * p[0, 3:] / z[0] + b * p[1, 3:] / z[1] + c * p[2, 3:] / z[2]
                    ) / invz
                    if textured:
                        tx = min(max(attr[0], 0.0), 1.0) * (texture.shape[1] - 1)
                        ty = (1 - min(max(attr[1], 0.0), 1.0)) * (texture.shape[0] - 1)
                        ix, iy = int(tx), int(ty)
                        jx, jy = (
                            min(ix + 1, texture.shape[1] - 1),
                            min(iy + 1, texture.shape[0] - 1),
                        )
                        fx, fy = tx - ix, ty - iy
                        color = (1 - fy) * (
                            (1 - fx) * texture[iy, ix] + fx * texture[iy, jx]
                        ) + fy * ((1 - fx) * texture[jy, ix] + fx * texture[jy, jx])
                    else:
                        color = attr
                    canvas[v, u] = np.minimum(np.maximum(color, 0), 255).astype(
                        np.uint8
                    )
                    depth[v, u] = d
                    owners[v, u] = face_index if owner == -2 else owner


def render_scene(scene, k, width, height, camera_transform=None):
    import trimesh

    canvas = np.full((height, width, 3), [32, 36, 44], dtype=np.uint8)
    depth = np.full((height, width), np.inf)
    owners = np.full((height, width), -1, dtype=np.int32)
    camera_transform = np.eye(4) if camera_transform is None else camera_transform
    names = sorted(scene.graph.nodes_geometry)
    for owner, node in enumerate(names):
        transform, name = scene.graph[node]
        mesh = scene.geometry[name]
        vertices = trimesh.transform_points(mesh.vertices, camera_transform @ transform)
        visual = mesh.visual
        material = getattr(visual, "material", None)
        texture = getattr(material, "baseColorTexture", None)
        if texture is None:
            texture = getattr(material, "image", None)
        uv = getattr(visual, "uv", None)
        if texture is not None and uv is not None:
            attributes = np.asarray(uv, dtype=float)
            texture = np.asarray(texture.convert("RGB"), dtype=float)
            factor = getattr(material, "baseColorFactor", None)
            if factor is not None:
                texture *= np.asarray(factor[:3], dtype=float) / 255.0
        else:
            colors = getattr(visual, "vertex_colors", None)
            attributes = (
                np.asarray(colors[:, :3], dtype=float)
                if colors is not None
                else np.full((len(vertices), 3), 180.0, dtype=float)
            )
            factor = getattr(material, "baseColorFactor", None)
            if colors is None and factor is not None:
                attributes[:] = np.asarray(factor[:3], dtype=float)
            texture = np.zeros((1, 1, 3), dtype=float)
        rasterize(
            np.asarray(vertices),
            np.asarray(mesh.faces),
            attributes,
            texture,
            np.asarray(k, dtype=float),
            canvas,
            depth,
            owners,
            owner,
        )
    return canvas, depth, owners, names
