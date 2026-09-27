"""GLB nodes using the exact official make_scene point transform convention."""

import numpy as np
import trimesh

# postprocessing_utils.py exports native row vertices with this matrix.
NATIVE_TO_GLB_ROW = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float)


def object_matrix(pose):
    import torch
    from pytorch3d.transforms import quaternion_to_matrix
    from sam3d_objects.data.dataset.tdfy.transforms_3d import compose_transform

    p = {
        k: torch.tensor(pose[k], dtype=torch.float32)
        for k in ("rotation", "translation", "scale")
    }
    native_row = (
        compose_transform(
            scale=p["scale"],
            rotation=quaternion_to_matrix(p["rotation"]),
            translation=p["translation"],
        )
        .get_matrix()[0]
        .numpy()
    )
    undo_export = np.eye(4)
    undo_export[:3, :3] = NATIVE_TO_GLB_ROW
    return native_row.T @ undo_export


def assemble(run, objects):
    import torch
    from sam3d_objects.utils.visualization import SceneVisualizer

    scene = trimesh.Scene(base_frame="Scene")
    checks = []
    for obj in objects:
        matrix = object_matrix(obj["pose"])
        oid = obj["id"]
        scene.graph.update(frame_from="Scene", frame_to=oid, matrix=matrix)
        asset = trimesh.load(run / obj["asset"], force="scene", process=False)
        max_error = 0.0
        for index, node in enumerate(asset.graph.nodes_geometry):
            child_tf, gname = asset.graph[node]
            geometry = asset.geometry[gname].copy()
            if not len(geometry.vertices) or not np.isfinite(geometry.vertices).all():
                raise ValueError(f"Invalid mesh: {oid}")
            scene.add_geometry(
                geometry,
                node_name=f"{oid}__{index}",
                geom_name=f"{oid}__geometry_{index}",
                parent_node_name=oid,
                transform=child_tf,
            )
            points = trimesh.transform_points(
                geometry.vertices[:: max(1, len(geometry.vertices) // 512)], child_tf
            )
            native = points @ NATIVE_TO_GLB_ROW.T
            expected = (
                SceneVisualizer.object_pointcloud(
                    torch.tensor(native[None], dtype=torch.float32),
                    torch.tensor(obj["pose"]["rotation"]),
                    torch.tensor(obj["pose"]["translation"]),
                    torch.tensor(obj["pose"]["scale"]),
                )
                .points_list()[0]
                .numpy()
            )
            actual = trimesh.transform_points(points, matrix)
            max_error = max(max_error, float(np.max(np.abs(actual - expected))))
        if max_error > 1e-5:
            raise ValueError(f"Official pose/GLB mismatch: {oid}: {max_error}")
        node_scale = np.linalg.norm(matrix[:3, :3], axis=0)
        rotation = np.eye(4)
        rotation[:3, :3] = matrix[:3, :3] / node_scale[None, :]
        obj["transform"] = {
            "position": matrix[:3, 3].tolist(),
            "rotation_quaternion_wxyz": trimesh.transformations.quaternion_from_matrix(
                rotation
            ).tolist(),
            "scale": node_scale.tolist(),
            "matrix": matrix.tolist(),
            "matrix_convention": "column vectors; native pose composed with inverse GLB export axis rotation",
        }
        checks.append({"object": oid, "official_point_transform_max_error": max_error})
    scene.export(run / "scene.glb")
    reloaded = trimesh.load(run / "scene.glb", force="scene", process=False)
    for obj in objects:
        if obj["id"] not in reloaded.graph.nodes:
            raise ValueError("Object node lost during export")
        if not np.allclose(
            reloaded.graph[obj["id"]][0], obj["transform"]["matrix"], atol=1e-6
        ):
            raise ValueError("Exported transform changed")
    return {
        "independent_object_nodes": [o["id"] for o in objects],
        "geometry_nodes": len(reloaded.graph.nodes_geometry),
        "bounds": reloaded.bounds.tolist(),
        "coordinate_validation": checks,
        "method": "official compose_transform used by make_scene; undo native-to-GLB vertex export rotation; no placement heuristic or scene normalization",
    }
