"""Export learned membership as original Gaussian objects, with audited parts."""
import json,shutil
from pathlib import Path
from collections import defaultdict
import numpy as np
from PIL import Image
from plyfile import PlyData,PlyElement
r=(Path(__file__).resolve().parents[2]/'outputs/images/A_MARCEAU/gaussian_editable');stage=r/'rendered_scene/object_scene';cache=r/'rendered_mask_support';catalog=json.loads((r/'rendered_gaussian_instances.json').read_text())['objects'];byid={o['id']:o for o in catalog};labels=np.load(r/'semantic_refinement/gaussian_object_ids.npy');counts=np.bincount(labels,minlength=len(catalog)+1)
for obj in catalog:
 if counts[obj['id']]<50:labels[labels==obj['id']]=0
active=[o for o in catalog if (labels==o['id']).any()];byname={o['name']:o for o in active};building=[o for o in active if o['label']=='building'];building_index={o['id']:i for i,o in enumerate(building)};parent_votes=np.zeros((len(building),len(catalog)+1),np.float64);byview=defaultdict(list)
for obj in active:
 for obs in obj['observations']:byview[obs['view']].append((obj,obs))
best={};support_quality=defaultdict(list)
for view,observations in byview.items():
 data=np.load(cache/f'{view}.npz');visible=data['visible_ids'];visible_counts=np.bincount(labels[visible],minlength=len(catalog)+1)
 for obj,obs in observations:
  ids=data[f"instance_{obs['detection_index']}"];weight=data[f"weight_{obs['detection_index']}"];inside=int((labels[ids]==obj['id']).sum());precision=inside/max(int(visible_counts[obj['id']]),1);recall=inside/max(len(ids),1);f1=2*precision*recall/max(precision+recall,1e-12);x0,y0,x1,y1=obs['bbox'];border=x0<=2 or y0<=2 or x1>=830 or y1>=478;quality=obs['score']*np.sqrt(obs['pixels'])*f1*f1*(.2 if border else 1.);support_quality[obj['name']].append(f1)
  if obj['name'] not in best or quality>best[obj['name']][0]:best[obj['name']]=(quality,obs)
  if obj['id'] in building_index:parent_votes[building_index[obj['id']]]+=np.bincount(labels[ids],weight,minlength=len(catalog)+1)
parents={}
for obj in active:
 if obj['label'] not in ['door','pillar'] or not building:continue
 scores=parent_votes[:,obj['id']];winner=int(scores.argmax());ratio=scores[winner]/max(scores.sum(),1.)
 if ratio>=.6 and scores[winner]>=50:parents[obj['name']]=dict(name=building[winner]['name'],reason='Building-mask overlap on original Gaussian IDs',confidence=float(ratio))
# Reviewed facade pieces share the enclosing building's occupied 3D bounds.
# They stay separate editable child objects; the parent transforms the assembly.
reviewed_parts={'building_0053':'building_0006','building_0135':'building_0100','building_0443':'building_0004','building_1743':'building_0004','building_2292':'building_2016','building_0150':'building_0008','building_1243':'building_0071','tree_1857':'tree_0002','chair_0587':'chair_0016','chair_3536':'chair_0041'}
for child,parent in reviewed_parts.items():
 if child in byname and parent in byname:parents[child]=dict(name=parent,reason='Reviewed facade/roof/connected wing within parent building bounds',confidence=None)
backup=r/'constrained_vote_partition';backup.mkdir(exist_ok=True)
for name in ['partition.json','gaussian_object_ids.npy']:
 if (r/name).exists() and not (backup/name).exists():shutil.copy2(r/name,backup/name)
source=PlyData.read(r/'trained_full.ply')['vertex'].data;xyz=np.column_stack([source[k] for k in ['x','y','z']]);result=[];rows=[dict(id=0,name='Environment',label='environment',members=[],observations=[])]+active
for obj in rows:
 ids=np.flatnonzero(labels==obj['id']);folder=r/'objects_refined'/obj['name'];folder.mkdir(parents=True,exist_ok=True);np.save(folder/'source_gaussian_ids.npy',ids);PlyData([PlyElement.describe(source[ids],'vertex')],text=False,byte_order='<').write(folder/'gaussians.ply');row={k:v for k,v in obj.items() if k!='observations'};row.update(gaussians=len(ids),center=np.median(xyz[ids],axis=0).tolist(),ply=str((folder/'gaussians.ply').relative_to(r)),source_ids=str((folder/'source_gaussian_ids.npy').relative_to(r)),status='render_loss_refined_instance')
 if obj['name'] in parents:row['parent_object']=parents[obj['name']]['name'];row['parent_evidence']=parents[obj['name']]['reason'];row['role']='editable_part'
 else:row['role']='environment' if obj['id']==0 else 'object'
 if obj['observations']:
  front=best[obj['name']][1];row['review_view']=front['view'];row['review_detection_index']=front['detection_index'];row['observation_support_f1_median']=float(np.median(support_quality[obj['name']]));data=np.load(stage/'detections'/f"{front['view']}.npz");h,w=map(int,data['shape']);mask=np.unpackbits(data['masks_packed'][front['detection_index']],count=h*w).reshape(h,w);rgb=np.array(Image.open(r/'rendered_scene/gs_data/images'/f"{front['view']}.png").convert('RGB'));rgba=np.dstack([rgb,mask*255]);x0,y0,x1,y1=front['bbox'];pad=max(4,int(max(x1-x0,y1-y0)*.05));Image.fromarray(rgba).crop((max(0,x0-pad),max(0,y0-pad),min(w,x1+pad),min(h,y1+pad))).save(folder/'reference.png');(folder/'observations.json').write_text(json.dumps(obj['observations'],indent=2))
 result.append(row)
np.save(r/'gaussian_object_ids.npy',labels);report=dict(source_gaussians=len(source),assigned_gaussians=int((labels>0).sum()),environment_gaussians=int((labels==0).sum()),objects=result,root_objects=sum(o['role']=='object' for o in result),editable_parts=sum(o['role']=='editable_part' for o in result),source_views=808,partition_policy='SAM3 on original Gaussian renders; exact opacity-aware correspondence; per-mask clustering with same-view cannot-links; frozen-appearance semantic membership optimization; reviewed building-part hierarchy.',status='final_render_and_edit_validation_pending');(r/'partition.json').write_text(json.dumps(report,indent=2));print('REFINED_EXPORT_COMPLETE',len(result),report['root_objects'],report['editable_parts'],report['assigned_gaussians'],flush=True)
