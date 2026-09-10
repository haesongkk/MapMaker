"""Render the trained scene at every original calibrated camera for segmentation.
Original video images remain unchanged; this isolated stage detects the actual
Gaussian appearance and avoids 2D generation/3D reconstruction misalignment.
"""
import json,time,hashlib
from pathlib import Path
import numpy as np,torch
from PIL import Image
from gsplat.rendering import rasterization
scene=(Path(__file__).resolve().parents[2]/'outputs/images/A_MARCEAU').resolve();r=scene/'gaussian_editable';dest=r/'rendered_scene';(dest/'gs_data/images').mkdir(parents=True,exist_ok=True);(dest/'gs_data/depths').mkdir(exist_ok=True)
for local,source in [(dest/'objects.json',scene/'objects.json'),(dest/'gs',scene/'gs'),(dest/'gs_data/points.ply',scene/'gs_data/points.ply'),(dest/'gs_data/cameras.json',scene/'gs_data/cameras.json')]:
 if not local.exists():local.symlink_to(source)
ckpt=torch.load(scene/'gs/ckpts/ckpt_7999_rank0.pt',map_location='cuda',weights_only=False);s=ckpt['splats'];T=np.array(ckpt['transform']);scale=np.cbrt(np.linalg.det(T[:3,:3]));cams=json.loads((scene/'gs_data/cameras.json').read_text());views=sorted(k for k,v in cams.items() if isinstance(v,dict) and 'extrinsic' in v and (scene/'gs_data/images'/f'{k}.png').exists());quats=torch.nn.functional.normalize(s['quats'],dim=-1);scales=s['scales'].exp();opacity=s['opacities'].sigmoid().reshape(-1);colors=s['sh0'][:,0]*.28209479177387814+.5;start=time.monotonic()
with (scene/'gs/ckpts/ckpt_7999_rank0.pt').open('rb') as stream:checkpoint_sha=hashlib.file_digest(stream,'sha256').hexdigest()
source_signature=hashlib.sha256((checkpoint_sha+':gsplat-rgb-ed-radius3-v2').encode()+(scene/'gs_data/cameras.json').read_bytes()).hexdigest();metadata=dest/'gs_data/render_metadata';metadata.mkdir(exist_ok=True)
with torch.inference_mode():
 for j,view in enumerate(views):
  imagepath=dest/'gs_data/images'/f'{view}.png';depthpath=dest/'gs_data/depths'/f'{view}.png'
  sidecar=metadata/f'{view}.json';w,h=Image.open(scene/'gs_data/images'/f'{view}.png').size
  if imagepath.exists() and depthpath.exists() and sidecar.exists():
   previous=json.loads(sidecar.read_text())
   if previous.get('source_signature')==source_signature and previous.get('shape')==[h,w]:continue
  w,h=Image.open(scene/'gs_data/images'/f'{view}.png').size;pose=T@np.linalg.inv(np.array(cams[view]['extrinsic']));pose[:3,:3]/=scale;K=np.array(cams[view]['intrinsic']);rgbd,alpha,_=rasterization(s['means'],quats,scales,opacity,colors,torch.tensor(np.linalg.inv(pose),dtype=torch.float32,device='cuda')[None],torch.tensor(K,dtype=torch.float32,device='cuda')[None],w,h,render_mode='RGB+ED',radius_clip=3)
  a=alpha[0,...,0].cpu().numpy();data=rgbd[0].cpu().numpy();Image.fromarray((data[...,:3].clip(0,1)*255).round().astype('uint8')).save(imagepath);depth=data[...,3]/scale;depth[a<.2]=0;Image.fromarray(depth.astype(np.float16).view(np.uint16)).save(depthpath)
  sidecar.write_text(json.dumps(dict(source_signature=source_signature,shape=[h,w])))
  if (j+1)%80==0:print('RENDERED_CALIBRATED_VIEWS',j+1,len(views),round(time.monotonic()-start),flush=True)
(dest/'render_manifest.json').write_text(json.dumps(dict(views=len(views),source_signature=source_signature,checkpoint_sha256=checkpoint_sha,source='gs/ckpts/ckpt_7999_rank0.pt',depth='Expected Gaussian depth / normalization scale; float16 reinterpreted as uint16 PNG',sh_degree=0,radius_clip=3),indent=2));print('RENDER_INPUTS_COMPLETE',len(views),flush=True)
