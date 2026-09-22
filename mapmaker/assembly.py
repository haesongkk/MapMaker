"""Compose checked object assets and a completed, textured 3D background."""

from pathlib import Path
import shutil
import numpy as np
import trimesh
from PIL import Image
from scipy.ndimage import distance_transform_edt, binary_fill_holes
from .common import read_json, write_json
from .geometry import optimize_transform
from .reconstruction import (
    is_structure,
    surface_mesh,
    complete_background,
    mesh_health,
    bake_visible_source,
    masked_surface_mesh,
    attached_parts,
    extend_background,
)
from .standalone_render import render_glb
from .raster import render_scene


def assemble(workdir: Path, labels=None, prefix="scene"):
    rgb = np.asarray(Image.open(workdir / "input.png").convert("RGB"))
    points = np.load(workdir / "analysis/points.npy")
    valid = np.load(workdir / "analysis/valid.npy") & np.isfinite(points).all(-1)
    camera = read_json(workdir / "analysis/camera.json")
    k = np.array(camera["K"])
    objects = read_json(workdir / "objects.json")
    review = (
        read_json(workdir / "mesh_review.json")
        if (workdir / "mesh_review.json").exists()
        else {}
    )
    masks = {
        o["id"]: np.asarray(Image.open(o["anchor_mask"]).convert("L")) > 127
        for o in objects
    }
    parts = attached_parts(objects, masks)
    for child, parent in parts.items():
        masks[parent] |= masks[child]
    if labels is not None:
        objects = [o for o in objects if o["label"] in labels]
    flip = np.diag([1.0, -1.0, -1.0, 1.0])
    scene = trimesh.Scene()
    depth = points[..., 2].copy()
    indices = distance_transform_edt(
        ~valid, return_distances=False, return_indices=True
    )
    depth[~valid] = depth[tuple(indices)][~valid]
    # Resolve nested detections explicitly. Small foreground objects own their pixels.
    owned = np.zeros(valid.shape, bool)
    visible_masks = {}
    for obj in sorted(objects, key=lambda o: masks[o["id"]].sum()):
        mask = masks[obj["id"]]
        if obj["id"] in parts:
            visible_masks[obj["id"]] = mask
            continue
        visible_masks[obj["id"]] = mask & ~owned
        owned |= mask
    asset_dir = workdir / (
        "accepted_meshes" if prefix == "scene" else f"{prefix}_accepted_meshes"
    )
    shutil.rmtree(asset_dir, ignore_errors=True)
    asset_dir.mkdir(exist_ok=True)
    diagnostics = workdir / "mesh_inspection"
    diagnostics.mkdir(exist_ok=True)
    placed = []
    audit = []
    for obj in objects:
        obj_id = obj["id"]
        mask = visible_masks[obj_id]
        report = {
            "id": obj_id,
            "label": obj["label"],
            "source_pixels": int(mask.sum()),
            "structure": is_structure(obj["label"]),
        }
        if mask.sum() < 25:
            report["decision"] = "skip_duplicate"
            audit.append(report)
            continue
        path = workdir / "meshes" / f"{obj_id}.glb"
        matrix = np.eye(4)
        chosen = None
        if path.exists() and not report["structure"]:
            generated = trimesh.load(path, force="scene").to_geometry()
            health = mesh_health(generated)
            report["generated_health"] = health
            if np.isfinite(generated.vertices).all() and len(generated.faces):
                matrix, iou, residual = optimize_transform(
                    generated, points, masks[obj_id], k
                )
                singular_values = np.linalg.svd(matrix[:3, :3], compute_uv=False)
                anisotropy = float(
                    singular_values.max() / max(singular_values.min(), 1e-8)
                )
                report.update(
                    generated_scale_anisotropy=anisotropy,
                    generated_fit_iou=iou,
                    fit_metric="source_depth_occlusion_aware_iou",
                    generated_depth_relative_error=residual,
                    generated_transform=matrix.tolist(),
                )
                # Save the actual generated geometry alone at both camera angles for review.
                diagnostic = trimesh.Scene()
                diagnostic.add_geometry(
                    generated, node_name=obj_id, transform=flip @ matrix
                )
                diagnostic.metadata["source_camera"] = camera
                diagnostic_path = diagnostics / f"{obj_id}.glb"
                diagnostic.export(diagnostic_path)
                for angle in (0, 12):
                    render_glb(
                        workdir,
                        angle,
                        scene_path=diagnostic_path,
                        prefix=f"mesh_inspection/{obj_id}_generated",
                    )
                if (
                    health["usable"]
                    and iou >= 0.85
                    and residual <= 0.10
                    and anisotropy <= 8.0
                    and obj_id not in review.get("rejected", {})
                ):
                    chosen = generated
                    report["decision"] = "generated_mesh"
            if chosen is None:
                report["rejection"] = review.get("rejected", {}).get(
                    obj_id, "generated_shape_or_alignment_below_gate"
                )
        if obj_id in parts:
            report.update(
                decision="integrated_into_parent",
                parent=parts[obj_id],
                reason=(
                    "overlapping masks of the same structure merged to avoid residual fragments"
                    if report["structure"]
                    else "source cushion is part of the generated seat; avoid overlapping shells"
                ),
            )
            audit.append(report)
            continue
        if chosen is not None:
            chosen, texture_report = bake_visible_source(
                chosen, matrix, rgb, masks[obj_id], k
            )
            report.update(texture_report)
        if chosen is None:
            matrix = np.eye(4)
            chosen = masked_surface_mesh(rgb, depth, k, mask)
            report["decision"] = (
                "observed_structure"
                if report["structure"]
                else "observed_surface_fallback"
            )
            report["limitation"] = (
                "Source depth surface only; unseen sides/back are not reconstructed."
            )
        if not len(chosen.faces):
            report["decision"] = "skip_empty"
            audit.append(report)
            continue
        target = asset_dir / f"{obj_id}.glb"
        chosen.export(target)
        if obj_id in parts.values():
            combined_mask = asset_dir / f"{obj_id}_mask.png"
            Image.fromarray(masks[obj_id].astype(np.uint8) * 255).save(combined_mask)
            obj = {
                **obj,
                "source_anchor_mask": obj["anchor_mask"],
                "anchor_mask": str(combined_mask),
                "integrated_parts": [
                    child for child, parent in parts.items() if parent == obj_id
                ],
            }
        scene.add_geometry(chosen, node_name=obj_id, transform=flip @ matrix)
        placed.append(
            {
                **obj,
                "mesh": str(target),
                "source_transform": matrix.tolist(),
                "transform": (flip @ matrix).tolist(),
                "representation": report["decision"],
                "fit_method": "yaw_scale_xyz_depth"
                if report["decision"] == "generated_mesh"
                else "source_depth",
            }
        )
        audit.append(report)
    # Source-mask holes on a tabletop are observed cups/books, not missing table
    # geometry. Separate their pixels from the rear support to prevent stretched
    # triangles connecting their outlines to an inpainted background on camera moves.
    occluders = np.zeros(valid.shape, bool)
    for obj in objects:
        if obj["label"] in {"table", "coffee table", "coffee_table"}:
            mask = masks[obj["id"]]
            occluders |= binary_fill_holes(mask) & ~mask & ~owned
    if occluders.any():
        foreground = masked_surface_mesh(rgb, depth, k, occluders)
        scene.add_geometry(
            foreground, node_name="observed_tabletop_occluders", transform=flip
        )
    background_rgb, background_depth = complete_background(
        rgb, depth, valid, owned | occluders
    )
    # Continuous support closes occlusion gaps; hidden texture is inpainted, not original object pixels.
    # Extrapolated inverse-depth planes and mirrored boundary texture support small
    # camera moves. These margins are explicitly unobserved room content.
    pad = max(4, round(rgb.shape[1] * 0.12))
    padded_rgb, padded_depth, support_k = extend_background(
        background_rgb, background_depth, k, pad
    )
    background = surface_mesh(
        padded_rgb, padded_depth, support_k, stride=3, discontinuity=np.inf
    )
    scene.add_geometry(background, node_name="completed_background", transform=flip)
    scene.metadata["source_camera"] = camera
    target = workdir / f"{prefix}.glb"
    scene.export(target)
    write_json(
        workdir / f"{prefix}.json",
        {
            "camera": camera,
            "objects": placed,
            "gltf_from_opencv": flip.tolist(),
            "background": "inpainted_depth_support",
            "hidden_background": "approximate; not observed",
            "border_extension_pixels": pad,
            "border_method": "local_inverse_depth_planes_and_mirrored_texture_not_observed",
            "observed_tabletop_occluder_pixels": int(occluders.sum()),
            "mesh_audit": audit,
        },
    )
    Image.fromarray(background_rgb).save(workdir / f"{prefix}_background_texture.png")
    np.save(workdir / f"{prefix}_background_depth.npy", background_depth)
    for angle in (0, -3, 3, 12):
        render_glb(workdir, angle, scene_path=target, prefix=f"{prefix}_glb")
    exported_scene = trimesh.load(target, force="scene")
    validate(workdir, exported_scene, placed, masks, visible_masks, k, camera, prefix)
    return target


def validate(workdir, scene, objects, masks, visible_masks, k, camera, prefix):
    width, height = camera["width"], camera["height"]
    flip = np.diag([1.0, -1.0, -1.0, 1.0])
    # Evaluate at the same full-resolution pixel centers used by the source masks.
    pixels, depth, owners, names = render_scene(scene, k, width, height, flip)
    observed_depth = np.load(workdir / "analysis/depth.npy")
    results = []
    for obj in objects:
        obj_id = obj["id"]
        target = visible_masks[obj_id]
        predicted = owners == names.index(obj_id)
        union = (predicted | target).sum()
        overlap = predicted & target
        isolated = trimesh.Scene()
        mesh = trimesh.load(obj["mesh"], force="scene").to_geometry()
        isolated.add_geometry(mesh, transform=np.asarray(obj["source_transform"]))
        _, _, silhouette, _ = render_scene(isolated, k, width, height)
        shape = silhouette >= 0
        original = masks[obj_id]
        err = overlap & np.isfinite(observed_depth)
        results.append(
            {
                "id": obj_id,
                "representation": obj["representation"],
                "silhouette_iou": float(
                    (shape & original).sum() / max((shape | original).sum(), 1)
                ),
                "visible_iou": float(overlap.sum() / max(union, 1)),
                "target_visible_pixels": int(target.sum()),
                "rendered_visible_pixels": int(predicted.sum()),
                "depth_mae": float(np.abs(depth[err] - observed_depth[err]).mean())
                if err.any()
                else None,
            }
        )
    Image.fromarray(pixels).save(workdir / f"{prefix}_validation_render.png")
    report = {
        "objects": results,
        "metric": "pixel_zbuffer_visible_iou",
        "mean_iou": float(np.mean([r["silhouette_iou"] for r in results]))
        if results
        else None,
        "mean_visible_iou": float(np.mean([r["visible_iou"] for r in results]))
        if results
        else None,
        "uncovered_pixels": int((owners < 0).sum()),
        "low_alignment_objects": [r["id"] for r in results if r["visible_iou"] < 0.6],
        "caveat": "Observed surface IoU measures reprojection, not unseen geometry accuracy.",
    }
    write_json(workdir / f"{prefix}_validation.json", report)
    if prefix == "scene":
        write_json(workdir / "validation.json", report)
        Image.fromarray(pixels).save(workdir / "validation_render.png")
        original = (
            Image.open(workdir / "input.png")
            .convert("RGB")
            .resize((640, round(height * 640 / width)))
        )
        rendered = Image.fromarray(pixels).resize(original.size)
        comparison = Image.new("RGB", (1280, original.height))
        comparison.paste(original)
        comparison.paste(rendered, (640, 0))
        comparison.save(workdir / "scene_comparison.png")
