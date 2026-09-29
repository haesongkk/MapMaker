"""Input selection/identity checks; these tests do not claim GPU E2E coverage."""
import importlib.util
from pathlib import Path

from PIL import Image

spec = importlib.util.spec_from_file_location('sample_validation', Path(__file__).parents[1] / 'scripts/validate_samples.py')
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)


def test_scan_nested_duplicates_hidden_and_generated(tmp_path, monkeypatch):
    monkeypatch.setattr(validation, 'ROOT', tmp_path)
    folder = tmp_path / 'samples'
    for rel in ['a/room.png', 'b/room.png', '.hidden/room.png', 'screenshots/result.png', 'room_thumbnail.png']:
        p = folder / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (4, 3), 'red').save(p)
    records, excluded = validation.scan(folder)
    assert [r['sample'] for r in records] == ['samples/a/room.png', 'samples/b/room.png']
    assert len({r['sample_id'] for r in records}) == 2
    assert len(excluded) == 3
    assert records[0]['sha256'] == records[1]['sha256']


def test_identity_uses_normalized_pixels_and_rejects_changed_input(tmp_path):
    source, output = tmp_path / 'source.jpg', tmp_path / 'normalized.png'
    im = Image.new('RGB', (12, 8), 'red')
    exif = im.getexif()
    exif[274] = 6
    im.save(source, exif=exif)
    with Image.open(source) as image:
        validation.ImageOps.exif_transpose(image).convert('RGB').save(output)
    assert validation.same_input(source, output)
    Image.new('RGB', (8, 12), 'blue').save(output)
    assert not validation.same_input(source, output)
