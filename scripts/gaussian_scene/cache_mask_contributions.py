"""Cache opacity-aware Gaussian mask support as detections become available."""
import json,time,hashlib,os
from pathlib import Path
import numpy as np,torch
from gsplat.rendering import rasterization
from raster_contributions import contributions
r=(Path(__file__).resolve().parents[2]/'outputs/images/A_MARCEAU/gaussian_editable');scene=r.parent;stage=r/'rendered_scene/object_scene';out=r/'rendered_mask_support';out.mkdir(exist_ok=True);manifest=json.loads((stage/'detection_manifest.json').read_text());cameras=json.loads((scene/'gs_data/cameras.json').read_text());ckpt=torch.load(scene/'gs/ckpts/ckpt_7999_rank0.pt',map_location='cuda',weights_only=False);s=ckpt['splats'];T=np.array(ckpt['transform']);scale=np.cbrt(np.linalg.det(T[:3,:3]));quats=torch.nn.functional.normalize(s['quats'],dim=-1);scales=s['scales'].exp();opacity=s['opacities'].sigmoid().reshape(-1);colors=s['sh0'][:,0]*.28209479177387814+.5;started=time.monotonic()
with (scene/'gs/ckpts/ckpt_7999_rank0.pt').open('rb') as stream:checkpoint_sha=hashlib.file_digest(stream,'sha256').hexdigest()
with torch.inference_mode():
 for j,view in enumerate(manifest['views']):
  recordpath=stage/'detections'/f'{view}.json';last=time.monotonic()
  while not recordpath.exists():
   if time.monotonic()-last>300:raise RuntimeError('Detection stalled for 300 seconds; resume cache after detection recovers')
   time.sleep(1)
  record=json.loads(recordpath.read_text());assert record['signature']==manifest['signature'];signature=hashlib.sha256((checkpoint_sha+record['signature']+record['image_sha256']+':exact-contribution-v2-full-resolution').encode()).hexdigest();dest=out/f'{view}.npz';sidecar=dest.with_suffix('.json')
  if dest.exists() and sidecar.exists() and json.loads(sidecar.read_text()).get('signature')==signature:continue
  packed=np.load(stage/'detections'/f'{view}.npz');h,w=map(int,packed['shape']);pose=T@np.linalg.inv(np.array(cameras[view]['extrinsic']));pose[:3,:3]/=scale;K=np.array(cameras[view]['intrinsic']);rgb,alpha,meta=rasterization(s['means'],quats,scales,opacity,colors,torch.tensor(np.linalg.inv(pose),dtype=torch.float32,device='cuda')[None],torch.tensor(K,dtype=torch.float32,device='cuda')[None],w,h,render_mode='RGB',radius_clip=3,packed=False)
  gids,pixels,weights=contributions(meta);unique,inverse=torch.unique(gids,return_inverse=True);total=torch.bincount(inverse,weights,minlength=len(unique));visible=total>.01;arrays={'visible_ids':unique[visible].cpu().numpy().astype(np.int32)}
  for row in record['instances']:
   idx=row['index'];mask=np.unpackbits(packed['masks_packed'][idx],count=h*w).astype(bool);inside=torch.as_tensor(mask,device='cuda')[pixels];positive=torch.bincount(inverse[inside],weights[inside],minlength=len(unique));fraction=positive/total.clamp_min(1e-12);keep=visible&(fraction>=.5);arrays[f'instance_{idx}']=unique[keep].cpu().numpy().astype(np.int32);arrays[f'weight_{idx}']=fraction[keep].cpu().numpy().astype(np.float16)
  tmp=dest.with_suffix('.tmp.npz');np.savez_compressed(tmp,**arrays);os.replace(tmp,dest);tmp=sidecar.with_suffix('.tmp.json');tmp.write_text(json.dumps(dict(signature=signature,view=view,visible_gaussians=int(visible.sum()),masks=len(record['instances']),intersections=len(gids))));os.replace(tmp,sidecar)
  del rgb,alpha,meta,gids,pixels,weights,unique,inverse,total,arrays
  if (j+1)%20==0:print('EXACT_MASK_SUPPORT',j+1,len(manifest['views']),round(time.monotonic()-started),flush=True)
(out/'manifest.json').write_text(json.dumps(dict(complete=True,views=len(manifest['views']),source_gaussians=len(s['means']),minimum_pixel_weight=.01,minimum_mask_fraction=.5,method='Exact front-to-back alpha * transmittance integrated across rendered pixels',detection_signature=manifest['signature']),indent=2));print('EXACT_MASK_SUPPORT_COMPLETE',flush=True)
