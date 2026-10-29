"""Reproduce SAM3D's pinned MoGe-1 pointmap, without loading SAM3D meshes/models."""
import argparse,json,time,sys,os,hashlib
from pathlib import Path
import numpy as np
from PIL import Image
import torch

p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--moge-source',type=Path,required=True);a=p.parse_args()
torch.set_num_threads(2)
torch.cuda.set_per_process_memory_fraction(.7)
sys.path.insert(0,str(a.moge_source.resolve()))
os.environ['HF_HOME']=str(Path('.runtime/hf-depth-cache').resolve())
from moge.model.v1 import MoGeModel
revision='ad326bfb61facd6c52b5a825bc1e34d7c97d9672'
model=MoGeModel.from_pretrained('Ruicheng/moge-vitl',revision=revision).to('cuda').eval()
for scene in sorted(a.root.iterdir()):
 if not (scene/'state.json').exists():continue
 if (scene/'pointmap.npz').exists() and (scene/'depth-provenance.json').exists():
  previous=json.loads((scene/'depth-provenance.json').read_text(encoding='utf-8'))
  if hashlib.sha256((scene/'pointmap.npz').read_bytes()).hexdigest()==previous['pointmap_sha256']:continue
 state=json.loads((scene/'state.json').read_text(encoding='utf-8'));image=Image.open(state['input_image']).convert('RGB')
 pixels=np.asarray(image);x=torch.tensor(pixels.transpose(2,0,1).copy(),dtype=torch.float32,device='cuda')/255
 start=time.monotonic()
 with torch.inference_mode(),torch.autocast(device_type='cuda',dtype=torch.float16):
  output=model.infer(x,force_projection=False)
 points=output['points'].float().cpu().numpy()*np.array([-1,-1,1],np.float32)
 temporary=scene/'pointmap.partial.npz'
 np.savez_compressed(temporary,points=points,mask=output['mask'].cpu().numpy(),intrinsics=output['intrinsics'].float().cpu().numpy())
 temporary.replace(scene/'pointmap.npz')
 info=dict(model='Ruicheng/moge-vitl',revision=revision,code_revision='a8c37341bc0325ca99b9d57981cc3bb2bd3e255b',
     frame='sam3d_pytorch3d_camera',force_projection=False,resolution_level=9,seconds=time.monotonic()-start,
     image_sha256=hashlib.sha256(Path(state['input_image']).read_bytes()).hexdigest(),
     pointmap_sha256=hashlib.sha256((scene/'pointmap.npz').read_bytes()).hexdigest(),device=torch.cuda.get_device_name(),
     metric_scale_verified=False,maximum_memory_gb=torch.cuda.max_memory_allocated()/1e9)
 (scene/'depth-provenance.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
 print(scene.name,json.dumps(info),flush=True)
 del output,x;torch.cuda.empty_cache()
