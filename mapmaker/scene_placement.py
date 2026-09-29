"""CPU placement in the assembled GLB frame: +Y up, column-vector matrices.

Never normalize individual meshes: their exported origins, child transforms and
SAM3D poses must stay paired. Only object root Y translations are corrected.
"""

import copy
from pathlib import Path
import subprocess
import sys

import numpy as np
import trimesh

FLOOR_CATEGORIES = frozenset({
    "sofa", "couch", "loveseat", "chair", "armchair", "office chair",
    "table", "coffee table", "dining table", "desk", "computer desk",
    "bed", "cabinet", "bureau", "dresser", "wardrobe", "nightstand",
    "refrigerator", "bookcase", "bookshelf", "ottoman", "hassock", "bar stool",
})
MAX_SHIFT_HEIGHT_RATIO = 0.5
CONTACT_TOLERANCE_RATIO = 0.01
PLACEMENT_VERSION = 1
FLOOR_NODE = "background_floor"
FLOOR_MARGIN_RATIO = 0.15
SUPPORTED_CATEGORIES = {
    "bedding": {"bed"}, "pillow": {"bed", "sofa", "couch", "loveseat"},
    "book": {"table", "coffee table", "desk", "computer desk"},
    "centerpiece": {"table", "dining table"},
    "desktop": {"desk", "computer desk"}, "monitor": {"desk", "computer desk"},
    "cup": {"table", "coffee table", "desk", "computer desk"},
}


def object_vertices(scene, object_id):
    """Include every descendant instance, applying its complete graph transform."""
    points = []
    for node in scene.graph.nodes_geometry:
        parent = node
        while parent != object_id and parent != scene.graph.base_frame:
            parent = scene.graph.transforms.parents.get(parent, scene.graph.base_frame)
        if parent == object_id:
            matrix, name = scene.graph[node]
            points.append(trimesh.transform_points(scene.geometry[name].vertices, matrix))
    if not points:
        raise ValueError(f"Object has no geometry: {object_id}")
    vertices = np.concatenate(points)
    if not np.isfinite(vertices).all():
        raise ValueError(f"Non-finite object geometry: {object_id}")
    return vertices


def bounds_of(vertices):
    return np.array([vertices.min(axis=0), vertices.max(axis=0)])


def correct_placement(scene, objects):
    """Median support bottom minimizes total vertical displacement; skip outliers."""
    bounds = {obj["id"]: bounds_of(object_vertices(scene, obj["id"])) for obj in objects}
    supports = [o for o in objects if o.get("name", "").lower().strip() in FLOOR_CATEGORIES]
    if not bounds:
        raise ValueError("Cannot place an empty scene")
    floor_y = float(np.median([bounds[o["id"]][0, 1] for o in supports])) if supports else float(
        min(b[0, 1] for b in bounds.values()))
    height = float(np.median([bounds[o["id"]][1, 1] - bounds[o["id"]][0, 1]
                             for o in (supports or objects)]))
    tolerance = max(height * CONTACT_TOLERANCE_RATIO, 1e-6)
    support_ids = {o["id"] for o in supports}
    shifts = {}
    for obj in supports:
        b = bounds[obj["id"]]
        delta = floor_y - b[0, 1]
        if abs(delta) <= max(MAX_SHIFT_HEIGHT_RATIO * (b[1, 1] - b[0, 1]), tolerance):
            shifts[obj["id"]] = float(delta)
    attached = {}
    for obj in objects:
        allowed = SUPPORTED_CATEGORIES.get(obj.get("name", "").lower().strip(), set())
        b = bounds[obj["id"]]
        footprint = np.prod(np.maximum(b[1, [0, 2]] - b[0, [0, 2]], 1e-12))
        candidates = []
        for support in supports:
            sid = support["id"]
            if support.get("name", "").lower().strip() not in allowed or sid not in shifts:
                continue
            sb = bounds[sid]
            overlap = np.maximum(0, np.minimum(b[1, [0, 2]], sb[1, [0, 2]]) - np.maximum(b[0, [0, 2]], sb[0, [0, 2]]))
            # A conservative one-level attachment preserves existing contact; no new snapping.
            h = sb[1, 1] - sb[0, 1]
            if np.prod(overlap) / footprint >= 0.5 and sb[0, 1] + 0.4 * h <= b[0, 1] <= sb[1, 1] + 0.15 * h:
                candidates.append(sid)
        if len(candidates) == 1:
            attached[obj["id"]] = candidates[0]
    for obj in objects:
        oid = obj["id"]
        matrix = np.array(scene.graph[oid][0], dtype=float)
        original = matrix.copy()
        before = bounds[oid]
        delta = floor_y - before[0, 1]
        reason = "category_not_floor_supported"
        applied = 0.0
        if oid in support_ids:
            if oid in shifts:
                applied = shifts[oid]
                reason = "floor_contact"
            else:
                reason = "excessive_shift_skipped"
        elif oid in attached:
            applied = shifts[attached[oid]]
            reason = "follow_existing_support"
        matrix[1, 3] += applied
        # Production assembly has independent roots; fail instead of double-applying a parent.
        if scene.graph.transforms.parents[oid] != scene.graph.base_frame:
            raise ValueError(f"Expected independent object root: {oid}")
        scene.graph.update(frame_from=scene.graph.base_frame, frame_to=oid, matrix=matrix)
        local = trimesh.transform_points(object_vertices(scene, oid), np.linalg.inv(matrix))
        after = bounds_of(object_vertices(scene, oid))
        obj["placement"] = {
            "reason": reason, "floor_supported": oid in support_ids,
            "support_object": attached.get(oid),
            "delta_y": applied, "floor_y": floor_y,
            "original_matrix": original.tolist(),
            "local_bounds": bounds_of(local).tolist(),
            "world_bounds_before": before.tolist(), "world_bounds_after": after.tolist(),
            "world_center": after.mean(axis=0).tolist(),
            "world_bottom_center": [float(after[:, 0].mean()), float(after[0, 1]), float(after[:, 2].mean())],
        }
        obj["transform"] = copy.deepcopy(obj["transform"])
        obj["transform"]["matrix"] = matrix.tolist()
        obj["transform"]["position"] = matrix[:3, 3].tolist()
        obj["transform"]["matrix_convention"] = (
            "column vectors; official SAM3D + inverse GLB export rotation; world Y contact translation")
    metrics = {}
    for phase in ("before", "after"):
        offsets = np.array([o["placement"][f"world_bounds_{phase}"][0][1] - floor_y for o in supports])
        metrics[phase] = {
            "floor_supported_count": len(supports),
            "floating_count": int(np.sum(offsets > tolerance)),
            "penetrating_count": int(np.sum(offsets < -tolerance)),
            "mean_absolute_contact_error": float(np.mean(abs(offsets))) if len(offsets) else None,
        }
    return {"floor_y": floor_y, "up_axis": "+Y", "floor_source": "median_support_bottom" if supports else "scene_bottom",
            "contact_tolerance": tolerance, "metrics": metrics,
            "support_ids": sorted(support_ids), "max_shift_height_ratio": MAX_SHIFT_HEIGHT_RATIO}


def add_floor(scene, objects, placement):
    """A thin neutral slab, top exactly at the contact plane; no room reconstruction."""
    selected = [o for o in objects if o["id"] in placement["support_ids"]] or objects
    boxes = np.array([o["placement"]["world_bounds_after"] for o in selected])
    low, high = boxes[:, 0].min(axis=0), boxes[:, 1].max(axis=0)
    span = high[[0, 2]] - low[[0, 2]]
    unit = max(float(span.max()), 1e-3)
    size = np.maximum(span, unit * 0.05) * (1 + 2 * FLOOR_MARGIN_RATIO)
    thickness = unit * 0.005
    floor = trimesh.creation.box(extents=[size[0], thickness, size[1]])
    floor.visual.vertex_colors = [185, 182, 175, 255]
    matrix = np.eye(4)
    matrix[:3, 3] = [(low[0] + high[0]) / 2, placement["floor_y"] - thickness / 2, (low[2] + high[2]) / 2]
    scene.add_geometry(floor, node_name=FLOOR_NODE, geom_name=FLOOR_NODE, transform=matrix)
    return {"node": FLOOR_NODE, "kind": "floor", "top_y": placement["floor_y"],
            "size_xz": size.tolist(), "thickness": thickness,
            "margin_each_side_ratio": FLOOR_MARGIN_RATIO, "source": "support footprint or scene bounds"}


def finalize_scene(run, *, render=True):
    """Finalize an assembled run, also usable on verified legacy worker results.

    Caller publishes done only after this returns. Original pose/asset files stay
    untouched. Version + scene hash prevents reapplying shifts on transfer.
    """
    from .scene_run import read, write, sha

    run = Path(run)
    meta = read(run / "scene_metadata.json")
    existing = meta.get("placement", {})
    if existing.get("version") == PLACEMENT_VERSION:
        if existing.get("scene_sha256") != sha(run / "scene.glb"):
            raise ValueError("Finalized scene hash mismatch")
        return existing
    if existing:
        raise ValueError("Unsupported placement version; replay from an uncorrected run")
    objects = [o for o in meta["objects"] if o.get("status") == "generated"]
    scene = trimesh.load(run / "scene.glb", force="scene", process=False)
    if FLOOR_NODE in scene.graph.nodes:
        raise ValueError("Unversioned background floor already exists")
    original_hash = sha(run / "scene.glb")
    placement = correct_placement(scene, objects)
    meta["background"] = [add_floor(scene, objects, placement)]
    scene.export(run / "scene.glb")
    reloaded = trimesh.load(run / "scene.glb", force="scene", process=False)
    for obj in objects:
        if not np.allclose(reloaded.graph[obj["id"]][0], obj["transform"]["matrix"], atol=1e-6):
            raise ValueError(f"Placement transform changed in GLB: {obj['id']}")
        if not np.allclose(bounds_of(object_vertices(reloaded, obj["id"])), obj["placement"]["world_bounds_after"], atol=1e-6):
            raise ValueError(f"Placement bounds changed in GLB: {obj['id']}")
    meta.setdefault("assembly", {}).update(bounds=reloaded.bounds.tolist(), geometry_nodes=len(reloaded.graph.nodes_geometry))
    meta["assembly"]["method"] = "official SAM3D assembly followed by CPU floor contact correction; separate background floor"
    placement.update(version=PLACEMENT_VERSION, original_scene_sha256=original_hash,
                     scene_sha256=sha(run / "scene.glb"), implementation_sha256=sha(Path(__file__)))
    meta["placement"] = placement
    meta["pipeline"].update(placement_method="official SAM3D + conservative world Y floor contact", structural_geometry=True)
    meta["preview_method"] = "CPU mesh preview of final scene.glb; Gaussian previews retain original SAM3D pose and contain no floor"
    write(run / "scene_metadata.json", meta)
    if render:
        subprocess.run([sys.executable, "-m", "mapmaker.scene_preview", str(run / "scene.glb"),
                        "--out", str(run / "previews/meshes"), "--material"], check=True)
    write(run / "logs/placement.json", placement)
    return placement
