import argparse
import json
import math
import os
import time
import threading
import traceback
from pathlib import Path
from glob import glob

import numpy as np
import torch
import torch.nn.functional as F
import viser
from gsplat.rendering import rasterization
from gs.utils import depth_to_normal
from plyfile import PlyData
from tqdm import tqdm

import nerfview
from nerfview import apply_float_colormap


OUTPUT_VARIANTS = {
    "학습 원본 · PT": "ckpts/ckpt_7999_rank0.pt",
    "Gaussian · PLY": "ply/point_cloud_7999.ply",
    "압축 Gaussian · SPZ": "ply/point_cloud_7999.spz",
    "후처리 메시": "ply/fuse_post.ply",
    "단순화 메시": "ply/fuse_simplified.ply",
}


def read_metadata(checkpoint):
    path = Path(checkpoint).parent / "position_meta_info.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    return {key: np.asarray(data[key]) if data.get(key) is not None else None
            for key in ("up_direction", "facing_direction", "center_point")}


def load_output(checkpoint, args, device):
    if Path(checkpoint).name in {"fuse_post.ply", "fuse_simplified.ply"}:
        import trimesh

        mesh = trimesh.load(checkpoint, force="mesh", process=False)
        if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
            raise ValueError("Mesh has no triangles")

        def double_sided(tree):
            for material in tree.get("materials", []):
                material["doubleSided"] = True

        glb = trimesh.exchange.gltf.export_glb(mesh, tree_postprocessor=double_sided)
        return dict(read_metadata(checkpoint), kind="mesh", glb=glb,
                    count=len(mesh.faces), source=checkpoint)
    result = load_scene(checkpoint, args, device)
    result.update(kind="gaussian", count=len(result["means"]), source=checkpoint)
    return result


def load_scene(checkpoint, args, device):
    up_direction = None
    facing_direction = None
    center_point = None

    if "rank*" in checkpoint or checkpoint.endswith(".pt"):
        ckpt_paths = sorted(glob(checkpoint)) if "rank*" in checkpoint else [checkpoint]
        if not ckpt_paths:
            raise FileNotFoundError(f"No checkpoints matched: {checkpoint}")

        splat_chunks = {"means": [], "quats": [], "scales": [], "opacities": [], "sh0": [], "shN": []}
        for ckpt_path in tqdm(ckpt_paths, desc="Loading checkpoints..."):
            ckpt_all = torch.load(ckpt_path, map_location=device, weights_only=False)
            up_direction = ckpt_all.get("up_direction", up_direction)
            facing_direction = ckpt_all.get("facing_direction", facing_direction)
            center_point = ckpt_all.get("center_point", center_point)

            ckpt = ckpt_all["splats"]
            splat_chunks["means"].append(ckpt["means"])
            splat_chunks["quats"].append(F.normalize(ckpt["quats"], p=2, dim=-1))
            splat_chunks["scales"].append(torch.exp(ckpt["scales"]))
            splat_chunks["opacities"].append(torch.sigmoid(ckpt["opacities"]))
            splat_chunks["sh0"].append(ckpt["sh0"])
            splat_chunks["shN"].append(ckpt["shN"])

        means = torch.cat(splat_chunks["means"], dim=0)
        quats = torch.cat(splat_chunks["quats"], dim=0)
        scales = torch.cat(splat_chunks["scales"], dim=0)
        opacities = torch.cat(splat_chunks["opacities"], dim=0)
        sh0 = torch.cat(splat_chunks["sh0"], dim=0)
        shN = torch.cat(splat_chunks["shN"], dim=0)
    elif checkpoint.endswith(".spz"):
        import spz

        options = spz.UnpackOptions()
        # Matches this repository's PLY -> SPZ export convention (verified
        # against PLY positions); RDF would flip the Y and Z axes here.
        options.to_coord = spz.CoordinateSystem.RUB
        cloud = spz.load_spz(checkpoint, options)
        n_points = cloud.num_points
        if n_points <= 0:
            raise ValueError(f"No Gaussians decoded from {checkpoint}")
        metadata = read_metadata(checkpoint)
        up_direction, facing_direction, center_point = (
            metadata[key] for key in ("up_direction", "facing_direction", "center_point")
        )
        means = torch.as_tensor(cloud.positions.reshape(n_points, 3), device=device)
        quats = torch.as_tensor(cloud.rotations.reshape(n_points, 4)[:, [3, 0, 1, 2]].copy(), device=device)
        quats = F.normalize(quats, p=2, dim=-1)
        scales = torch.as_tensor(cloud.scales.reshape(n_points, 3), device=device).exp()
        opacities = torch.as_tensor(cloud.alphas, device=device).sigmoid()
        sh0 = torch.as_tensor(cloud.colors.reshape(n_points, 1, 3), device=device)
        shN = torch.as_tensor(cloud.sh.reshape(n_points, (cloud.sh_degree + 1) ** 2 - 1, 3), device=device)
    elif checkpoint.endswith(".ply"):
        with open(os.path.join(os.path.dirname(checkpoint), "position_meta_info.json"), "r") as f:
            meta_info = json.load(f)
        up_direction = np.array(meta_info["up_direction"])
        facing_direction = np.array(meta_info["facing_direction"])
        center_point = np.array(meta_info["center_point"])

        print(f"[load_ply] Reading {checkpoint} ...")
        plydata = PlyData.read(checkpoint)
        vertex = plydata['vertex']
        n_points = len(vertex.data)
        print(f"[load_ply] Number of points: {n_points}")

        # 1. Positions: means (N, 3).
        means = torch.tensor(np.stack([vertex['x'], vertex['y'], vertex['z']], axis=-1), dtype=torch.float32, device=device)

        # 2. Quaternions: quats (N, 4), stored in PLY as rot_0~rot_3 (wxyz).
        quats = torch.tensor(np.stack([vertex['rot_0'], vertex['rot_1'], vertex['rot_2'], vertex['rot_3']], axis=-1), dtype=torch.float32, device=device)
        quats = F.normalize(quats, p=2, dim=-1)

        # 3. Scales: scales (N, 3), stored in log space.
        scales = torch.tensor(np.stack([vertex['scale_0'], vertex['scale_1'], vertex['scale_2']], axis=-1), dtype=torch.float32, device=device)
        scales = torch.exp(scales)

        # 4. Opacities: opacities (N,), stored as logits before sigmoid.
        opacities = torch.tensor(np.array(vertex['opacity']), dtype=torch.float32, device=device)
        opacities = torch.sigmoid(opacities)

        # 5. SH coefficients: DC (sh0) + remaining bands (shN).
        # sh0: f_dc_0, f_dc_1, f_dc_2 -> (N, 1, 3).
        sh_dc = torch.tensor(np.stack([
            vertex['f_dc_0'], vertex['f_dc_1'], vertex['f_dc_2']
        ], axis=-1), dtype=torch.float32, device=device)  # (N, 3)
        sh0 = sh_dc.unsqueeze(1)  # (N, 1, 3)

        # shN: f_rest_* -> (N, C, 3).
        rest_names = sorted(
            [p.name for p in vertex.properties if p.name.startswith('f_rest_')],
            key=lambda x: int(x.split('_')[-1])
        )

        if rest_names:
            sh_rest_flat = torch.tensor(np.stack(
                [vertex[name] for name in rest_names], axis=-1
            ), dtype=torch.float32, device=device)  # (N, num_rest)

            # Standard 3DGS stores f_rest flattened as (C * 3); reshape to (N, C, 3).
            num_rest_coeffs = len(rest_names)
            assert num_rest_coeffs % 3 == 0, \
                f"Invalid PLY: f_rest count {num_rest_coeffs} is not divisible by 3."
            num_sh_rest = num_rest_coeffs // 3
            shN = sh_rest_flat.reshape(n_points, 3, num_sh_rest).transpose(1, 2).contiguous()  # (N, C, 3)
        else:
            shN = torch.zeros(n_points, 0, 3, dtype=torch.float32, device=device)
    else:
        raise NotImplementedError(f"Unsupported checkpoint format: {checkpoint}")

    colors = torch.cat([sh0, shN], dim=-2)
    if args.none_sh_degree:
        sh_degree = None
    else:
        sh_degree = int(math.sqrt(colors.shape[-2]) - 1)

    # repeat the scene into a grid (to mimic a large-scale setting)
    repeats = args.scene_grid
    gridx, gridy = torch.meshgrid(
        [
            torch.arange(-(repeats // 2), repeats // 2 + 1, device=device),
            torch.arange(-(repeats // 2), repeats // 2 + 1, device=device),
        ],
        indexing="ij",
    )

    grid = torch.stack([gridx, gridy, torch.zeros_like(gridx)], dim=-1).reshape(-1, 3)
    means = means[None, :, :] + grid[:, None, :]
    means = means.reshape(-1, 3)
    quats = quats.repeat(repeats ** 2, 1)
    scales = scales.repeat(repeats ** 2, 1)
    colors = colors.repeat(repeats ** 2, 1, 1)
    if sh_degree is None:
        colors = colors[:, 0]
    opacities = opacities.repeat(repeats ** 2)
    print("Number of Gaussians:", len(means))

    return {name: value for name, value in locals().items() if name in (
        "means", "quats", "scales", "opacities", "colors", "sh_degree",
        "up_direction", "facing_direction", "center_point",
    )}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene_grid", type=int, default=1, help="repeat the scene into a grid of NxN")
    parser.add_argument("--gpu_id", type=int, default=0)
    parser.add_argument("--none_sh_degree", action='store_true')
    parser.add_argument("--ckpt", type=str, default=None, help="path to the .pt file")
    parser.add_argument("--scene_root", type=Path, default=None, help="directory containing scene/gs/ckpts checkpoints")
    parser.add_argument("--port", type=int, default=443, help="port for the viewer server")
    parser.add_argument("--backend", type=str, default="gsplat", choices=["gsplat", "gsplat_legacy", "inria"])
    args = parser.parse_args()
    assert args.scene_grid % 2 == 1, "scene_grid must be odd"
    if args.ckpt is None:
        raise ValueError("--ckpt is required")

    os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu_id)

    torch.manual_seed(42)
    device = "cuda"
    scene_lock = threading.RLock()
    scene = load_output(args.ckpt, args, device)

    render_state = {"mode": "RGB"}

    if args.backend == "gsplat":
        rasterization_fn = rasterization
    elif args.backend == "gsplat_legacy":
        from gsplat import rasterization_legacy_wrapper
        rasterization_fn = rasterization_legacy_wrapper
    elif args.backend == "inria":
        from gsplat import rasterization_inria_wrapper
        rasterization_fn = rasterization_inria_wrapper
    else:
        raise ValueError(f"Unknown backend: {args.backend}")


    # register and open viewer
    @torch.no_grad()
    def viewer_render_fn(
            camera_state: nerfview.CameraState, render_tab_state: nerfview.RenderTabState
    ):
        if render_tab_state.preview_render:
            width = render_tab_state.render_width
            height = render_tab_state.render_height
        else:
            width = render_tab_state.viewer_width
            height = render_tab_state.viewer_height
        if scene["kind"] == "mesh":
            return np.zeros((height, width, 3), dtype=np.float32)
        c2w = camera_state.c2w
        K = camera_state.get_K([width, height])
        c2w = torch.from_numpy(c2w).float().to(device)
        K = torch.from_numpy(K).float().to(device)
        viewmat = c2w.inverse()

        current_mode = render_state["mode"]
        if current_mode not in {"RGB", "Depth", "Normal"}:
            raise ValueError(f"Unknown render mode: {current_mode}")

        raster_kwargs = {
            "sh_degree": scene["sh_degree"],
            "render_mode": "RGB" if current_mode == "RGB" else "ED",
            "radius_clip": 3,
        }
        if current_mode == "RGB":
            raster_kwargs["backgrounds"] = torch.zeros((3,), device=device)

        render_colors, _, _ = rasterization_fn(
            scene["means"], scene["quats"], scene["scales"], scene["opacities"], scene["colors"],
            viewmat[None], K[None], width, height, **raster_kwargs
        )

        if current_mode == "RGB":
            render_rgbs = render_colors[0, ..., 0:3].cpu().numpy()
        elif current_mode == "Depth":
            depth = render_colors[0, ..., 0:1]  # (H, W, 1)
            near_plane = depth.min()
            far_plane = depth.max()
            depth_normalized = (depth - near_plane) / (far_plane - near_plane + 1e-10)
            depth_normalized = torch.clamp(depth_normalized, 0, 1)
            render_rgbs = apply_float_colormap(depth_normalized, "turbo").cpu().numpy()
        else:
            depth = render_colors[0, ..., 0]  # (H, W)
            normal_vis = depth_to_normal(depth, K)  # (H, W, 3)
            render_rgbs = normal_vis.cpu().numpy()

        return render_rgbs


    # Set up the Viser server.
    server = viser.ViserServer(port=args.port, verbose=False)

    def reset_cameras():
        up = scene["up_direction"]
        facing = scene["facing_direction"]
        center = scene["center_point"]
        up = up if up is not None else (-1, 0, 0)
        look_at = facing if facing is not None else (0.0, 0.0, -1.0)
        position = center if center is not None else (0, 0, 0)
        server.scene.set_up_direction(up)
        server.initial_camera.up = up
        server.initial_camera.look_at = look_at
        server.initial_camera.position = position
        server.initial_camera.fov = np.deg2rad(70)
        for client in server.get_clients().values():
            with client.atomic():
                client.camera.up_direction = up
                client.camera.position = position
                client.camera.look_at = look_at
                client.camera.fov = np.deg2rad(70)

    reset_cameras()
    scene_paths = {}
    if args.scene_root is not None:
        scene_paths = {
            path.parents[2].name: str(path)
            for path in sorted(args.scene_root.glob("*/gs/ckpts/ckpt_7999_rank0.pt"))
        }
    current_name = next(
        (name for name, path in scene_paths.items() if Path(path).resolve() == Path(args.ckpt).resolve()),
        Path(args.ckpt).stem,
    )
    scene_paths.setdefault(current_name, args.ckpt)
    def variant_paths(name):
        initial = Path(scene_paths[name])
        gs_root = initial.parent.parent
        paths = {label: str(gs_root / relative) for label, relative in OUTPUT_VARIANTS.items()
                 if (gs_root / relative).is_file()}
        if str(initial) not in paths.values():
            paths["지정 파일"] = str(initial)
        return paths

    current_variant = next(label for label, path in variant_paths(current_name).items()
                           if Path(path).resolve() == Path(args.ckpt).resolve())
    mesh_handle = None
    with server.gui.add_folder("장면 선택"):
        scene_dropdown = server.gui.add_dropdown(
            "장면", options=list(scene_paths), initial_value=current_name,
        )
        variant_dropdown = server.gui.add_dropdown(
            "출력 형식", options=list(variant_paths(current_name)), initial_value=current_variant,
        )
        scene_status = server.gui.add_text("상태", initial_value="준비 완료", disabled=True)
        output_info = server.gui.add_markdown("")

    def update_display():
        global mesh_handle
        new_handle = None
        if scene["kind"] == "mesh":
            new_handle = server.scene.add_glb(
                "/output_mesh", scene["glb"], cast_shadow=False, receive_shadow=False,
            )
        elif mesh_handle is not None:
            mesh_handle.remove()
        mesh_handle = new_handle
        render_mode_dropdown.disabled = scene["kind"] == "mesh"
        unit = "삼각형" if scene["kind"] == "mesh" else "Gaussian"
        note = "메시는 정점 색상으로 표시됩니다." if scene["kind"] == "mesh" else "RGB · Depth · Normal 모드를 사용할 수 있습니다."
        output_info.content = f"**{Path(scene['source']).name}** · {unit} {scene['count']:,}개\n\n{note}"
        scene_status.value = f"{current_name} · {current_variant} 준비 완료"

    @scene_dropdown.on_update
    @variant_dropdown.on_update
    def switch_scene(event):
        global scene, current_name, current_variant
        with scene_lock:
            selected = scene_dropdown.value
            paths = variant_paths(selected)
            requested = variant_dropdown.value
            variant = requested if requested in paths else next(iter(paths))
            if (selected, variant) == (current_name, current_variant):
                return
            scene_dropdown.disabled = True
            variant_dropdown.disabled = True
            scene_status.value = f"{selected} · {variant} 불러오는 중…"
            previous_scene, previous_name, previous_variant = scene, current_name, current_variant
            try:
                new_scene = load_output(paths[variant], args, device)
                torch.cuda.synchronize()
                scene = new_scene
                current_name, current_variant = selected, variant
                update_display()
                if selected != previous_name:
                    reset_cameras()
                variant_dropdown.options = list(paths)
                variant_dropdown.value = variant
                viewer.rerender(None)
            except Exception:
                traceback.print_exc()
                scene, current_name, current_variant = previous_scene, previous_name, previous_variant
                update_display()
                scene_dropdown.value = current_name
                variant_dropdown.options = list(variant_paths(current_name))
                variant_dropdown.value = current_variant
                scene_status.value = f"{selected} · {variant} 로딩 실패. 이전 결과를 유지합니다."
            finally:
                del previous_scene
                torch.cuda.empty_cache()
                scene_dropdown.disabled = False
                variant_dropdown.disabled = False

    # Add GUI controls.
    with server.gui.add_folder("Render Settings"):
        render_mode_dropdown = server.gui.add_dropdown(
            "Render Mode",
            options=["RGB", "Depth", "Normal"],
            initial_value="RGB",
        )


    @render_mode_dropdown.on_update
    def _(_) -> None:
        render_state["mode"] = render_mode_dropdown.value
        viewer.rerender(None)


    def locked_render(camera_state, render_tab_state):
        with scene_lock:
            return viewer_render_fn(camera_state, render_tab_state)

    viewer = nerfview.Viewer(
        server=server,
        render_fn=locked_render,
        mode="rendering",
    )

    update_display()
    print("Viewer running... Ctrl+C to exit.")
    print("Available render modes: RGB, Depth, Normal")
    time.sleep(100000)