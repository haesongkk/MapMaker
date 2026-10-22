import io
import sys
from contextlib import nullcontext
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from mapmaker import initial_vision
from mapmaker.scene_pipeline import create_run
from mapmaker.scene_run import read


class Tensor:
    def __init__(self, value): self.value = np.asarray(value)
    def cpu(self): return self
    def float(self): return self
    def numpy(self): return self.value
    def tolist(self): return self.value.tolist()
    def unsqueeze(self, *args): return self
    def to(self, *args): return self


def torch_stub():
    return SimpleNamespace(inference_mode=nullcontext, autocast=lambda *a, **kw: nullcontext(),
        cuda=SimpleNamespace(empty_cache=lambda: None), manual_seed=lambda _: None,
        bfloat16=None, __version__='test')


def test_ram_preserves_default_threshold_order_case_and_duplicates(tmp_path, monkeypatch):
    image = tmp_path/'image.png'
    Image.new('RGB',(8,8)).save(image)
    class Model:
        def eval(self): return self
        def to(self, device): return self
        @property
        def class_threshold(self): raise AssertionError('Do not touch model thresholds')
    monkeypatch.setitem(sys.modules,'torch',torch_stub())
    monkeypatch.setitem(sys.modules,'ram',SimpleNamespace(
        get_transform=lambda **kw: lambda image: Tensor([1]),
        inference_ram=lambda image, model: ['Wall | blue | Wall | Sofa','']))
    monkeypatch.setitem(sys.modules,'ram.models',SimpleNamespace(ram_plus=lambda **kw: Model()))
    assert initial_vision.ram_tags([image],tmp_path/'checkpoint')[str(image)] == ['Wall','blue','Wall','Sofa']


@pytest.mark.parametrize('tagger', ['ram++', 'qwen2.5-vl-7b'])
def test_all_prompts_and_masks_survive_without_selection(tmp_path,monkeypatch,tagger):
    data=io.BytesIO(); Image.new('RGB',(32,32)).save(data,format='PNG')
    run=create_run(data.getvalue(),tmp_path/'run',mode=1)
    prompts=['wall','blue','sofa']*15
    calls=[]
    monkeypatch.setattr(initial_vision,'ram_tags',lambda images,checkpoint:{str(images[0]):prompts})
    if tagger == 'qwen2.5-vl-7b':
        import json
        from mapmaker.scene_run import write, sha
        from mapmaker.qwen_tags import MODEL, REVISION, PROMPT
        meta=read(run/'scene_metadata.json');meta['execution']['tagger']=tagger
        write(run/'scene_metadata.json',meta)
        write(run/'logs/qwen_response.json',dict(model=MODEL,revision=REVISION,
            input_sha256=sha(run/meta['input_image']),raw_response='```json\n'+json.dumps(prompts)+'\n```',
            tags=prompts,prompt=PROMPT,generation={}))
        def no_ram(*args):raise AssertionError('Qwen branch must not load RAM++')
        monkeypatch.setattr(initial_vision,'ram_tags',no_ram)
    monkeypatch.setitem(sys.modules,'torch',torch_stub())
    class Processor:
        def __init__(self,model): pass  # Default settings only; no threshold override.
        def set_image(self,image): return {}
        def reset_all_prompts(self,state): pass
        def set_text_prompt(self,*,state,prompt):
            calls.append(prompt)
            masks=np.zeros((3,32,32),bool)
            masks[0,0,0]=True; masks[1,0,0]=True  # Tiny identical masks and an empty mask.
            return dict(masks=Tensor(masks),scores=Tensor([.51,.55,.52]))
    monkeypatch.setitem(sys.modules,'sam3.model_builder',SimpleNamespace(build_sam3_image_model=lambda **kw: object()))
    monkeypatch.setitem(sys.modules,'sam3.model.sam3_image_processor',SimpleNamespace(Sam3Processor=Processor))
    initial_vision.run_scene(run)
    meta=read(run/'scene_metadata.json')
    assert calls==prompts
    assert len(meta['objects'])==135
    assert len({o['id'] for o in meta['objects']})==135
    assert [o['mask_area'] for o in meta['objects']]==[1,1,0]*45
    assert all((run/o['mask']).exists() for o in meta['objects'])
    assert meta['execution']['baseline_policy']=='default_model_outputs_unfiltered_v1'


def test_reconstruction_attempts_every_mask_and_preserves_pose(tmp_path,monkeypatch):
    from mapmaker import initial_reconstruct, reconstruction_runtime, reconstruction_output
    from mapmaker.scene_run import sha,write
    data=io.BytesIO();Image.new('RGB',(8,8)).save(data,format='PNG')
    run=create_run(data.getvalue(),tmp_path/'run',mode=1)
    meta=read(run/'scene_metadata.json')
    for index in range(15):
        path=run/f'masks/{index}.png'
        Image.fromarray(np.full((8,8),255 if index else 0,dtype=np.uint8)).save(path)
        meta['objects'].append(dict(id=str(index),mask=f'masks/{index}.png',mask_sha256=sha(path)))
    write(run/'scene_metadata.json',meta)
    calls=[];pose={'rotation':[[1,0,0,0]],'translation':[[2,3,4]],'scale':[[1,2,3]]}
    class PoseTensor(Tensor):
        def detach(self):return self
    class Mesh:
        def export(self,path):__import__('pathlib').Path(path).write_bytes(b'mesh')
    def model(image,mask,*,seed):
        calls.append((mask.sum(),seed))
        if not mask.any():raise ValueError('model rejected empty mask')
        return dict(glb=Mesh(),gaussian=object(),**{k:PoseTensor(v) for k,v in pose.items()})
    monkeypatch.setattr(reconstruction_runtime,'prepare',lambda:(model,lambda _:object()))
    monkeypatch.setitem(sys.modules,'torch',torch_stub())
    def export(run,meta,successful,outputs,*,baseline=False):
        assert len(successful)==14 and outputs==[] and baseline
        assert all(obj['pose']==pose for obj in successful)
        write(run/'scene_metadata.json',meta)
    monkeypatch.setattr(reconstruction_output,'export_inference',export)
    initial_reconstruct.run_scene(run)
    assert len(calls)==15 and all(seed==42 for _,seed in calls)
    assert read(run/'scene_metadata.json')['objects'][0]['status']=='failed'
