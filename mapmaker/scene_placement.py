"""CPU placement in the assembled GLB frame: +Y up, column-vector matrices.

Never normalize individual meshes: their exported origins, child transforms and
SAM3D poses must stay paired. Shared alignment preserves relative orientation;
individual moves require geometric evidence, never object names.
"""

import copy
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import trimesh

CONTACT_TOLERANCE_RATIO = 0.01
PLACEMENT_VERSION = 10
MEAN_UP_EPSILON = 1e-6
FLOOR_NODE = "background_floor"



def update_transform(obj, matrix):
    scale = np.linalg.norm(matrix[:3, :3], axis=0)
    orientation = np.eye(4)
    orientation[:3, :3] = matrix[:3, :3] / scale[None, :]
    obj["transform"] = copy.deepcopy(obj["transform"])
    obj["transform"].update(
        matrix=matrix.tolist(), position=matrix[:3, 3].tolist(), scale=scale.tolist(),
        rotation_quaternion_wxyz=trimesh.transformations.quaternion_from_matrix(orientation).tolist(),
        matrix_convention="column vectors; individual transform @ global alignment @ official GLB transform",
    )


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


def remove_object_tree(scene, oid):
    descendants = []
    for node in scene.graph.nodes_geometry:
        parent = node
        while parent not in (oid, scene.graph.base_frame):
            parent = scene.graph.transforms.parents.get(parent, scene.graph.base_frame)
        if parent == oid:
            descendants.append(node)
    for node in descendants:
        _, geometry = scene.graph[node]
        scene.delete_geometry(geometry)
        if node in scene.graph.nodes:
            scene.graph.transforms.remove_node(node)
    if oid in scene.graph.nodes:
        scene.graph.transforms.remove_node(oid)


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


def correct_placement(scene, objects, orientation=None):
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
    if (not np.isfinite(magnitude) or magnitude < MEAN_UP_EPSILON) and not (orientation and orientation.get('accepted')):
        raise ValueError("Mean object Y-up is undefined or nearly cancels; alignment aborted")
    mean_up = mean / magnitude if magnitude >= MEAN_UP_EPSILON else np.asarray(orientation['up'])
    alignment_up = np.asarray(orientation["up"]) if orientation and orientation.get("accepted") else mean_up
    rotation = rotation_to_world_up(alignment_up)
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
        update_transform(obj, matrix)
    tolerance = max(float(np.median([b[1, 1] - b[0, 1] for b in all_bounds])) * CONTACT_TOLERANCE_RATIO, 1e-6)
    metrics = {}
    for phase in ("before", "after"):
        offsets = np.array([o["placement"][f"world_bounds_{phase}"][0][1] for o in objects])
        metrics[phase] = {"object_count": len(objects),
                          "floating_count": int(np.sum(offsets > tolerance)),
                          "penetrating_count": int(np.sum(offsets < -tolerance)),
                          "mean_absolute_contact_error": float(np.mean(abs(offsets)))}
    return {"floor_y": 0., "up_axis": "+Y", "floor_source": "global_rotated_minimum",
            "method": orientation.get('reason', 'pointmap_surface_normals') if orientation and orientation.get("accepted") else "equal_weight_all_object_mean_up",
            "orientation_evidence": orientation or {"accepted": False, "reason": "no_pointmap"}, "individual_correction": False,
            "object_ids": [o["id"] for o in objects],
            "mean_up_before": mean_up.tolist(), "mean_up_after": (rotation @ mean_up).tolist(),
            "mean_up_magnitude": magnitude, "mean_up_epsilon": MEAN_UP_EPSILON,
            "rotation_matrix": rotation.tolist(), "common_transform": common.tolist(),
            "translation": common[:3, 3].tolist(),
            "minimum_y_before": min(float(v[:, 1].min()) for v in vertices.values()),
            "minimum_y_rotated": minimum, "minimum_y_after": min(float(b[0, 1]) for b in all_bounds),
            "contact_tolerance": tolerance, "metrics_scope": "all generated objects vs Y=0; not support classification",
            "metrics": metrics}


def align_objects(scene, objects, placement):
    """Preserve relative pose: no semantic grounding or individual upright prior."""
    for obj in objects:
        record = obj['placement']
        record['global_matrix'] = obj['transform']['matrix']
        record['world_bounds_global'] = record['world_bounds_after']
        record['world_up_global'] = record['world_up_after']
        record['individual'] = dict(applied=False, grounded=False,
            reason='preserve_pose_until_geometric_evidence', transform=np.eye(4).tolist(),
            ground_shift_y=0.)
    placement.update(individual_correction=False, individual_object_ids=[],
                     grounded_object_ids=[], individual_method='preserve_relative_pose')
    return placement


def group_export_nodes(scene, objects, surfaces):
    """Explicit GLB hierarchy, retaining every object's world transform."""
    groups = {'objects': 'mapmaker_objects', 'space': 'mapmaker_space'}
    # SceneGraph.update adds edges but does not remove a previous parent's edge.
    # A replay of an already grouped GLB can therefore export multiple parents.
    # Rebuild one canonical parent tree from current world transforms instead.
    original = scene.graph
    nodes = [node for node in original.nodes if node != original.base_frame and node not in groups.values()]
    world = {node: original[node][0].copy() for node in nodes}
    parents = dict(original.transforms.parents)
    overrides = {obj['id']: groups['objects'] for obj in objects}
    overrides.update({surface['node']: groups['space'] for surface in surfaces})
    graph = trimesh.scene.transforms.SceneGraph(base_frame=original.base_frame)
    for group in groups.values():
        graph.update(frame_from=original.base_frame, frame_to=group, matrix=np.eye(4))
    for node in nodes:
        parent = overrides.get(node, parents.get(node, original.base_frame))
        parent_world = world[parent] if parent in world else np.eye(4)
        attributes = {key: copy.deepcopy(value) for key, value in original.transforms.node_data[node].items()
                      if key in ('geometry', 'metadata')}
        graph.update(frame_from=parent, frame_to=node,
                     matrix=np.linalg.inv(parent_world) @ world[node], **attributes)
    scene.graph = graph
    return groups


def finalize_scene(run, *, render=True, overlap_repair=None, supported_repair=None):
    """Finalize an assembled run, also usable on verified legacy worker results.

    Caller publishes done only after this returns. Original pose/asset files stay
    untouched. Version + scene hash prevents reapplying shifts on transfer.
    """
    from .scene_run import read, write, sha

    if overlap_repair is None:
        setting = os.environ.get('MAPMAKER_OVERLAP_REPAIR', '0')
        if setting not in ('0', '1'):
            raise ValueError('MAPMAKER_OVERLAP_REPAIR must be 0 or 1')
        overlap_repair = setting == '1'
    if supported_repair is None:
        setting = os.environ.get('MAPMAKER_SUPPORTED_REPAIR', '0')
        if setting not in ('0','1'):
            raise ValueError('MAPMAKER_SUPPORTED_REPAIR must be 0 or 1')
        supported_repair = setting == '1'
    run = Path(run)
    meta = read(run / "scene_metadata.json")
    if overlap_repair or supported_repair:
        if not meta.get('pointmap'):
            raise ValueError('Overlap repair requires a verified pointmap')
    existing = meta.get("placement", {})
    if existing.get("version") == PLACEMENT_VERSION:
        if existing.get("scene_sha256") != sha(run / "scene.glb"):
            raise ValueError("Finalized scene hash mismatch")
        if overlap_repair and not existing.get('overlap_refinement', {}).get('complete'):
            raise ValueError('Overlap repair requires replay from uncorrected inference assets')
        if supported_repair and not existing.get('supported_refinement', {}).get('complete'):
            raise ValueError('Supported repair requires replay from uncorrected inference assets')
        if not any(b.get("node") == FLOOR_NODE for b in meta.get("background", [])):
            return existing
        # Legacy v4 results already have aligned objects: remove only their slab.
        scene = trimesh.load(run / "scene.glb", force="scene", process=False)
        if FLOOR_NODE in scene.graph.nodes_geometry:
            _, geometry = scene.graph[FLOOR_NODE]
            scene.delete_geometry(geometry)
            scene.graph.transforms.remove_node(FLOOR_NODE)
        scene.export(run / "scene.glb")
        meta["background"] = []
        meta["pipeline"]["structural_geometry"] = False
        meta["assembly"].update(bounds=scene.bounds.tolist(), geometry_nodes=len(scene.graph.nodes_geometry))
        meta["assembly"]["method"] = "official SAM3D assembly + up alignment and grounding; no background geometry"
        existing["scene_sha256"] = sha(run / "scene.glb")
        write(run / "scene_metadata.json", meta)
        write(run / "logs/placement.json", existing)
        if render:
            subprocess.run([sys.executable, "-m", "mapmaker.scene_preview", str(run / "scene.glb"),
                            "--out", str(run / "previews/meshes"), "--material"], check=True)
        return existing
    if existing and existing.get('version') not in (4, 5, 6, 7, 8):
        raise ValueError("Unsupported placement version; replay from an uncorrected run")
    if overlap_repair or supported_repair:
        # An already verified finalized result needs no native work in the
        # parent interpreter; fresh geometry processing always requires it.
        import manifold3d
    objects = [o for o in meta["objects"] if o.get("status") == "generated"]
    scene = trimesh.load(run / "scene.glb", force="scene", process=False)
    if existing.get('version') in (4, 5, 6, 7, 8):
        if existing.get('scene_sha256') != sha(run / 'scene.glb'):
            raise ValueError('Finalized scene hash mismatch')
        # Replay from recorded original roots, never apply another correction to v4 poses.
        for obj in objects:
            original = np.asarray(obj['placement']['original_matrix'], dtype=float)
            scene.graph.update(frame_from=scene.graph.base_frame, frame_to=obj['id'], matrix=original)
        if FLOOR_NODE in scene.graph.nodes_geometry:
            _, geometry = scene.graph[FLOOR_NODE]
            scene.delete_geometry(geometry)
            scene.graph.transforms.remove_node(FLOOR_NODE)
    if existing.get('version') in (6, 7, 8):
        for record in meta.get('structure', {}).get('surfaces', []):
            node = record['node']
            if node in scene.graph.nodes_geometry:
                _, geometry = scene.graph[node]
                scene.delete_geometry(geometry)
                scene.graph.transforms.remove_node(node)
    if FLOOR_NODE in scene.graph.nodes:
        raise ValueError("Unversioned background floor already exists")
    original_hash = existing.get('original_scene_sha256') or sha(run / "scene.glb")
    orientation = None
    if meta.get('pointmap'):
        info = meta['pointmap']
        path = run/info['asset']
        if info.get('frame') != 'sam3d_pytorch3d_camera' or sha(path) != info['sha256']:
            raise ValueError('Pointmap frame or hash mismatch')
        from .scene_orientation import estimate_up
        from PIL import Image
        image = (np.asarray(Image.open(run/meta['input_image']).convert('RGB'))
                 if meta.get('input_image') else None)
        with np.load(path, allow_pickle=False) as archive:
            points = archive['points']
            orientation = estimate_up(points, image)
        if existing.get('version') in (6, 7, 8):
            from .mask_geometry import refine_selected
            from PIL import Image
            refine_selected(run, meta, points, np.asarray(Image.open(run/meta['input_image']).convert('RGB')))
            for obj in objects:
                if obj['status'] in ('duplicate', 'structural'):
                    remove_object_tree(scene, obj['id'])
            objects = [obj for obj in objects if obj['status'] == 'generated']
        from .scene_projection import route_inconsistent_context
        routed = route_inconsistent_context(run, scene, objects, points)
        meta['projection_context_review'] = dict(uses_object_names=False, routed_ids=routed)
        objects = [obj for obj in objects if obj['status'] == 'generated']
        from .scene_composite_review import review_reconstructed_composites
        composite_decisions = review_reconstructed_composites(run, scene, objects, points)
        meta['reconstructed_composite_review'] = dict(uses_object_names=False, decisions=composite_decisions)
        objects = [obj for obj in objects if obj['status'] == 'generated']
    placement = correct_placement(scene, objects, orientation)
    align_objects(scene, objects, placement)
    from .scene_structure import restore_structure
    structure = (restore_structure(run, scene, meta, placement,
        proposal_method='reference_stable_normals',occlusion_method='guarded_enclosed_plane_evidence') if supported_repair
        else restore_structure(run, scene, meta, placement))
    if meta.get('pointmap'):
        from .scene_pose_refinement import refine_poses
        placement['pose_refinement']=refine_poses(run,scene,objects,points,placement,structure,strict_source=supported_repair)
    from .scene_contacts import improve_contacts
    source_guard = None
    if meta.get('pointmap'):
        from .scene_source_guard import contact_source_guard
        source_guard = contact_source_guard(run,scene,meta,placement,points)
    improve_contacts(scene, objects, placement, structure=structure,source_guard=source_guard)
    if supported_repair and meta.get('pointmap'):
        from .scene_supported_refinement import refine_supported_poses
        placement['supported_refinement']=refine_supported_poses(run,scene,objects,points,placement,structure)
    if overlap_repair and meta.get('pointmap'):
        from .scene_overlap_refinement import refine_overlaps
        placement['overlap_refinement'] = refine_overlaps(run, scene, objects, points, placement, structure,
                                                        strict_source=supported_repair)
    meta['structure'] = structure
    meta['background'] = structure['surfaces']
    groups = group_export_nodes(scene, objects, structure['surfaces'])
    scene.export(run / "scene.glb")
    reloaded = trimesh.load(run / "scene.glb", force="scene", process=False)
    for obj in objects:
        if not np.allclose(reloaded.graph[obj["id"]][0], obj["transform"]["matrix"], atol=1e-6):
            raise ValueError(f"Placement transform changed in GLB: {obj['id']}")
        if not np.allclose(bounds_of(object_vertices(reloaded, obj["id"])), obj["placement"]["world_bounds_after"], atol=1e-6):
            raise ValueError(f"Placement bounds changed in GLB: {obj['id']}")
    meta.setdefault("assembly", {}).update(bounds=reloaded.bounds.tolist(), geometry_nodes=len(reloaded.graph.nodes_geometry), groups=groups)
    meta["assembly"]["method"] = "official SAM3D assembly, shared alignment, observed structural surfaces and label-free bounded contacts"
    placement.update(version=PLACEMENT_VERSION, original_scene_sha256=original_hash,
                     scene_sha256=sha(run / "scene.glb"), implementation_sha256=sha(Path(__file__)))
    if existing:
        placement['upgraded_from_version'] = existing['version']
    meta["placement"] = placement
    meta["pipeline"].update(placement_method="official SAM3D + shared alignment + label-free geometry contacts", structural_geometry=bool(structure["surfaces"]))
    meta["preview_method"] = "CPU mesh preview of final scene.glb; Gaussian previews retain original SAM3D pose and contain no floor"
    write(run / "scene_metadata.json", meta)
    if render:
        subprocess.run([sys.executable, "-m", "mapmaker.scene_preview", str(run / "scene.glb"),
                        "--out", str(run / "previews/meshes"), "--material"], check=True)
    write(run / "logs/placement.json", placement)
    return placement
