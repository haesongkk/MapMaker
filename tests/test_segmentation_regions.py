import contextlib
import io
import sys
import types
import numpy as np
import pytest
from PIL import Image
from mapmaker.segmentation_regions import crop_queries, restore_crop_mask
from mapmaker.scene_pipeline import create_run
from mapmaker.scene_run import read
from mapmaker.scene_transfer import pack_run, unpack_run


def test_crop_mapping_and_truncated_fragments():
    mask = np.zeros((20, 30), bool)
    mask[4:8, 9:12] = True
    result = restore_crop_mask(mask, (10, 15, 40, 35), (100, 80))
    assert result.shape == (80, 100) and result[19:23, 19:22].all()
    assert result.sum() == mask.sum()
    mask[0, 3] = True
    assert restore_crop_mask(mask, (10, 15, 40, 35), (100, 80)) is None
    assert restore_crop_mask(mask, (10, 0, 40, 20), (100, 80)) is not None


def test_localized_queries_are_equivariant_to_prompt_renaming():
    regions = [dict(image='crop', box=(0, 0, 30, 20))]
    large = np.ones((20, 30), bool)
    a = crop_queries(['a', 'b'], regions, {'crop': ['a', 'b']}, {}, [(dict(name='a'), large)], 10000)
    b = crop_queries(['x', 'y'], regions, {'crop': ['x', 'y']}, {}, [(dict(name='x'), large)], 10000)
    assert a == [dict(box=(0, 0, 30, 20), prompts=['b'])]
    assert b == [dict(box=(0, 0, 30, 20), prompts=['y'])]


def test_instance_outside_crop_does_not_suppress_another_localized_instance():
    mask = np.zeros((100, 100), bool)
    mask[10:40, 10:40] = True
    regions = [dict(image='left', box=(0, 0, 50, 100)),
               dict(image='right', box=(50, 0, 100, 100))]
    for word in ['a', 'renamed']:
        queries = crop_queries([word], regions, {'left': [word], 'right': [word]},
                               {}, [(dict(name=word), mask)], mask.size)
        assert queries == [dict(box=regions[1]['box'], prompts=[word])]


@pytest.mark.parametrize('tags', [['bottle'], []])
def test_full_vision_entrypoint_and_artifact_transfer_without_gpu(tmp_path, monkeypatch, tags):
    from mapmaker import scene_vision

    class Tensor:
        def __init__(self, value): self.value = np.asarray(value)
        def cpu(self): return self
        def float(self): return self
        def numpy(self): return self.value
        def tolist(self): return self.value.tolist()

    class Processor:
        def __init__(self, model): self.model = model
        def set_image(self, image): return image.size
        def reset_all_prompts(self, state): pass
        def set_text_prompt(self, state, prompt):
            width, height = state
            mask = np.zeros((1, height, width), bool)
            mask[0, height//2-10:height//2+10, width//2-10:width//2+10] = True
            return dict(masks=Tensor(mask), scores=Tensor([.99]))

    torch = types.ModuleType('torch')
    torch.cuda = types.SimpleNamespace(empty_cache=lambda: None)
    torch.manual_seed = lambda seed: None
    torch.inference_mode = contextlib.nullcontext
    torch.autocast = lambda *a, **k: contextlib.nullcontext()
    torch.bfloat16 = 'fixture'
    torch.__version__ = 'fixture'
    monkeypatch.setitem(sys.modules, 'torch', torch)
    for name in ('sam3', 'sam3.model', 'sam3.model_builder', 'sam3.model.sam3_image_processor'):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    sys.modules['sam3.model_builder'].build_sam3_image_model = lambda **k: None
    sys.modules['sam3.model.sam3_image_processor'].Sam3Processor = Processor
    monkeypatch.setattr(scene_vision, 'ram_tags', lambda paths, *a, **k: {str(p): tags for p in paths})
    from mapmaker import point_proposals
    monkeypatch.setattr(point_proposals, 'validate_interactive_weights', lambda *a: {'fixture': True})
    def point_fixture(model, state, size, **kwargs):
        if tags:
            return [], {'fixture': True}
        mask = np.zeros(size[::-1], bool)
        mask[300:330, 300:330] = True
        record = dict(name='object', confidence=.93, area=900,
            proposal_method='uniform_point_grid', confidence_kind='predicted_mask_iou_not_object_presence',
            supporting_points=[[305,305],[320,320]], stability=.99)
        return [(record, mask)], {'fixture': True}
    monkeypatch.setattr(point_proposals, 'scan_small_instances', point_fixture)
    data = io.BytesIO()
    Image.new('RGB', (900, 800), 'white').save(data, 'PNG')
    run = create_run(data.getvalue(), tmp_path/('a'*32))
    scene_vision.run_scene(run)
    metadata = read(run/'scene_metadata.json')
    assert read(run/'status.json')['stage'] == 'segmented'
    if tags:
        assert len(metadata['objects']) > 1
        assert metadata['object_extraction']['localized_segmentation']['views'] == 14
    else:
        assert len(metadata['objects']) == 1
        assert metadata['objects'][0]['selection_evidence']['route'] == 'stable_point_mask_agreement'
        assert metadata['object_extraction']['localized_segmentation']['views'] == 0
    pack_run(run, tmp_path/'result.zip')
    unpack_run(tmp_path/'result.zip', tmp_path/'download')
    assert read(tmp_path/'download/scene_metadata.json') == metadata
