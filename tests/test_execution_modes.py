import io
from pathlib import Path
import numpy as np
import pytest
import trimesh
from PIL import Image
from mapmaker.scene_pipeline import create_run
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_export import finish_mode, objects_only


def new_run(tmp_path, number):
    data = io.BytesIO()
    Image.new('RGB', (8, 8)).save(data, format='PNG')
    return create_run(data.getvalue(), tmp_path / str(number), mode=number)


@pytest.mark.parametrize('number', [0, 5, True, '2'])
def test_invalid_mode_creates_no_output(tmp_path, number):
    with pytest.raises(ValueError):
        create_run(b'not an image', tmp_path / 'output', mode=number)
    assert not (tmp_path / 'output').exists()


@pytest.mark.parametrize('number', [1, 2])
def test_raw_modes_never_apply_correction(tmp_path, monkeypatch, number):
    run = new_run(tmp_path, number)
    (run / 'scene.glb').write_bytes(b'unchanged raw result')
    original = sha(run / 'scene.glb')
    def forbidden(*args, **kwargs):
        raise AssertionError('Raw inference must not run geometry correction')
    monkeypatch.setattr('mapmaker.scene_placement.finalize_scene', forbidden)
    finish_mode(run)
    assert sha(run / 'scene.glb') == original
    assert read(run / 'scene_metadata.json')['execution']['completed_mode'] == number


def test_objects_export_preserves_shared_mesh_and_transform(tmp_path):
    run = new_run(tmp_path, 4)
    scene = trimesh.Scene()
    matrix = trimesh.transformations.translation_matrix([2, 3, 4])
    scene.add_geometry(trimesh.creation.box(), geom_name='shared', node_name='object', transform=matrix)
    scene.graph.update(frame_to='wall', geometry='shared', matrix=np.eye(4))
    scene.export(run / 'scene.glb')
    before = sha(run / 'scene.glb')
    meta = read(run / 'scene_metadata.json')
    meta['structure'] = dict(surfaces=[dict(node='wall')])
    meta['objects'] = [dict(id='object', status='generated')]
    write(run / 'scene_metadata.json', meta)
    target = tmp_path / 'objects'
    objects_only(run, target)
    loaded = trimesh.load(target / 'scene.glb', force='scene', process=False)
    assert 'wall' not in loaded.graph.nodes_geometry
    assert 'object' in loaded.graph.nodes_geometry
    np.testing.assert_allclose(loaded.graph['object'][0], matrix)
    assert len(loaded.geometry[loaded.graph['object'][1]].faces) == 12
    assert sha(run / 'scene.glb') == before
    assert read(target / 'scene_metadata.json')['execution']['mode'] == 3


@pytest.mark.parametrize('number', [3, 4])
def test_corrected_modes_share_one_finalization(tmp_path, monkeypatch, number):
    run = new_run(tmp_path, number)
    calls = []
    monkeypatch.setattr('mapmaker.scene_placement.finalize_scene', lambda *a, **kw: calls.append(kw))
    exported = []
    monkeypatch.setattr('mapmaker.scene_export.objects_only', lambda *a: exported.append(a))
    finish_mode(run)
    assert calls == [dict(render=False, supported_repair=True, overlap_repair=True)]
    assert len(exported) == (number == 3)


def test_compare_reconstructs_only_twice_per_input(tmp_path, monkeypatch):
    from mapmaker import comparison
    image = tmp_path / 'image.png'
    Image.new('RGB', (8, 8)).save(image)
    calls = []
    class Pipeline:
        def run(self, run):
            calls.append(read(run/'scene_metadata.json')['execution']['mode'])
            (run/'scene.glb').write_bytes(b'raw')
        def close(self):pass
    def derive(source, four, three):
        assert read(Path(source)/'scene_metadata.json')['execution']['mode'] == 2
        for path in (four, three):
            path.mkdir();(path/'scene.glb').write_bytes(b'derived')
        return {3:str(three),4:str(four)}
    monkeypatch.setattr(comparison, 'configured_pipeline', Pipeline)
    monkeypatch.setattr(comparison, 'derive', derive)
    result = comparison.compare([image], tmp_path/'batch')
    assert calls == [1, 2]
    assert set(read(result)['samples'][0]['stages']) == {'1','2','3','4'}


def test_model_is_loaded_once_across_policies(monkeypatch):
    import sys
    from types import SimpleNamespace
    from mapmaker import reconstruction_runtime
    calls = []
    instance = object()
    def load(*args, **kwargs):
        calls.append(kwargs)
        return instance
    monkeypatch.setitem(sys.modules, 'inference', SimpleNamespace(Inference=load))
    monkeypatch.setattr(reconstruction_runtime, '_model', None)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    assert reconstruction_runtime.model() is instance
    assert reconstruction_runtime.model() is instance
    assert calls == [dict(compile=False)]
