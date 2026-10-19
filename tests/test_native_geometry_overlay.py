import hashlib
import io
import zipfile

import pytest

from scripts import native_geometry_overlay as overlay


def wheel(tmp_path, monkeypatch):
    path = tmp_path / 'native.whl'
    with zipfile.ZipFile(path, 'w') as archive:
        for name in overlay.FILES:
            archive.writestr(name, name.encode())
    monkeypatch.setattr(overlay, 'WHEEL_SHA256', hashlib.sha256(path.read_bytes()).hexdigest())
    return path


def test_staging_verifies_existing_bytes(tmp_path, monkeypatch):
    source = wheel(tmp_path, monkeypatch)
    target = overlay.stage_geometry_wheel(source, tmp_path / 'runtime')
    assert overlay.stage_geometry_wheel(source, tmp_path / 'runtime') == target
    (target / 'manifold3d.pyi').write_text('modified')
    with pytest.raises(ValueError, match='modified'):
        overlay.stage_geometry_wheel(source, tmp_path / 'runtime')


def test_hash_rejection_writes_nothing(tmp_path):
    source = tmp_path / 'native.whl'
    source.write_bytes(b'bad wheel')
    with pytest.raises(ValueError, match='hash mismatch'):
        overlay.stage_geometry_wheel(source, tmp_path / 'runtime')
    assert not (tmp_path / 'runtime').exists()


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'unexpected.py'])
def test_unexpected_entries_rejected(name):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        for item in overlay.FILES:
            archive.writestr(item, b'x')
        archive.writestr(name, b'x')
    with zipfile.ZipFile(data) as archive:
        with pytest.raises(ValueError, match='layout'):
            overlay.validate_layout(archive)


def test_duplicate_entries_rejected():
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        with pytest.warns(UserWarning):
            archive.writestr('duplicate', b'x')
            archive.writestr('duplicate', b'y')
    with zipfile.ZipFile(data) as archive:
        with pytest.raises(ValueError, match='Duplicate'):
            overlay.validate_layout(archive)


def test_finalized_transfer_needs_no_native_import(tmp_path, monkeypatch):
    import builtins
    from mapmaker.scene_placement import finalize_scene, PLACEMENT_VERSION
    from mapmaker.scene_run import sha, write
    (tmp_path / 'scene.glb').write_bytes(b'hashed finalized scene')
    placement = dict(version=PLACEMENT_VERSION, scene_sha256=sha(tmp_path / 'scene.glb'),
                     overlap_refinement={'complete': True},supported_refinement={'complete': True})
    write(tmp_path / 'scene_metadata.json', dict(pointmap={'path': 'verified'}, placement=placement))
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name == 'manifold3d':
            raise AssertionError('Parent interpreter must not import native extension')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded_import)
    assert finalize_scene(tmp_path, render=False, overlap_repair=True) == placement
    assert finalize_scene(tmp_path, render=False, supported_repair=True) == placement
