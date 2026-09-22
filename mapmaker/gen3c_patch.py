"""Install MapMaker's side-arc trajectory and exact pose export in a local GEN3C checkout."""
from pathlib import Path


def patch(repo: Path) -> None:
    root = repo / 'cosmos_predict1/diffusion/inference'
    camera = root / 'camera_utils.py'
    source = camera.read_text()
    if 'def create_side_arc_trajectory(' not in source:
        marker = 'def generate_camera_trajectory('
        addition = '''def create_side_arc_trajectory(initial_w2c, center_depth, num_frames, angle_deg, radius, side, device):
    """Move from the input view along one circular arc, facing its center."""
    if not 0 < angle_deg <= 90 or radius <= 0:
        raise ValueError("side arc needs 0 < angle <= 90 and radius > 0")
    target = torch.tensor([0.0, 0.0, center_depth * radius], device=device)
    poses = []
    for i in range(num_frames):
        theta = math.radians(angle_deg) * i / (num_frames - 1)
        sign = -1 if side == "left" else 1
        pos = torch.tensor([sign * radius * center_depth * math.sin(theta), 0.0,
                            radius * center_depth * (1.0 - math.cos(theta))], device=device)
        view = look_at_matrix(pos, target)
        view[:3, 3] = -(view[:3, :3] @ pos)
        poses.append(view)
    return apply_transformation(torch.stack(poses), initial_w2c)


'''
        source = source.replace(marker, addition + marker, 1)
        source = source.replace('    center_depth: float = 1.0,', '    center_depth: float = 1.0,\n    side_angle_deg: float = 90.0,', 1)
        source = source.replace('    if trajectory_type in ["clockwise", "counterclockwise"]:', '''    if trajectory_type in ["side_left", "side_right"]:
        new_w2cs_seq = create_side_arc_trajectory(initial_w2c, center_depth, num_frames,
            side_angle_deg, movement_distance, trajectory_type.removeprefix("side_"), device)
    elif trajectory_type in ["clockwise", "counterclockwise"]:''', 1)
        camera.write_text(source)
    elif 'view[:3, 3] = -(view[:3, :3] @ pos)' not in source:
        source = source.replace('        poses.append(look_at_matrix(pos, target))',
            '        view = look_at_matrix(pos, target)\n        view[:3, 3] = -(view[:3, :3] @ pos)\n        poses.append(view)', 1)
        camera.write_text(source)
    script = root / 'gen3c_single_image.py'
    source = script.read_text()
    if '"side_left"' not in source:
        source = source.replace('            "left",', '            "side_left",\n            "side_right",\n            "left",', 1)
    if '--side_angle_deg' not in source:
        source = source.replace('    parser.add_argument(\n        "--movement_distance",', '    parser.add_argument("--side_angle_deg", type=float, default=90.0)\n    parser.add_argument(\n        "--movement_distance",', 1)
        source = source.replace('                movement_distance=args.movement_distance,', '                movement_distance=args.movement_distance,\n                side_angle_deg=args.side_angle_deg,', 1)
    if '--camera_poses_output' not in source:
        source = source.replace('    parser.add_argument(\n        "--movement_distance",', '    parser.add_argument("--camera_poses_output", type=str, default=None)\n    parser.add_argument(\n        "--movement_distance",', 1)
        source = source.replace('        except (ValueError, NotImplementedError) as e:', '''            if args.camera_poses_output:
                import numpy as np
                np.save(args.camera_poses_output, generated_w2cs[0].detach().cpu().numpy())
        except (ValueError, NotImplementedError) as e:''', 1)
    script.write_text(source)
    if not all(token in camera.read_text() for token in ("def create_side_arc_trajectory(", "side_angle_deg: float = 90.0", "create_side_arc_trajectory(initial_w2c")):
        raise RuntimeError("GEN3C camera trajectory patch did not apply cleanly")
    if not all(token in source for token in ("side_left", "--side_angle_deg", "--camera_poses_output", "generated_w2cs[0].detach().cpu().numpy()")):
        raise RuntimeError("GEN3C pose export patch did not apply cleanly")
