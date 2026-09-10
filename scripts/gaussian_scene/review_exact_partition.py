"""Review each object against masks of the actual trained scene, with occlusion."""
import json
from pathlib import Path
import numpy as np,torch
from PIL import Image,ImageDraw
from gsplat.rendering import rasterization
r=(Path(__file__).resolve().parents[2]/'outputs/images/A_MARCEAU/gaussian_editable');scene=r.parent;stage=r/'rendered_scene/object_scene';manifest=json.loads((r/'partition.json').read_text());assert manifest.get('source_views')==808;objects=manifest['objects'];byname={o['name']:o for o in objects};ckpt=torch.load(scene/'gs/ckpts/ckpt_7999_rank0.pt',map_location='cuda',weights_only=False);s=ckpt['splats'];T=np.array(ckpt['transform']);scale=np.cbrt(np.linalg.det(T[:3,:3]));cams=json.loads((scene/'gs_data/cameras.json').read_text());out=r/'object_review_exact';out.mkdir(exist_ok=True);rows=[];quats=torch.nn.functional.normalize(s['quats'],dim=-1);scales=s['scales'].exp();opacity=s['opacities'].sigmoid().reshape(-1);colors=s['sh0'][:,0]*.28209479177387814+.5
for j,obj in enumerate(objects):
 if obj['id']==0:continue
 members=[o for o in objects if o['name']==obj['name'] or o.get('parent_object')==obj['name']];ids_np=np.concatenate([np.load(r/o['source_ids']) for o in members]);ids=torch.as_tensor(ids_np,device='cuda');view=obj['review_view'];pose=T@np.linalg.inv(np.array(cams[view]['extrinsic']));pose[:3,:3]/=scale;K=np.array(cams[view]['intrinsic']);h,w=480,832;vm=torch.tensor(np.linalg.inv(pose),dtype=torch.float32,device='cuda')[None];kk=torch.tensor(K,dtype=torch.float32,device='cuda')[None]
 with torch.inference_mode():
  rgb,alpha,_=rasterization(s['means'][ids],quats[ids],scales[ids],opacity[ids],colors[ids],vm,kk,w,h,render_mode='RGB',radius_clip=3)
  feature=torch.zeros((len(s['means']),1),device='cuda');feature[ids]=1;visible,total,_=rasterization(s['means'],quats,scales,opacity,feature,vm,kk,w,h,render_mode='RGB',radius_clip=3)
 ratio=(visible[0,...,0]/total[0,...,0].clamp_min(1e-6)).cpu().numpy();prediction=ratio>.5;data=np.load(stage/'detections'/f'{view}.npz');gold=np.zeros((h,w),bool)
 for member in members:
  observations=json.loads((r/Path(member['ply']).parent/'observations.json').read_text())
  for obs in observations:
   if obs['view']==view:gold|=np.unpackbits(data['masks_packed'][obs['detection_index']],count=h*w).reshape(h,w).astype(bool)
 intersection=int((prediction&gold).sum());union=int((prediction|gold).sum());precision=intersection/max(int(prediction.sum()),1);recall=intersection/max(int(gold.sum()),1);iou=intersection/max(union,1)
 aa=alpha[0].cpu().numpy();rr=rgb[0].cpu().numpy();composite=np.clip(rr+(1-aa)*.85,0,1);ys,xs=np.nonzero(aa[...,0]>.05);bounds=[max(0,int(xs.min())-5),max(0,int(ys.min())-5),min(w,int(xs.max())+6),min(h,int(ys.max())+6)] if len(xs) else [0,0,w,h];im=Image.fromarray((composite*255).astype('uint8')).crop(bounds);im.thumbnail((240,230));source=np.array(Image.open(r/'rendered_scene/gs_data/images'/f'{view}.png').convert('RGB'));rgba=Image.fromarray(np.dstack([source,gold.astype('uint8')*255]));yy,xx=np.where(gold);ref=rgba.crop([max(0,int(xx.min())-5),max(0,int(yy.min())-5),min(w,int(xx.max())+6),min(h,int(yy.max())+6)]);ref.thumbnail((240,230));tile=Image.new('RGB',(480,260),'#dddddd');tile.paste(ref,(0,25),ref);tile.paste(im,(240,25));ImageDraw.Draw(tile).text((5,5),f"{obj['name']} / IoU {iou:.2f} / {len(ids_np)}",fill='black');tile.save(out/f"{obj['name']}.jpg");overlay=source.copy();overlay[prediction&~gold]=[255,40,40];overlay[gold&~prediction]=[40,80,255];Image.fromarray(overlay).save(out/f"{obj['name']}_boundary.jpg");rows.append(dict(name=obj['name'],label=obj['label'],view=view,gaussians=len(ids_np),children=[o['name'] for o in members if o!=obj],iou=iou,precision=precision,recall=recall,predicted_pixels=int(prediction.sum()),mask_pixels=int(gold.sum())))
 if j%20==0:print('EXACT_OBJECT_REVIEW',j,flush=True)
for label in sorted({o['label'] for o in rows}):
 items=[o for o in rows if o['label']==label];page=Image.new('RGB',(1440,260*((len(items)+2)//3)),'white')
 for i,item in enumerate(items):page.paste(Image.open(out/f"{item['name']}.jpg"),((i%3)*480,(i//3)*260))
 page.save(out/(label.replace(' ','_')+'_gallery.jpg'))
(out/'manifest.json').write_text(json.dumps(rows,indent=2));print('EXACT_REVIEW_COMPLETE',len(rows),flush=True)
