"""Render scene.glb directly, without using the input photograph as a canvas."""
from __future__ import annotations

from pathlib import Path
import cv2
import numpy as np
import trimesh
from PIL import Image

from .common import read_json


def render_glb(workdir: Path, yaw_degrees: float = 0, scale: float = 0.5) -> Path:
    camera = read_json(workdir / 'analysis/camera.json')
    width, height = round(camera['width'] * scale), round(camera['height'] * scale)
    k = np.asarray(camera['K'], dtype=np.float64) * scale
    k[2, 2] = 1
    scene = trimesh.load(workdir / 'scene.glb', force='scene')
    # GLB is Y-up with the source camera looking along -Z. Change to OpenCV axes.
    gltf_to_cv = np.diag([1., -1., -1., 1.])
    yaw = np.deg2rad(yaw_degrees)
    rotation = np.array([[np.cos(yaw), 0, -np.sin(yaw)],
                         [0, 1, 0],
                         [np.sin(yaw), 0, np.cos(yaw)]])
    all_pixels, all_depths, all_colors = [], [], []
    for node in scene.graph.nodes_geometry:
        transform, name = scene.graph[node]
        mesh = scene.geometry[name]
        matrix = gltf_to_cv @ transform
        vertices = trimesh.transform_points(mesh.vertices, matrix)
        # Rotate the virtual camera about a point in the room.
        pivot = np.array([0., 0., 3.])
        vertices = (vertices - pivot) @ rotation.T + pivot
        z = vertices[:, 2]
        projected = vertices @ k.T
        projected[:, :2] /= np.maximum(projected[:, 2:3], 1e-6)
        faces = mesh.faces
        valid = np.all(z[faces] > 0.05, axis=1)
        faces = faces[valid]
        pixels = np.rint(projected[faces, :2]).astype(np.int32)
        depths = z[faces].mean(axis=1)
        visual = mesh.visual
        texture = getattr(getattr(visual, 'material', None), 'baseColorTexture', None)
        uv = getattr(visual, 'uv', None)
        if texture is not None and uv is not None:
            tex = np.asarray(texture.convert('RGB'))
            coords = uv[faces].mean(axis=1)
            tx = np.clip((coords[:, 0] * (tex.shape[1] - 1)).astype(int), 0, tex.shape[1] - 1)
            ty = np.clip(((1 - coords[:, 1]) * (tex.shape[0] - 1)).astype(int), 0, tex.shape[0] - 1)
            colors = tex[ty, tx]
        elif hasattr(visual, 'vertex_colors') and len(visual.vertex_colors):
            colors = visual.vertex_colors[faces, :3].mean(axis=1).astype(np.uint8)
        else:
            colors = np.full((len(faces), 3), 180, dtype=np.uint8)
        all_pixels.append(pixels)
        all_depths.append(depths)
        all_colors.append(colors)
    pixels = np.concatenate(all_pixels)
    depths = np.concatenate(all_depths)
    colors = np.concatenate(all_colors)
    canvas = np.full((height, width, 3), 235, dtype=np.uint8)
    for index in np.argsort(depths)[::-1]:
        triangle = pixels[index]
        if (triangle[:, 0].max() < 0 or triangle[:, 0].min() >= width or
                triangle[:, 1].max() < 0 or triangle[:, 1].min() >= height):
            continue
        cv2.fillConvexPoly(canvas, triangle, colors[index].tolist())
    suffix = 'source' if yaw_degrees == 0 else f'yaw_{yaw_degrees:g}'
    path = workdir / f'scene_glb_{suffix}.png'
    Image.fromarray(canvas).save(path)
    return path
