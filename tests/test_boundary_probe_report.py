from contextlib import nullcontext
import sys
from types import SimpleNamespace

import numpy as np
from PIL import Image

from mapmaker.scene_run import read, write, sha
from scripts import probe_instance_boundaries as probe


def test_actual_report_path_serializes_numpy_decoder_outputs(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    (source / 'input').mkdir(parents=True)
    (source / 'masks').mkdir()
    image = source / 'input/source_image.png'
    Image.new('RGB', (80, 80)).save(image)
    mask = np.zeros((80, 80), bool)
    mask[10:70, 10:70] = True
    mask_path = source / 'masks/0.png'
    Image.fromarray(mask.astype('uint8') * 255).save(mask_path)
    write(source / 'scene_metadata.json', dict(input_image='input/source_image.png',
          input_sha256=sha(image), objects=[dict(status='generated', mask='masks/0.png',
          mask_sha256=sha(mask_path))]))
    checkpoint = tmp_path / 'sam3.pt'
    checkpoint.write_bytes(b'checkpoint')
    monkeypatch.setattr(probe, 'SAM3_CHECKPOINT', checkpoint)

    class Model:
        def predict_inst(self, state, **kwargs):
            return (np.tile(mask, (3, 3, 1, 1)), np.full((3, 3), .99, np.float32),
                    np.full((3, 3, 16, 16), 2., np.float32))

    class Processor:
        def __init__(self, model):
            self.model = model

        def set_image(self, image):
            return None

    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: True), bfloat16=None,
        manual_seed=lambda seed: None, inference_mode=nullcontext,
        autocast=lambda *args, **kwargs: nullcontext()))
    monkeypatch.setitem(sys.modules, 'sam3.model_builder', SimpleNamespace(build_sam3_image_model=lambda **kwargs: Model()))
    monkeypatch.setitem(sys.modules, 'sam3.model.sam3_image_processor', SimpleNamespace(Sam3Processor=Processor))
    from mapmaker import point_proposals
    monkeypatch.setattr(point_proposals, 'validate_interactive_weights', lambda *args: dict(checkpoint_coverage='test'))
    output = tmp_path / 'output'
    probe.main(source, output)
    report = read(output / 'boundary-audit.json')
    assert report['completed'] and report['selected_count'] == 1
    assert len(report['records'][0]['queries']) == 3
    for query in report['records'][0]['queries']:
        for candidate in query['candidates']:
            assert candidate['passes_existing_decoder_filters'] is True
            assert candidate['mask_iou'] == 1.
            assert sha(output / candidate['mask']) == candidate['mask_sha256']
