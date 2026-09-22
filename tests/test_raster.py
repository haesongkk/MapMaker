import numpy as np
import trimesh
from mapmaker.raster import rasterize, render_scene
from mapmaker.reconstruction import complete_background, surface_mesh


def test_intersecting_triangles_have_pixel_depth_not_average_depth():
    k = np.array([[20.0, 0, 16], [0, 20.0, 16], [0, 0, 1]])
    xy = np.array([[3, 3], [29, 3], [16, 29]])
    z1 = np.array([1.0, 4.0, 2.0])
    z2 = np.array([4.0, 1.0, 2.0])

    def vertices(z):
        return np.c_[(xy[:, 0] - 16) * z / 20, (xy[:, 1] - 16) * z / 20, z]

    scene = trimesh.Scene()
    for name, z, color in [
        ("red", z1, [255, 0, 0, 255]),
        ("blue", z2, [0, 0, 255, 255]),
    ]:
        scene.add_geometry(
            trimesh.Trimesh(
                vertices(z),
                [[0, 1, 2]],
                vertex_colors=np.tile(color, (3, 1)),
                process=False,
            ),
            node_name=name,
        )
    canvas, depth, _, _ = render_scene(scene, k, 32, 32)
    assert canvas[6, 7, 0] > 250
    assert canvas[6, 25, 2] > 250
    # Analytic reciprocal depth at left pixel.
    bary = np.array(
        [1 - (7 - 3) / 26 - (6 - 3) / 52, (7 - 3) / 26 - (6 - 3) / 52, (6 - 3) / 26]
    )
    assert abs(depth[6, 7] - 1 / (bary / z1).sum()) < 1e-6


def test_near_plane_clipping_and_order_independence():
    k = np.array([[20.0, 0, 16], [0, 20.0, 16], [0, 0, 1]])
    verts = np.array([[-0.03, -0.03, 0.01], [0.2, -0.2, 1], [0, 0.2, 1]])
    canvas = np.zeros((32, 32, 3), np.uint8)
    depth = np.full((32, 32), np.inf)
    owner = np.full((32, 32), -1, np.int32)
    rasterize(
        verts,
        np.array([[0, 1, 2]]),
        np.full((3, 3), 200.0),
        np.zeros((1, 1, 3)),
        k,
        canvas,
        depth,
        owner,
        0,
    )
    assert np.isfinite(depth).sum() > 10
    assert depth.min() >= 0.05


def test_background_completion_fills_exclusion_behind_foreground():
    depth = np.full((48, 64), 4.0, np.float32)
    depth[12:36, 16:48] = 2
    mask = depth < 3
    valid = np.ones_like(mask)
    rgb = np.full((48, 64, 3), 100, np.uint8)
    rgb[mask] = [255, 0, 0]
    color, completed = complete_background(rgb, depth, valid, mask)
    assert np.all(completed[mask] > depth[mask])
    assert color[24, 32, 0] < 180  # Removed object color is not used as the fill.
    k = np.array([[40.0, 0, 32], [0, 40.0, 24], [0, 0, 1]])
    mesh = surface_mesh(color, completed, k, discontinuity=np.inf)
    _, z, _, _ = render_scene(trimesh.Scene(mesh), k, 64, 48)
    assert np.isfinite(z).all()


def test_perspective_correct_texture_interpolation():
    k = np.array([[10.0, 0, 0], [0, 10.0, 0], [0, 0, 1]])
    verts = np.array([[0.0, 0, 1], [4.0, 0, 4], [0, 2.0, 2]])
    uv = np.array([[0.0, 1], [1.0, 1], [0.0, 0]])
    tex = np.zeros((101, 101, 3))
    tex[:, :, 0] = np.arange(101)[None, :] * 2
    canvas = np.zeros((12, 12, 3), np.uint8)
    depth = np.full((12, 12), np.inf)
    owners = np.full((12, 12), -1, np.int32)
    rasterize(verts, np.array([[0, 1, 2]]), uv, tex, k, canvas, depth, owners, 0)
    expected = (0.2 / 4) / (0.6 / 1 + 0.2 / 4 + 0.2 / 2) * 200
    assert abs(int(canvas[2, 2, 0]) - expected) < 1.1


def test_glb_renders_without_source_image_or_analysis(tmp_path):
    from mapmaker.standalone_render import render_glb
    from PIL import Image

    camera = {"width": 32, "height": 32, "K": [[20, 0, 16], [0, 20, 16], [0, 0, 1]]}
    mesh = trimesh.creation.box()
    scene = trimesh.Scene()
    transform = np.eye(4)
    transform[2, 3] = -2
    scene.add_geometry(mesh, transform=transform)
    scene.metadata["source_camera"] = camera
    scene.export(tmp_path / "scene.glb")
    path = render_glb(tmp_path, scale=1)
    assert Image.open(path).size == (32, 32)
    assert np.isfinite(np.load(tmp_path / "scene_glb_source_depth.npy")).any()
    assert not (tmp_path / "input.png").exists()


def test_uv_seams_are_not_physical_mesh_fragments():
    from mapmaker.reconstruction import mesh_health

    box = trimesh.creation.box()
    # Each triangle receives independent texture seam vertices, as GLB commonly does.
    vertices = box.vertices[box.faces].reshape(-1, 3)
    seam_mesh = trimesh.Trimesh(
        vertices, np.arange(len(vertices)).reshape(-1, 3), process=False
    )
    assert mesh_health(seam_mesh)["usable"]
    broken = trimesh.util.concatenate([box, box.copy().apply_translation([5, 0, 0])])
    assert not mesh_health(broken)["usable"]


def test_pose_fit_corrects_y_up_and_source_mask_alignment():
    from mapmaker.geometry import optimize_transform, initial_transform
    from mapmaker.common import image_to_points

    # Asymmetric seat/back silhouette: a flipped Y axis is visibly wrong.
    seat = trimesh.creation.box(extents=[1.6, 0.25, 0.7])
    back = trimesh.creation.box(extents=[1.6, 0.8, 0.18])
    back.apply_translation([0, 0.5, -0.26])
    mesh = trimesh.util.concatenate([seat, back])
    k = np.array([[75.0, 0, 48], [0, 75.0, 40], [0, 0, 1]])
    truth = np.diag([1.0, -1.0, -1.0, 1.0])
    truth[:3, 3] = [0.1, 0.25, 3.0]
    reference = trimesh.Scene()
    reference.add_geometry(mesh, transform=truth)
    _, z, owners, _ = render_scene(reference, k, 96, 80)
    mask = owners >= 0
    points = image_to_points(z, k)
    initial = initial_transform(mesh, points, mask)
    before = trimesh.Scene()
    before.add_geometry(mesh, transform=initial)
    _, _, before_owner, _ = render_scene(before, k, 96, 80)
    before_mask = before_owner >= 0
    before_iou = (before_mask & mask).sum() / (before_mask | mask).sum()
    matrix, iou, residual = optimize_transform(mesh, points, mask, k)
    assert iou > 0.85
    assert iou > before_iou + 0.05
    assert residual < 0.1
    assert matrix[1, 1] < 0


def test_pose_fit_keeps_complete_shape_behind_an_occluder():
    from mapmaker.geometry import optimize_transform
    from mapmaker.common import image_to_points

    mesh = trimesh.creation.box(extents=[1.6, 1.6, 0.3])
    k = np.array([[75.0, 0, 48], [0, 75.0, 40], [0, 0, 1]])
    transform = np.diag([1.0, -1.0, -1.0, 1.0])
    transform[2, 3] = 3.0
    scene = trimesh.Scene()
    scene.add_geometry(mesh, transform=transform)
    _, depth, owners, _ = render_scene(scene, k, 96, 80)
    full = owners >= 0
    y, x = np.where(full)
    hole = np.zeros_like(full)
    hole[y.min() + 10 : y.max() - 9, x.min() + 10 : x.max() - 9] = True
    visible = full & ~hole
    depth[hole] = 1.5  # Independent foreground object, not a hole in the box.
    matrix, score, _ = optimize_transform(mesh, image_to_points(depth, k), visible, k)
    fitted = trimesh.Scene()
    fitted.add_geometry(mesh, transform=matrix)
    _, _, owner, _ = render_scene(fitted, k, 96, 80)
    assert score > 0.85
    assert ((owner >= 0) & hole).sum() > 0.9 * hole.sum()


def test_thin_observed_masks_keep_every_pixel():
    from mapmaker.reconstruction import masked_surface_mesh

    rgb = np.full((24, 32, 3), 100, np.uint8)
    depth = np.full((24, 32), 2.0)
    mask = np.zeros((24, 32), bool)
    mask[2:22, 7] = True
    mask[8, 12:28] = True
    k = np.array([[25.0, 0, 16], [0, 25.0, 12], [0, 0, 1]])
    mesh = masked_surface_mesh(rgb, depth, k, mask)
    _, _, owners, _ = render_scene(trimesh.Scene(mesh), k, 32, 24)
    assert np.array_equal(owners >= 0, mask)


def test_source_baking_preserves_geometry_and_unseen_texture():
    from mapmaker.reconstruction import bake_visible_source
    from PIL import Image

    mesh = trimesh.creation.box()
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.zeros((len(mesh.vertices), 2)),
        material=trimesh.visual.material.PBRMaterial(
            baseColorTexture=Image.new("RGB", (8, 8), (10, 10, 200))
        ),
    )
    matrix = np.eye(4)
    matrix[2, 3] = 2.0
    k = np.array([[25.0, 0, 16], [0, 25.0, 16], [0, 0, 1]])
    rgb = np.full((32, 32, 3), [200, 10, 10], np.uint8)
    baked, report = bake_visible_source(mesh, matrix, rgb, np.ones((32, 32), bool), k)
    assert np.allclose(baked.vertices[baked.faces], mesh.vertices[mesh.faces])
    assert 0 < report["source_baked_face_fraction"] < 1
    scene = trimesh.Scene()
    scene.add_geometry(baked, transform=matrix)
    front, _, _, _ = render_scene(scene, k, 32, 32)
    back_view = np.diag([-1.0, 1.0, -1.0, 1.0])
    back_view[2, 3] = 4
    back, _, _, _ = render_scene(scene, k, 32, 32, back_view)
    assert front[16, 16, 0] > 190 and front[16, 16, 2] < 20
    assert back[16, 16, 2] > 190 and back[16, 16, 0] < 20


def test_background_margin_preserves_a_perspective_plane():
    from mapmaker.reconstruction import extend_background

    y, x = np.mgrid[:30, :40]
    depth = 1 / (0.3 + 0.002 * x + 0.004 * y)
    rgb = np.zeros((30, 40, 3), np.uint8)
    k = np.array([[30.0, 0, 20], [0, 30.0, 15], [0, 0, 1]])
    _, padded, shifted = extend_background(rgb, depth, k, 5)
    yy, xx = np.mgrid[-5:35, -5:45]
    assert np.allclose(padded, 1 / (0.3 + 0.002 * xx + 0.004 * yy))
    assert shifted[0, 2] == 25 and shifted[1, 2] == 20


def test_nested_structure_masks_merge_without_merging_disjoint_instances():
    from mapmaker.reconstruction import attached_parts

    big = np.zeros((20, 20), bool)
    big[2:18, 2:18] = True
    inner = np.zeros_like(big)
    inner[5:12, 5:12] = True
    separate = np.zeros_like(big)
    separate[:2, :2] = True
    objects = [
        {"id": "cabinet", "label": "cabinet", "confidence": 0.9},
        {"id": "part", "label": "cabinet", "confidence": 0.7},
        {"id": "other", "label": "cabinet", "confidence": 0.8},
    ]
    assert attached_parts(
        objects, {"cabinet": big, "part": inner, "other": separate}
    ) == {"part": "cabinet"}
