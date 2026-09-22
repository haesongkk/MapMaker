from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import trimesh
from PIL import Image, ImageDraw

from .common import read_json, write_json


def render_silhouette(mesh: trimesh.Trimesh, matrix: np.ndarray, k: np.ndarray,
                      height: int, width: int) -> np.ndarray:
    vertices = trimesh.transform_points(mesh.vertices, matrix)
    projected = (k @ vertices.T).T
    projected[:, :2] /= np.maximum(projected[:, 2:3], 1e-6)
    pixels = np.round(projected[:, :2]).astype(np.int32)
    output = np.zeros((height, width), dtype=np.uint8)
    for face in mesh.faces:
        if np.any(vertices[face, 2] <= 0):
            continue
        cv2.fillConvexPoly(output, pixels[face], 255)
    return output




def render_object_color(mesh: trimesh.Trimesh, matrix: np.ndarray, k: np.ndarray,
                        canvas: np.ndarray) -> np.ndarray:
    """Project textured triangles from far to near for a source-view check render."""
    vertices = trimesh.transform_points(mesh.vertices, matrix)
    projected = (k @ vertices.T).T
    projected[:, :2] /= np.maximum(projected[:, 2:3], 1e-6)
    pixels = np.round(projected[:, :2]).astype(np.int32)
    faces = mesh.faces
    depths = vertices[faces, 2].mean(axis=1)
    order = np.argsort(depths)[::-1]
    texture = getattr(mesh.visual.material, "baseColorTexture", None) if hasattr(mesh.visual, "material") else None
    uv = getattr(mesh.visual, "uv", None)
    tex = np.asarray(texture.convert("RGB")) if texture is not None else None
    colors = getattr(mesh.visual, "vertex_colors", None)
    output = canvas.copy()
    for index in order:
        face = faces[index]
        if np.any(vertices[face, 2] <= 0):
            continue
        if tex is not None and uv is not None:
            coord = uv[face].mean(axis=0)
            tx = int(np.clip(coord[0] * (tex.shape[1]-1), 0, tex.shape[1]-1))
            ty = int(np.clip((1-coord[1]) * (tex.shape[0]-1), 0, tex.shape[0]-1))
            color = tex[ty, tx].tolist()
        elif colors is not None and len(colors):
            color = np.asarray(colors[face, :3].mean(axis=0), dtype=np.uint8).tolist()
        else:
            color = [180, 180, 180]
        cv2.fillConvexPoly(output, pixels[face], color)
    return output


def validate_scene(workdir: Path) -> dict:
    camera = read_json(workdir / "analysis/camera.json")
    k = np.asarray(camera["K"], dtype=float)
    width, height = camera["width"], camera["height"]
    scene = read_json(workdir / "scene.json")
    original = np.asarray(Image.open(workdir / "input.png").convert("RGB"))
    overlay = original.copy()
    rendered = original.copy()
    results = []
    for obj in scene["objects"]:
        mesh = trimesh.load(obj["mesh"], force="scene").to_geometry()
        if not isinstance(mesh, trimesh.Trimesh):
            continue
        predicted = render_silhouette(mesh, np.asarray(obj["source_transform"]), k, height, width) > 0
        mask_path = Path(obj.get("anchor_mask", workdir / "object_views" / obj["id"] / "anchor_mask.png"))
        observed = np.asarray(Image.open(mask_path).convert("L")) > 127
        intersection = np.logical_and(predicted, observed).sum()
        union = np.logical_or(predicted, observed).sum()
        iou = float(intersection / union) if union else 0.0
        overlay[predicted] = (0.5 * overlay[predicted] + np.array([255, 80, 0]) * 0.5).astype(np.uint8)
        rendered = render_object_color(mesh, np.asarray(obj["source_transform"]), k, rendered)
        results.append({"id": obj["id"], "silhouette_iou": iou})
    Image.fromarray(overlay).save(workdir / "validation_overlay.png")
    Image.fromarray(rendered).save(workdir / "validation_render.png")
    panel_width = 640
    panel_height = round(height * panel_width / width)
    comparison = Image.new("RGB", (panel_width * 3, panel_height + 34), (32, 32, 32))
    draw = ImageDraw.Draw(comparison)
    for index, (title, pixels) in enumerate((("Original", original),
                                             ("Photo + projected meshes", rendered),
                                             ("Mesh alignment", overlay))):
        draw.text((index * panel_width + 10, 9), title, fill="white")
        panel = Image.fromarray(pixels).resize((panel_width, panel_height), Image.Resampling.LANCZOS)
        comparison.paste(panel, (index * panel_width, 34))
    comparison.save(workdir / "scene_comparison.png")
    scores = [item["silhouette_iou"] for item in results]
    report = {"objects": results, "metric": "source_view_silhouette_iou",
              "mean_iou": float(np.mean(scores)) if scores else None,
              "low_alignment_objects": [item["id"] for item in results
                                        if item["silhouette_iou"] < 0.6]}
    write_json(workdir / "validation.json", report)
    return report
