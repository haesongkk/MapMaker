from pathlib import Path

from mapmaker.gen3c_patch import patch


def test_gen3c_patch_installs_side_arc_and_exact_export(tmp_path: Path):
    root = tmp_path / 'cosmos_predict1/diffusion/inference'
    root.mkdir(parents=True)
    (root / 'camera_utils.py').write_text('''def generate_camera_trajectory(
    center_depth: float = 1.0,
):
    if trajectory_type in ["clockwise", "counterclockwise"]:
        pass
''')
    (root / 'gen3c_single_image.py').write_text('''    parser.add_argument(
        "--movement_distance",
    )
    choices = [
            "left",
    ]
                movement_distance=args.movement_distance,
        except (ValueError, NotImplementedError) as e:
            pass
''')
    patch(tmp_path)
    before = (root / 'camera_utils.py').read_text(), (root / 'gen3c_single_image.py').read_text()
    patch(tmp_path)
    assert before == ((root / 'camera_utils.py').read_text(), (root / 'gen3c_single_image.py').read_text())
    assert 'generated_w2cs[0].detach().cpu().numpy()' in before[1]
    assert 'center_depth * radius' in before[0]
    assert 'math.sin(theta)' in before[0]
    assert 'view[:3, 3] = -(view[:3, :3] @ pos)' in before[0]
