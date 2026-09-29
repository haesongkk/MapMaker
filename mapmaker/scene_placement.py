"""CPU placement in the assembled GLB frame: +Y up, column-vector matrices.

Never normalize individual meshes: their exported origins, child transforms and
SAM3D poses must stay paired. All object roots receive one shared rigid rotation and translation.
"""

import copy
from pathlib import Path
import subprocess
import sys

import numpy as np
import trimesh

CONTACT_TOLERANCE_RATIO = 0.01
PLACEMENT_VERSION = 2
MEAN_UP_EPSILON = 1e-6
FLOOR_NODE = "background_floor"
FLOOR_MARGIN_RATIO = 0.15


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


def rotation_to_world_up(up):
    """Shortest proper rotation; exact antiparallel uses the fixed world X axis."""
    target = np.array([0., 1., 0.])
    cross = np.cross(up, target)
    sine = np.linalg.norm(cross)
    cosine = float(np.clip(up @ target, -1., 1.))
    if sine < 1e-12:
        return np.eye(3) if cosine > 0 else np.diag([1., -1., -1.])
    axis = cross / sine
    x, y, z = axis
    skew = np.array([[0., -z, y], [z, 0., -x], [-y, x, 0.]])
    return np.eye(3) + sine * skew + (1. - cosine) * (skew @ skew)


def correct_placement(scene, objects):
    """Equal-weight mean of ALL object local +Y vectors; no individual correction."""
    if not objects:
        raise ValueError("Cannot place an empty scene")
    originals, vertices, ups = {}, {}, {}
    for obj in objects:
        oid = obj["id"]
        if scene.graph.transforms.parents[oid] != scene.graph.base_frame:
            raise ValueError(f"Expected independent object root: {oid}")
        matrix = np.array(scene.graph[oid][0], dtype=float)
        lengths = np.linalg.norm(matrix[:3, :3], axis=0)
        if not np.isfinite(matrix).all() or np.any(lengths <= 1e-12):
            raise ValueError(f"Invalid object transform: {oid}")
        originals[oid] = matrix
        vertices[oid] = object_vertices(scene, oid)
        ups[oid] = matrix[:3, 1] / lengths[1]
    mean = np.mean(list(ups.values()), axis=0)
    magnitude = float(np.linalg.norm(mean))
    if not np.isfinite(magnitude) or magnitude < MEAN_UP_EPSILON:
        raise ValueError("Mean object Y-up is undefined or nearly cancels; alignment aborted")
    mean_up = mean / magnitude
    rotation = rotation_to_world_up(mean_up)
    rotated = {oid: points @ rotation.T for oid, points in vertices.items()}
    minimum = min(float(points[:, 1].min()) for points in rotated.values())
    common = np.eye(4)
    common[:3, :3] = rotation
    common[1, 3] = -minimum
    all_bounds = []
    for obj in objects:
        oid = obj["id"]
        original = originals[oid]
        matrix = common @ original
        after = bounds_of(rotated[oid] + common[:3, 3])
        all_bounds.append(after)
        scene.graph.update(frame_from=scene.graph.base_frame, frame_to=oid, matrix=matrix)
        obj["placement"] = {
            "reason": "global_mean_up_alignment", "floor_y": 0.,
            "original_matrix": original.tolist(),
            "world_up_before": ups[oid].tolist(),
            "world_up_after": (rotation @ ups[oid]).tolist(),
            "world_bounds_before": bounds_of(vertices[oid]).tolist(),
            "world_bounds_after": after.tolist(),
            "local_bounds": bounds_of(trimesh.transform_points(vertices[oid], np.linalg.inv(original))).tolist(),
            "world_center": after.mean(axis=0).tolist(),
            "world_bottom_center": [float(after[:, 0].mean()), float(after[0, 1]), float(after[:, 2].mean())],
        }
        obj["transform"] = copy.deepcopy(obj["transform"])
        scale = np.linalg.norm(matrix[:3, :3], axis=0)
        orientation = np.eye(4)
        orientation[:3, :3] = matrix[:3, :3] / scale[None, :]
        obj["transform"].update(
            matrix=matrix.tolist(), position=matrix[:3, 3].tolist(), scale=scale.tolist(),
            rotation_quaternion_wxyz=trimesh.transformations.quaternion_from_matrix(orientation).tolist(),
            matrix_convention="column vectors; shared global alignment @ official GLB object transform",
        )
    tolerance = max(float(np.median([b[1, 1] - b[0, 1] for b in all_bounds])) * CONTACT_TOLERANCE_RATIO, 1e-6)
    metrics = {}
    for phase in ("before", "after"):
        offsets = np.array([o["placement"][f"world_bounds_{phase}"][0][1] for o in objects])
        metrics[phase] = {"object_count": len(objects),
                          "floating_count": int(np.sum(offsets > tolerance)),
                          "penetrating_count": int(np.sum(offsets < -tolerance)),
                          "mean_absolute_contact_error": float(np.mean(abs(offsets)))}
    return {"floor_y": 0., "up_axis": "+Y", "floor_source": "global_rotated_minimum",
            "method": "equal_weight_all_object_mean_up", "individual_correction": False,
            "object_ids": [o["id"] for o in objects],
            "mean_up_before": mean_up.tolist(), "mean_up_after": (rotation @ mean_up).tolist(),
            "mean_up_magnitude": magnitude, "mean_up_epsilon": MEAN_UP_EPSILON,
            "rotation_matrix": rotation.tolist(), "common_transform": common.tolist(),
            "translation": common[:3, 3].tolist(),
            "minimum_y_before": min(float(v[:, 1].min()) for v in vertices.values()),
            "minimum_y_rotated": minimum, "minimum_y_after": min(float(b[0, 1]) for b in all_bounds),
            "contact_tolerance": tolerance, "metrics_scope": "all generated objects vs Y=0; not support classification",
            "metrics": metrics}


def add_floor(scene, objects, placement):
    """A thin neutral slab, top exactly at the contact plane; no room reconstruction."""
    boxes = np.array([o["placement"]["world_bounds_after"] for o in objects])
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
            "margin_each_side_ratio": FLOOR_MARGIN_RATIO, "source": "all aligned object bounds"}


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
    meta["assembly"]["method"] = "official SAM3D assembly followed by shared mean-up rotation and global grounding; separate background floor"
    placement.update(version=PLACEMENT_VERSION, original_scene_sha256=original_hash,
                     scene_sha256=sha(run / "scene.glb"), implementation_sha256=sha(Path(__file__)))
    meta["placement"] = placement
    meta["pipeline"].update(placement_method="official SAM3D + equal-weight all-object mean-up alignment", structural_geometry=True)
    meta["preview_method"] = "CPU mesh preview of final scene.glb; Gaussian previews retain original SAM3D pose and contain no floor"
    write(run / "scene_metadata.json", meta)
    if render:
        subprocess.run([sys.executable, "-m", "mapmaker.scene_preview", str(run / "scene.glb"),
                        "--out", str(run / "previews/meshes"), "--material"], check=True)
    write(run / "logs/placement.json", placement)
    return placement
