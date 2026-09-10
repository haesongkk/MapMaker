"""Optimize Gaussian instance membership against rendered panoptic masks.
All original geometry, opacity and appearance tensors remain frozen. Only
semantic logits are trained; output assignment changes cannot alter full-scene RGB.
"""
import argparse,json,time
from pathlib import Path
import numpy as np,torch
from gsplat.rendering import rasterization
p=argparse.ArgumentParser();p.add_argument('--steps',type=int,default=1616);p.add_argument('--resume',action='store_true');p.add_argument('--learning-rate',type=float,default=.08);p.add_argument('--optimizer-epsilon',type=float,default=1e-10);args=p.parse_args();torch.set_num_threads(8);r=(Path(__file__).resolve().parents[2]/'outputs/images/A_MARCEAU/gaussian_editable');stage=r/'rendered_scene/object_scene';catalog=json.loads((r/'rendered_gaussian_instances.json').read_text())['objects'];manifest=json.loads((stage/'detection_manifest.json').read_text());mapping={(obs['view'],obs['detection_index']):obj['id'] for obj in catalog for obs in obj['observations']};out=r/'semantic_refinement';out.mkdir(exist_ok=True);cams=json.loads((r.parent/'gs_data/cameras.json').read_text());ckpt=torch.load(r.parent/'gs/ckpts/ckpt_7999_rank0.pt',map_location='cuda',weights_only=False);s=ckpt['splats'];T=np.array(ckpt['transform']);scale=np.cbrt(np.linalg.det(T[:3,:3]));samples=[]
for view in manifest['views']:
 record=json.loads((stage/'detections'/f'{view}.json').read_text());data=np.load(stage/'detections'/f'{view}.npz');hh,ww=map(int,data['shape']);h,w=hh//2,ww//2;target=np.zeros((h,w),np.int64);known=np.ones((h,w),bool)
 # Broad masks first; visible smaller instances own overlapping pixels.
 for obs in sorted(record['instances'],key=lambda x:x['pixels'],reverse=True):
  mask=np.unpackbits(data['masks_packed'][obs['index']],count=hh*ww).reshape(hh,ww)[::2,::2][:h,:w].astype(bool);gid=mapping.get((view,obs['index']))
  if gid is None:known[mask]=False
  else:target[mask]=gid;known[mask]=True
 target[~known]=-1;pose=T@np.linalg.inv(np.array(cams[view]['extrinsic']));pose[:3,:3]/=scale;K=np.array(cams[view]['intrinsic']);K[:2]*=.5;samples.append((view,torch.tensor(target,device='cuda'),torch.tensor(np.linalg.inv(pose),dtype=torch.float32,device='cuda')[None],torch.tensor(K,dtype=torch.float32,device='cuda')[None],w,h))
n=len(s['means']);classes=len(catalog)+1;initial=np.load(r/'gaussian_object_ids.npy');logits=torch.full((n,classes),-1.5,device='cuda');logits[torch.arange(n,device='cuda'),torch.as_tensor(initial,device='cuda')]=1.5
if args.resume and (out/'logits.pt').exists():logits.copy_(torch.load(out/'logits.pt',map_location='cuda',weights_only=True).float())
logits=torch.nn.Parameter(logits);optimizer=torch.optim.Adam([logits],lr=args.learning_rate,eps=args.optimizer_epsilon);quats=torch.nn.functional.normalize(s['quats'],dim=-1).detach();scales=s['scales'].exp().detach();opacity=s['opacities'].sigmoid().reshape(-1).detach();means=s['means'].detach();generator=np.random.default_rng(20260910);order=generator.permutation(len(samples));history=[];started=time.monotonic()
for step in range(args.steps):
 if step and step%len(samples)==0:order=generator.permutation(len(samples))
 view,target,V,K,w,h=samples[int(order[step%len(samples)])];temperature=max(.4,1.-.6*step/max(args.steps-1,1));probabilities=torch.softmax(logits/temperature,dim=-1);rendered,alpha,_=rasterization(means,quats,scales,opacity,probabilities,V,K,w,h,render_mode='RGB',radius_clip=3,channel_chunk=32);prediction=rendered[0]/alpha[0].clamp_min(1e-6);valid=(target>=0)&(alpha[0,...,0]>.2);truth=target[valid];selected=prediction[valid].gather(1,truth[:,None])[:,0];counts=torch.bincount(truth,minlength=classes).float();class_weights=(truth.numel()/counts.clamp_min(1)).sqrt().clamp(max=15);weights=class_weights[truth];loss=(-(selected.clamp_min(1e-7)).log()*weights).sum()/weights.sum().clamp_min(1);assert torch.isfinite(loss),view;optimizer.zero_grad(set_to_none=True);loss.backward();optimizer.step()
 if (step+1)%20==0:
  row=dict(step=step+1,loss=float(loss.detach()),view=view,temperature=temperature,seconds=time.monotonic()-started);history.append(row);(out/'progress.json').write_text(json.dumps(row,indent=2));print('SEMANTIC_MEMBERSHIP',json.dumps(row),flush=True)
 if (step+1)%404==0 or step+1==args.steps:
  with torch.no_grad():
   labels=logits.argmax(-1).cpu().numpy().astype(np.int32);np.save(out/'gaussian_object_ids.npy',labels);torch.save(logits.detach().half().cpu(),out/'logits.pt');(out/'history.json').write_text(json.dumps(history,indent=2))
(out/'report.json').write_text(json.dumps(dict(steps=args.steps,gaussians=n,classes=classes,geometry_frozen=True,appearance_frozen=True,opacity_frozen=True,seconds=time.monotonic()-started,status='assignment_trained_render_review_pending'),indent=2));print('SEMANTIC_REFINEMENT_COMPLETE',flush=True)
