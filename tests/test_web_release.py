import hashlib
import io
import zipfile
import pytest
from scripts.bootstrap_web_release import apply, FILES


def archive(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        for name, content in files.items():
            z.writestr(name, content)
    data = stream.getvalue()
    return data, hashlib.sha256(data).hexdigest()


def test_static_release_keeps_backend_and_vendor(tmp_path):
    (tmp_path/'web/vendor').mkdir(parents=True)
    (tmp_path/'web/vendor/three.js').write_text('existing vendor')
    (tmp_path/'backend.py').write_text('existing backend')
    data, digest = archive({name: name.encode() for name in FILES})
    apply(data, digest, tmp_path)
    assert (tmp_path/'backend.py').read_text() == 'existing backend'
    assert (tmp_path/'web/vendor/three.js').read_text() == 'existing vendor'
    for name in FILES:
        assert (tmp_path/name).read_text() == name


@pytest.mark.parametrize('extra', ['../outside.py', 'mapmaker/cloud_web.py'])
def test_unexpected_entries_are_rejected_before_writes(tmp_path, extra):
    data, digest = archive({**{name: 'new' for name in FILES}, extra: 'bad'})
    with pytest.raises(ValueError):
        apply(data, digest, tmp_path)
    assert not list(tmp_path.iterdir())


def test_checksum_mismatch_is_rejected_before_writes(tmp_path):
    data, _ = archive({name: 'new' for name in FILES})
    with pytest.raises(ValueError):
        apply(data, 'wrong', tmp_path)
    assert not list(tmp_path.iterdir())
