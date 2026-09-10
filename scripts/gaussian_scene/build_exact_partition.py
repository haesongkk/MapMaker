"""Build the final-candidate partition from opacity-aware multiview evidence."""
import json,time,shutil
from pathlib import Path
from collections import defaultdict
import numpy as np,torch
from plyfile import PlyData,PlyElement
from PIL import Image
r=(Path(__file__).resolve().parents[2]/'outputs/images/A_MARCEAU/gaussian_editable');stage=r/'rendered_scene/object_scene';cache=r/'rendered_mask_support'
for path in [r/'rendered_gaussian_instances.json',cache/'manifest.json']:
 started=time.monotonic()
 while not path.exists():
  if time.monotonic()-started>3600:raise RuntimeError('Waiting for upstream stages exceeded one hour')
  time.sleep(2)
cat=json.loads((r/'rendered_gaussian_instances.json').read_text())['objects'];manifest=json.loads((stage/'detection_manifest.json').read_text());n=json.loads((r/'source_manifest.json').read_text())['gaussians'];byview=defaultdict(lambda:defaultdict(list))
for obj in cat:
 for obs in obj['observations']:byview[obs['view']][obj['id']].append(obs['detection_index'])
votes=torch.zeros((len(cat)+1,n),device='cuda');visible_counts=torch.zeros(n,device='cuda');start=time.monotonic()
for j,view in enumerate(manifest['views']):
 data=np.load(cache/f'{view}.npz');visible=torch.as_tensor(data['visible_ids'].astype(np.int64),device='cuda');visible_counts[visible]+=1
 for gid,indices in byview[view].items():
  ids=torch.as_tensor(np.concatenate([data[f'instance_{idx}'] for idx in indices]).astype(np.int64),device='cuda');weights=torch.as_tensor(np.concatenate([data[f'weight_{idx}'] for idx in indices]).astype(np.float32),device='cuda')
  if len(indices)>1:
   per_view=torch.zeros(n,device='cuda');per_view.scatter_reduce_(0,ids,weights,reduce='amax');votes[gid]+=per_view
  else:votes[gid,ids]+=weights
 if (j+1)%80==0:print('EXACT_VOTE_VIEWS',j+1,len(manifest['views']),round(time.monotonic()-start),flush=True)
maximum=votes.max(0);labels=maximum.indices;strength=maximum.values;nonbuilding=torch.tensor([o['id'] for o in cat if o['label']!='building'],device='cuda');small=votes[nonbuilding].max(0);nested=(small.values>=1.5)&(small.values>=strength*.55);labels[nested]=nonbuilding[small.indices[nested]];labels[(strength<1.5)|(strength<visible_counts*.15)]=0
# Tiny residual fragments are retained as environment, not asserted as objects.
counts=torch.bincount(labels,minlength=len(cat)+1)
for obj in cat:
 if counts[obj['id']]<50:labels[labels==obj['id']]=0
assigned=labels.cpu().numpy().astype(np.int32);building_ids=[o['id'] for o in cat if o['label']=='building'];building_names={o['id']:o['name'] for o in cat if o['label']=='building'};parents={}
for obj in cat:
 if obj['label'] not in ['door','pillar']:continue
 ids=torch.where(labels==obj['id'])[0]
 if not len(ids) or not building_ids:continue
 scores=votes[building_ids][:,ids].sum(1);winner=int(scores.argmax());ratio=float(scores[winner]/scores.sum().clamp_min(1));own=float(votes[obj['id'],ids].sum())
 if ratio>=.6 and float(scores[winner])>=own*.3:parents[obj['name']]=dict(name=building_names[building_ids[winner]],overlap_vote_fraction=ratio)
backup=r/'voted_partition';backup.mkdir(exist_ok=True)
for name in ['partition.json','gaussian_object_ids.npy']:
 if (r/name).exists() and not (backup/name).exists():shutil.copy2(r/name,backup/name)
np.save(r/'gaussian_object_ids.npy',assigned);np.save(r/'exact_visible_counts.npy',visible_counts.cpu().numpy().astype(np.uint16));np.save(r/'exact_best_votes.npy',strength.cpu().numpy().astype(np.float32));del votes
source=PlyData.read(r/'trained_full.ply')['vertex'].data;xyz=np.column_stack([source[k] for k in ['x','y','z']]);rows=[dict(id=0,name='Environment',label='environment',members=[],observations=[])]+cat;result=[]
for obj in rows:
 ids=np.flatnonzero(assigned==obj['id'])
 if not len(ids):continue
 folder=r/'objects_exact'/obj['name'];folder.mkdir(parents=True,exist_ok=True);np.save(folder/'source_gaussian_ids.npy',ids);PlyData([PlyElement.describe(source[ids],'vertex')],text=False,byte_order='<').write(folder/'gaussians.ply')
 row={k:v for k,v in obj.items() if k!='observations'};row.update(gaussians=len(ids),center=np.median(xyz[ids],axis=0).tolist(),ply=str((folder/'gaussians.ply').relative_to(r)),source_ids=str((folder/'source_gaussian_ids.npy').relative_to(r)),status='exact_multiview_candidate_visual_review_pending')
 if obj['name'] in parents:row['parent_object']=parents[obj['name']]['name'];row['parent_evidence']=parents[obj['name']]['overlap_vote_fraction']
 if obj['observations']:
  def quality(o):
   x0,y0,x1,y1=o['bbox'];border=x0<=2 or y0<=2 or x1>=830 or y1>=478;return o['score']*np.sqrt(o['pixels'])*(.2 if border else 1.)
  front=max(obj['observations'],key=quality);row['review_view']=front['view'];row['review_detection_index']=front['detection_index'];data=np.load(stage/'detections'/f"{front['view']}.npz");h,w=map(int,data['shape']);mask=np.unpackbits(data['masks_packed'][front['detection_index']],count=h*w).reshape(h,w);rgb=np.array(Image.open(r/'rendered_scene/gs_data/images'/f"{front['view']}.png").convert('RGB'));rgba=np.dstack([rgb,mask*255]);x0,y0,x1,y1=front['bbox'];pad=max(4,int(max(x1-x0,y1-y0)*.05));Image.fromarray(rgba).crop((max(0,x0-pad),max(0,y0-pad),min(w,x1+pad),min(h,y1+pad))).save(folder/'reference.png');(folder/'observations.json').write_text(json.dumps(obj['observations'],indent=2))
 result.append(row)
valid_names={o['name'] for o in result}
for row in result:
 if row.get('parent_object') not in valid_names:row.pop('parent_object',None);row.pop('parent_evidence',None)
report=dict(source_gaussians=n,assigned_gaussians=int((assigned>0).sum()),environment_gaussians=int((assigned==0).sum()),objects=result,source_views=len(manifest['views']),partition_policy='SAM3 on actual trained Gaussian renders. Exact per-pixel alpha/transmittance support; direct Gaussian-ID multiview tracking; same-category duplicate merge; per-Gaussian vote consensus. Original attributes are untouched. Door/pillar parent links use shared building-mask evidence.',status='visual_and_edit_validation_pending');(r/'partition.json').write_text(json.dumps(report,indent=2));print('EXACT_PARTITION_COMPLETE',len(result),report['assigned_gaussians'],report['environment_gaussians'],flush=True)
