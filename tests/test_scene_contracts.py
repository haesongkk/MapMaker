"""CPU contracts; official SAM3D transforms are also checked during GPU assembly."""

import io
import sys
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest
import trimesh

from mapmaker.scene_pipeline import create_run
from mapmaker.scene_run import read


def test_input_exif_orientation_and_rgb(tmp_path):
    image = Image.new("RGB", (12, 8), "red")
    exif = image.getexif()
    exif[274] = 6
    data = io.BytesIO()
    image.save(data, "JPEG", exif=exif)
    run = create_run(data.getvalue(), tmp_path / "run")
    normalized = Image.open(run / "input/source_image.png")
    assert normalized.mode == "RGB" and normalized.size == (8, 12)
    assert read(run / "scene_metadata.json")["input_size"] == [8, 12]
    assert read(run / "status.json")["stage"] == "queued"


@pytest.mark.parametrize("bad", [False, True])
def test_assembly_independent_nodes_and_official_point_check(tmp_path, monkeypatch, bad):
    from mapmaker import scene_assembly as assembly

    class Tensor(np.ndarray):
        def numpy(self):
            return np.asarray(self)

    def tensor(value, **kwargs):
        return np.asarray(value, dtype=np.float32).view(Tensor)

    # Dependency double supplies native row-vector composition; the assertion
    # below independently checks known transformed vertices in GLB coordinates.
    def compose_transform(scale, rotation, translation):
        matrix = np.eye(4, dtype=np.float32)
        matrix[:3, :3] = np.diag(scale.ravel()) @ rotation[0].T
        matrix[3, :3] = translation[0]
        return SimpleNamespace(get_matrix=lambda: tensor(matrix[None]))

    def pointcloud(points, rotation, translation, scale):
        result = points[0] * scale[0] + translation[0] + (1 if bad else 0)
        return SimpleNamespace(points_list=lambda: [tensor(result)])

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(tensor=tensor, float32=np.float32))
    monkeypatch.setitem(sys.modules, "pytorch3d.transforms", SimpleNamespace(
        quaternion_to_matrix=lambda q: tensor(np.eye(3)[None])))
    monkeypatch.setitem(sys.modules, "sam3d_objects.data.dataset.tdfy.transforms_3d",
                        SimpleNamespace(compose_transform=compose_transform))
    monkeypatch.setitem(sys.modules, "sam3d_objects.utils.visualization",
                        SimpleNamespace(SceneVisualizer=SimpleNamespace(object_pointcloud=pointcloud)))
    mesh = trimesh.creation.box()
    mesh.export(tmp_path / "object.glb")
    objects = [{"id": oid, "asset": "object.glb", "pose": {
        "rotation": [[1, 0, 0, 0]], "translation": [[x, 2, 3]], "scale": [[2, 3, 4]],
    }} for oid, x in [("chair_00", 1), ("chair_01", 5)]]
    if bad:
        with pytest.raises(ValueError, match="Official pose/GLB mismatch"):
            assembly.assemble(tmp_path, objects)
        return
    result = assembly.assemble(tmp_path, objects)
    scene = trimesh.load(tmp_path / "scene.glb", force="scene", process=False)
    assert result["independent_object_nodes"] == ["chair_00", "chair_01"]
    assert len(scene.graph.nodes_geometry) == 2
    for obj in objects:
        matrix = scene.graph[obj["id"]][0]
        point = trimesh.transform_points([[1, 2, 3]], matrix)[0]
        assert np.allclose(point, [2 + obj["pose"]["translation"][0][0], -7, 11])
        assert scene.graph.transforms.parents[obj["id"] + "__0"] == obj["id"]
