"""Observed surface reconstruction and conservative completion of hidden background.

These meshes reconstruct measured front surfaces, not unseen object backs.
"""

from __future__ import annotations
import cv2
import numpy as np
import trimesh
from PIL import Image
from scipy.ndimage import distance_transform_edt, binary_erosion

STRUCTURAL = {
    "curtain",
    "wall",
    "wood_wall",
    "wood wall",
    "shelf",
    "shelve",
    "entertainment_center",
    "entertainment center",
    "cabinet",
    "window",
    "television",
    "door",
    "ceiling",
    "floor",
    "blinds",
}


def is_structure(label):
    return label.replace("_", " ") in {x.replace("_", " ") for x in STRUCTURAL}


def surface_mesh(rgb, depth, k, mask=None, stride=2, discontinuity=0.12):
    h, w = depth.shape
    ys = np.unique(np.r_[np.arange(0, h, stride), h - 1])
    xs = np.unique(np.r_[np.arange(0, w, stride), w - 1])
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    z = depth[yy, xx]
    vertices = np.stack(
        ((xx - k[0, 2]) * z / k[0, 0], (yy - k[1, 2]) * z / k[1, 1], z), -1
    ).reshape(-1, 3)
    good = np.isfinite(z) & (z > 0)
    if mask is not None:
        good &= mask[yy, xx]
    gh, gw = z.shape
    a = (np.arange(gh - 1)[:, None] * gw + np.arange(gw - 1)[None, :]).ravel()
    faces = np.concatenate(
        (np.stack((a, a + gw, a + 1), 1), np.stack((a + gw + 1, a + 1, a + gw), 1))
    )
    ok = good.ravel()[faces].all(1)
    zz = z.ravel()[faces]
    ok &= (zz.max(1) - zz.min(1)) <= discontinuity * np.maximum(
        np.median(zz, axis=1), 1e-5
    )
    faces = faces[ok]
    uv = np.stack((xx / (w - 1), 1 - yy / (h - 1)), -1).reshape(-1, 2)
    # Invalid vertices must not pollute GLB bounds.
    vertices = np.nan_to_num(vertices)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=Image.fromarray(rgb),
        metallicFactor=0.0,
        roughnessFactor=1.0,
        doubleSided=True,
    )
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    mesh.remove_unreferenced_vertices()
    return mesh


def complete_background(rgb, depth, valid, excluded):
    """Fill removed regions with surrounding colors and depth strictly behind the observation.

    Hidden geometry is an approximation. Inverse depth interpolation respects planar
    perspective better than linear interpolation of XYZ. Never reuse object colors.
    """
    good = valid & np.isfinite(depth) & (depth > 0)
    if not good.any():
        raise ValueError("No valid depth for reconstruction")
    nearest = distance_transform_edt(~good, return_distances=False, return_indices=True)
    clean = depth[tuple(nearest)].astype(np.float32)
    hole = excluded | ~good
    if not hole.any():
        return rgb.copy(), clean
    h, w = depth.shape
    size = (min(w, 320), max(1, round(h * min(w, 320) / w)))
    small_mask = (
        cv2.resize(hole.astype(np.float32), size, interpolation=cv2.INTER_AREA) > 0
    ).astype(np.uint8)
    small_mask = cv2.dilate(small_mask, np.ones((3, 3), np.uint8))
    color = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
    color = cv2.inpaint(color, small_mask, 5, cv2.INPAINT_TELEA)
    inv = cv2.resize(1 / clean, size, interpolation=cv2.INTER_AREA)
    inv = cv2.inpaint(inv, small_mask, 5, cv2.INPAINT_NS)
    filled = 1 / np.maximum(cv2.resize(inv, (w, h)), 1e-3)
    out_depth = clean.copy()
    # Behind both the interpolated surrounding support and removed object surfaces.
    out_depth[hole] = np.maximum(
        filled[hole], clean[hole] + np.maximum(0.08, 0.03 * clean[hole])
    )
    out_rgb = rgb.copy()
    out_rgb[hole] = cv2.resize(color, (w, h))[hole]
    return out_rgb, out_depth


def mesh_health(mesh):
    finite = bool(np.isfinite(mesh.vertices).all())
    if not finite or not len(mesh.faces):
        return {"usable": False, "reason": "empty_or_nonfinite"}
    # GLB texture seams duplicate vertices; they are not physical cracks.
    topology = mesh.copy()
    topology.merge_vertices(merge_tex=True, merge_norm=True)
    components = trimesh.graph.connected_components(
        topology.face_adjacency, nodes=np.arange(len(topology.faces))
    )
    areas = np.array([mesh.area_faces[c].sum() for c in components])
    largest = float(areas.max() / max(areas.sum(), 1e-9)) if len(areas) else 0.0
    degenerate = float((mesh.area_faces < 1e-12).mean())
    return {
        "usable": bool(largest >= 0.9 and degenerate < 0.01),
        "components": len(components),
        "largest_component_area_fraction": largest,
        "degenerate_fraction": degenerate,
        "watertight": bool(topology.is_watertight),
        "vertices": len(mesh.vertices),
        "faces": len(mesh.faces),
    }


def bake_visible_source(mesh, matrix, rgb, mask, k):
    """Bake source colors on visible triangles; preserve generated texture elsewhere.

    Colors outside the object's source mask are extended from its own nearest
    pixel, so wall pixels or foreground occluders cannot stain the object.
    All data is embedded in the resulting GLB material, never the render canvas.
    """
    from .raster import rasterize

    material = getattr(mesh.visual, "material", None)
    texture = getattr(material, "baseColorTexture", None)
    if texture is None:
        texture = getattr(material, "image", None)
    uv = getattr(mesh.visual, "uv", None)
    if texture is None or uv is None:
        return mesh, {"source_baked_face_fraction": 0.0, "reason": "no_generated_uv"}
    h, w = mask.shape
    vertices = trimesh.transform_points(mesh.vertices, matrix)
    depth = np.full((h, w), np.inf)
    face_ids = np.full((h, w), -1, np.int32)
    rasterize(
        vertices,
        np.asarray(mesh.faces),
        np.full((len(vertices), 3), 180.0),
        np.zeros((1, 1, 3)),
        k,
        np.zeros((h, w, 3), np.uint8),
        depth,
        face_ids,
        -2,
    )
    visible = np.zeros(len(mesh.faces), bool)
    visible[np.unique(face_ids[face_ids >= 0])] = True
    # Extend one triangle ring to cover subpixel faces at the silhouette without
    # spraying the source photograph over the unseen back of the object.
    topology = mesh.copy()
    topology.merge_vertices(merge_tex=True, merge_norm=True)
    adjacency = topology.face_adjacency
    border = adjacency[visible[adjacency].any(axis=1)]
    visible[border.ravel()] = True
    safe_mask = binary_erosion(mask, iterations=2)
    if not safe_mask.any():
        safe_mask = mask
    indices = distance_transform_edt(
        ~safe_mask, return_distances=False, return_indices=True
    )
    source = rgb[tuple(indices)]
    generated = np.asarray(texture.convert("RGB"))
    th, tw = generated.shape[:2]
    ah, aw = max(h, th), w + tw
    atlas = np.zeros((ah, aw, 3), dtype=np.uint8)
    atlas[:h, :w] = source
    atlas[:th, w:] = generated
    # Duplicate UV seam vertices without modifying the geometry.
    flattened = mesh.faces.ravel()
    old_uv = np.asarray(uv)[flattened]
    atlas_uv = np.column_stack(
        (
            (w + old_uv[:, 0] * (tw - 1)) / (aw - 1),
            1 - (1 - old_uv[:, 1]) * (th - 1) / (ah - 1),
        )
    )
    vertex_pixels = vertices @ k.T
    vertex_pixels = vertex_pixels[:, :2] / np.maximum(vertex_pixels[:, 2:3], 1e-8)
    source_uv = np.column_stack(
        (
            np.clip(vertex_pixels[:, 0], 0, w - 1) / (aw - 1),
            1 - np.clip(vertex_pixels[:, 1], 0, h - 1) / (ah - 1),
        )
    )
    baked = np.repeat(visible, 3)
    atlas_uv[baked] = source_uv[flattened[baked]]
    result = trimesh.Trimesh(
        mesh.vertices[flattened],
        np.arange(len(flattened)).reshape(-1, 3),
        process=False,
    )
    result.visual = trimesh.visual.TextureVisuals(
        uv=atlas_uv,
        material=trimesh.visual.material.PBRMaterial(
            baseColorTexture=Image.fromarray(atlas),
            metallicFactor=0.0,
            roughnessFactor=1.0,
            doubleSided=True,
        ),
    )
    return result, {
        "source_baked_face_fraction": float(visible.mean()),
        "unseen_faces": "original_generated_texture",
    }


def masked_surface_mesh(rgb, depth, k, mask):
    """One shared-vertex quad per observed pixel, including thin mask boundaries.

    Corner depths average only pixels belonging to this object. Neighbouring
    foreground/background pixels cannot pull its boundary into a stretched edge.
    """
    h, w = mask.shape
    numerator = np.zeros((h + 1, w + 1), float)
    denominator = np.zeros_like(numerator)
    for dy in (0, 1):
        for dx in (0, 1):
            numerator[dy : dy + h, dx : dx + w] += np.where(mask, depth, 0)
            denominator[dy : dy + h, dx : dx + w] += mask
    z = numerator / np.maximum(denominator, 1)
    y, x = np.meshgrid(np.arange(h + 1) - 0.5, np.arange(w + 1) - 0.5, indexing="ij")
    vertices = np.stack(
        ((x - k[0, 2]) * z / k[0, 0], (y - k[1, 2]) * z / k[1, 1], z), -1
    ).reshape(-1, 3)
    py, px = np.where(mask)
    a = py * (w + 1) + px
    faces = np.concatenate(
        (np.stack((a, a + w + 1, a + 1), 1), np.stack((a + w + 2, a + 1, a + w + 1), 1))
    )
    uv = np.stack((x / (w - 1), 1 - y / (h - 1)), -1).reshape(-1, 2)
    mesh = trimesh.Trimesh(vertices, faces, process=False)
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=uv,
        material=trimesh.visual.material.PBRMaterial(
            baseColorTexture=Image.fromarray(rgb),
            metallicFactor=0.0,
            roughnessFactor=1.0,
            doubleSided=True,
        ),
    )
    mesh.remove_unreferenced_vertices()
    return mesh


def attached_parts(objects, masks):
    """Cushions mostly contained in a seat are part of that seat, not duplicate seats."""
    result = {}
    for child in objects:
        if child["label"] not in {"pillow", "cushion"}:
            continue
        mask = masks[child["id"]]
        candidates = []
        for parent in objects:
            if parent["label"] not in {"couch", "sofa", "chair", "armchair", "bed"}:
                continue
            fraction = float((mask & masks[parent["id"]]).sum() / max(mask.sum(), 1))
            if fraction >= 0.85:
                candidates.append((fraction, parent["id"]))
        if candidates:
            result[child["id"]] = max(candidates)[1]
    structures = sorted(
        (o for o in objects if is_structure(o["label"])),
        key=lambda o: (-o.get("confidence", 0), o["id"]),
    )
    for index, child in enumerate(structures):
        mask = masks[child["id"]]
        for parent in structures[:index]:
            if parent["label"] != child["label"]:
                continue
            other = masks[parent["id"]]
            overlap = (mask & other).sum() / max(min(mask.sum(), other.sum()), 1)
            if overlap >= 0.85:
                root = parent["id"]
                while root in result:
                    root = result[root]
                result[child["id"]] = root
                break
    return result


def extend_background(rgb, depth, k, pad):
    """Extrapolate local inverse-depth planes; mirror texture in unobserved margins."""
    inv = 1 / depth
    h, w = depth.shape
    sy, sx = min(32, h - 1), min(32, w - 1)
    vertical = np.pad(inv, ((pad, pad), (0, 0)), mode="edge")
    if sy:
        vertical[:pad] = (
            inv[0] - np.arange(pad, 0, -1)[:, None] * (inv[sy] - inv[0]) / sy
        )
        vertical[-pad:] = (
            inv[-1] + np.arange(1, pad + 1)[:, None] * (inv[-1] - inv[-1 - sy]) / sy
        )
    padded = np.pad(vertical, ((0, 0), (pad, pad)), mode="edge")
    if sx:
        padded[:, :pad] = (
            vertical[:, 0, None]
            - np.arange(pad, 0, -1)[None, :]
            * (vertical[:, sx, None] - vertical[:, 0, None])
            / sx
        )
        padded[:, -pad:] = (
            vertical[:, -1, None]
            + np.arange(1, pad + 1)[None, :]
            * (vertical[:, -1, None] - vertical[:, -1 - sx, None])
            / sx
        )
    padded = np.clip(padded, inv.min() * 0.25, inv.max() * 4)
    intrinsics = k.copy()
    intrinsics[0, 2] += pad
    intrinsics[1, 2] += pad
    return (
        np.pad(rgb, ((pad, pad), (pad, pad), (0, 0)), mode="reflect"),
        1 / padded,
        intrinsics,
    )
