"""Read-only orthographic geometry previews, all triangles; no source-camera claim."""

import argparse, json
from pathlib import Path
import numpy as np
import trimesh
from PIL import Image, ImageDraw

p = argparse.ArgumentParser()
p.add_argument("asset")
p.add_argument("--out", required=True)
p.add_argument("--material", action="store_true")
p.add_argument("--node")
p.add_argument("--opencv-frame", action="store_true")
p.add_argument("--view", choices=["front_Z", "top_Y", "oblique"])
a = p.parse_args()
out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)
s = trimesh.load(a.asset, force="scene", process=False)
tris = []
colors = []
palette = np.array(
    [
        [65, 130, 200],
        [230, 120, 70],
        [100, 180, 115],
        [190, 120, 200],
        [215, 180, 60],
        [70, 185, 190],
        [195, 85, 110],
        [135, 145, 165],
    ]
)
for k, node in enumerate(s.graph.nodes_geometry):
    if a.node and node != a.node:
        continue
    tf, gname = s.graph[node]
    g = s.geometry[gname]
    v = trimesh.transform_points(g.vertices, tf)
    tri = v[g.faces]
    tris.append(tri)
    col = np.tile(
        palette[k % len(palette)] if not a.material else [185, 185, 185], (len(tri), 1)
    )
    if a.material and g.visual.kind == "texture":
        mat = g.visual.material
        img = getattr(mat, "baseColorTexture", None)
        if img is None:
            img = getattr(mat, "image", None)
        if img is not None:
            tex = np.array(img.convert("RGB"))
            uv = g.visual.uv[g.faces].mean(1)
            x = np.clip(
                (uv[:, 0] * (tex.shape[1] - 1)).astype(int), 0, tex.shape[1] - 1
            )
            y = np.clip(
                ((1 - uv[:, 1]) * (tex.shape[0] - 1)).astype(int), 0, tex.shape[0] - 1
            )
            col = tex[y, x]
    if a.material and g.visual.kind == "vertex":
        col = np.asarray(g.visual.vertex_colors)[g.faces, :3].mean(1)
    if a.material and g.visual.kind == "face":
        col = np.asarray(g.visual.face_colors)[:, :3]
    colors.append(col)
t = np.concatenate(tris)
t = t * np.array([1, -1, -1]) if a.opencv_frame else t
c = np.concatenate(colors)
lo = t.min((0, 1))
hi = t.max((0, 1))
t = t - (lo + hi) / 2
views = {
    "front_Z": np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]]),
    "top_Y": np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]]),
    "oblique": np.array(
        [[0.707, 0, -0.707], [-0.408, 0.816, -0.408], [0.577, 0.577, 0.577]]
    ),
}
for name, rot in views.items():
    if a.view and name != a.view:
        continue
    tr = t @ rot.T
    n = np.cross(tr[:, 1] - tr[:, 0], tr[:, 2] - tr[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    shade = 0.35 + 0.65 * np.abs(n @ np.array([0.3, 0.5, 0.8124]))
    rgb = np.clip(c * shade[:, None], 0, 255).astype("uint8")
    projected = tr[:, :, :2]
    pmin = projected.min((0, 1))
    pmax = projected.max((0, 1))
    view_scale = 450 / max(pmax - pmin)
    xy = (projected - (pmin + pmax) / 2) * view_scale
    xy[:, :, 1] *= -1
    xy += 256
    idx = np.argsort(tr[:, :, 2].mean(1))
    im = Image.new("RGB", (512, 550), "#f4f4f4")
    d = ImageDraw.Draw(im)
    for j in idx:
        d.polygon([tuple(v) for v in xy[j]], fill=tuple(rgb[j]))
    d.text(
        (8, 520),
        name
        + (
            " | material sampled per triangle"
            if a.material
            else " | node colors, geometry only"
        ),
        fill="black",
    )
    im.save(out / (name + ".png"))
(out / "render_note.json").write_text(
    json.dumps(
        {
            "method": "orthographic painter rendering of every original triangle, graph transforms respected; per-view bounds fitted to frame",
            "source_asset": str(Path(a.asset).resolve()),
            "texture_rendered": a.material,
            "texture_limit": "CPU per-triangle centroid UV sampling, not full raster interpolation; no fine-detail quality claims",
            "colors": "texture/vertex/face colors averaged per triangle"
            if a.material
            else "debug colors per original scene node",
            "asset_modified": False,
            "selected_node": a.node,
            "source_camera_aligned": False,
            "display_axis_conversion": "OpenCV x/right y/down z/forward to x/right y/up z/back"
            if a.opencv_frame
            else None,
            "triangle_count": len(t),
        },
        indent=2,
    )
)
