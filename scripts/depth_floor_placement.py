"""Fresh derivation from raw SAM3D poses. Never consumes Qwen placement matrices."""
import argparse,json,sys,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import trimesh
from PIL import Image
from scipy.spatial import cKDTree
from mapmaker.staged_placement import load_run,geometry,write_scene,settle_on
from mapmaker.scene_run import sha,write
from mapmaker.scene_vanishing import fit_camera
from mapmaker.depth_floor import estimate_floor,observed_bottom,infer_contacts,projected_support
from mapmaker.pair_support import nearby_contact

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))

def initialize(source,root):
 if root.exists():raise ValueError('Choose a fresh derivation directory')
 meta,objects,mats=load_run(source);root.mkdir(parents=True)
 state=dict(source=str(source.resolve()),source_scene_sha256=sha(source/'scene.glb'),source_metadata_sha256=sha(source/'scene_metadata.json'),
     input_image=str((source/meta['input_image']).resolve()),objects=objects,original_matrices={k:v.tolist() for k,v in mats.items()},
     origin='unmodified_sam3d_pose',object_up_averaging=False,qwen_relations=False)
 write(root/'state.json',state);write_scene(source/'scene.glb',root/'raw.glb',mats)
 Image.open(source/meta['input_image']).convert('RGB').save(root/'original.png')

def load(root):
 s=read(root/'state.json');data=np.load(root/'pointmap.npz');points=data['points'];h,w=points.shape[:2]
 masks={o['id']:np.array(Image.open(Path(s['source'])/o['mask']).convert('L').resize((w,h),Image.Resampling.NEAREST))>0 for o in s['objects']}
 return s,points,masks

def analyze(root):
 s,points,masks=load(root);mats={k:np.array(v) for k,v in s['original_matrices'].items()}
 camera=fit_camera(points)
 if not camera['accepted']:raise ValueError('Pointmap camera projection inconsistent')
 geo=geometry(s['source'],s['objects'],mats);registration={}
 for oid,(v,f) in geo.items():
  cloud=points[masks[oid]];cloud=cloud[np.isfinite(cloud).all(1)]
  if len(cloud)<30:registration[oid]=dict(accepted=False,reason='insufficient_depth');continue
  cloud=cloud[np.linspace(0,len(cloud)-1,min(len(cloud),512)).astype(int)]
  scale=max(float(np.linalg.norm(np.ptp(cloud,axis=0))),1e-8)
  distance=cKDTree(v).query(cloud)[0]
  registration[oid]=dict(observed_depth=float(np.median(cloud[:,2])),mesh_depth=float(np.median(v[:,2])),
       median_surface_vertex_distance=float(np.median(distance)),normalized_median=float(np.median(distance)/scale),
       normalized_p90=float(np.quantile(distance,.9)/scale),accepted=bool(np.median(distance)/scale<.15),
       method='visible_observation_to_mesh_vertex_distance_proxy')
 excluded=np.logical_or.reduce(list(masks.values()));common,plane=estimate_floor(points,excluded)
 world=trimesh.transform_points(points.reshape(-1,3),common).reshape(points.shape)
 updated={k:common@m for k,m in mats.items()};report=write_scene(Path(s['source'])/'scene.glb',root/'floor-aligned.glb',updated)
 report.update(plane=plane,camera=camera,registration=registration,observed_objects={k:observed_bottom(world,m) for k,m in masks.items()},
     common_transform=common.tolist(),object_up_averaging=False)
 write(root/'floor-report.json',report);write(root/'floor-matrices.json',{k:v.tolist() for k,v in updated.items()})
 np.savez_compressed(root/'world-pointmap.npz',points=world.astype(np.float32))
 print(root.name,json.dumps(dict(plane=plane['selected'],rotation=plane['rotation_degrees'],registration=registration)),flush=True)

def correct(root):
 s,_,masks=load(root);world=np.load(root/'world-pointmap.npz')['points'];floor=read(root/'floor-report.json');tol=floor['plane']['tolerance']
 rows=infer_contacts(world,masks,tol)
 matrices={k:np.array(v) for k,v in read(root/'floor-matrices.json').items()};base={k:v.copy() for k,v in matrices.items()}
 geo=geometry(s['source'],s['objects'],matrices)
 for key,row in rows.items():
  if row['target'] is None:
   target,evidence=projected_support(geo[key][0],world,masks,key,np.linalg.inv(floor['common_transform']),np.array(floor['camera']['matrix']),tol,rows)
   row['projected_foot_evidence']=evidence
   if target:row.update(target=target,kind='surface',contact_source='projected_mesh_feet_checked_against_observed_depth')
 # Occluded contact: propose finite mesh support, then require depth consistency
 # before applying. This never promotes an elevated object to the room floor.
 for key,row in rows.items():
  if row['target'] is not None:continue
  v,_=geo[key];lo,hi=v.min(0),v.max(0);limit=max(np.linalg.norm(hi-lo)*.25,3*tol);proposals=[]
  for parent,other in rows.items():
   if parent==key or other['observed_bottom']>=row['observed_bottom']-tol*.25:continue
   parent_observed=world[masks[parent]];parent_observed=parent_observed[np.isfinite(parent_observed).all(1)]
   observed_top=float(np.quantile(parent_observed[:,1],.995))
   if row['observed_bottom']-observed_top>4*tol:continue
   pv,pf=geo[parent];pl,ph=pv.min(0),pv.max(0)
   if np.any(np.minimum(hi,ph)[[0,2]]<=np.maximum(lo,pl)[[0,2]]):continue
   if lo[1]>ph[1]+limit or hi[1]<pl[1]:continue
   correction,e=settle_on(v,pv[pf],tol*.25)
   if correction is None and e['reason']=='insufficient_support_footprint':
    delta,e=nearby_contact(v,pv[pf],tol*.25)
    if delta is not None:correction=float(delta[1])
   if correction is not None and abs(correction)<=limit:proposals.append(dict(target=parent,dy=correction,**{k:v for k,v in e.items() if k!='dy'}))
  proposals.sort(key=lambda r:abs(r['dy']))
  row['occluded_mesh_support_proposals']=proposals
  if proposals and (len(proposals)==1 or abs(proposals[0]['dy'])+tol*.5<abs(proposals[1]['dy'])):
   row.update(target=proposals[0]['target'],kind='surface',contact_source='occluded_mesh_support_pending_depth_guard')
 write(root/'observed-contacts.json',rows)
 pending=set(rows);changes=[dict(object_id=k,target=None,applied=False,reason='insufficient_observed_depth',dy=0.,translation=[0.,0.,0.]) for k in matrices if k not in rows];done=set();blocked=set()
 while pending:
  ready=sorted(k for k in pending if rows[k]['target'] not in pending)
  if not ready:
   changes.extend(dict(object_id=k,applied=False,reason='cyclic_contacts') for k in sorted(pending));break
  for key in ready:
   pending.remove(key);row=rows[key];target=row['target'];v,f=geo[key];record=dict(object_id=key,target=target,applied=False)
   if target is None or target in blocked or not floor['registration'][key]['accepted']:
    record['reason']='unresolved_observed_support';changes.append(record);blocked.add(key);continue
   carry=0.;horizontal=np.zeros(3);parent_horizontal=np.zeros(3)
   if target=='floor':dy=-float(v[:,1].min());record['reason']='observed_floor_contact'
   else:
    parent_motion=matrices[target][:3,3]-base[target][:3,3];carry=parent_motion[1];parent_horizontal=parent_motion.copy();parent_horizontal[1]=0;horizontal=parent_horizontal.copy();parent,pf=geo[target]
    # A mesh extending substantially below the visible contact may be inserted,
    # interlocking or occluded; preserve its relative offset instead of snapping its base.
    test=v+parent_motion
    correction,e=settle_on(test,parent[pf],tol*.25)
    if correction is None and e['reason']=='insufficient_support_footprint':
     delta,e=nearby_contact(test,parent[pf],tol*.25)
     if delta is not None:correction=float(delta[1]);horizontal+=np.array([delta[0],0,delta[2]])
    embedded=correction is not None and correction>max(2*tol,row['observed_height']*.12) and v[:,1].min()<row['observed_bottom']-2*tol
    if embedded:
     dy=float(carry);record['reason']='preserve_observed_interlock'
    else:
     record.update(e)
     dy=None if correction is None else float(carry+correction)
     if correction is None and any(c['target']==target and c['contact_fraction']>=.8 for c in row['candidates']):
      dy=float(carry);record['reason']='follow_observed_support_without_contact_snap'
   limit=max(float(np.linalg.norm(np.ptp(v,axis=0)))*.25,tol*3)
   record['parent_carry']=float(carry)
   if dy is None:blocked.add(key)
   elif abs(dy-carry)>limit:record.update(reason='motion_exceeds_depth_budget',requested_dy=dy,limit=limit);blocked.add(key)
   elif float(v[:,1].min()+dy)<-tol:record['reason']='would_cross_observed_floor';blocked.add(key)
   else:
    cloud=world[masks[key]];cloud=cloud[np.isfinite(cloud).all(1)];cloud=cloud[np.linspace(0,len(cloud)-1,min(512,len(cloud))).astype(int)]
    tree=cKDTree(v);before=tree.query(cloud)[0];shift=np.array([0,dy-carry,0])+horizontal-parent_horizontal;after=tree.query(cloud-shift)[0]
    absolute_after=tree.query(cloud-np.array([0,dy,0])-horizontal)[0]
    record['depth_guard']=dict(before_median=float(np.median(before)),after_median=float(np.median(after)),before_p90=float(np.quantile(before,.9)),after_p90=float(np.quantile(after,.9)),absolute_after_median=float(np.median(absolute_after)),frame='parent_carried_observations_for_children_original_observations_for_floor')
    if np.median(after)>np.median(before)+tol or np.quantile(after,.9)>np.quantile(before,.9)+2*tol:
     record.update(reason='would_degrade_observed_depth',requested_dy=dy);blocked.add(key)
    elif abs(dy)<=tol*.1 and np.linalg.norm(horizontal)<=tol*.1:record.update(reason='already_within_contact_tolerance',dy=0.)
    else:
     delta=horizontal+np.array([0,dy,0]);matrices[key][:3,3]+=delta;v+=delta;record.update(applied=True,dy=dy,translation=delta.tolist())
   if not record['applied']:
    if record.get('dy') and 'requested_dy' not in record:record['requested_dy']=record['dy']
    record.update(dy=0.,translation=[0.,0.,0.])
   changes.append(record);done.add(key)
 report=write_scene(Path(s['source'])/'scene.glb',root/'final.glb',matrices);report.update(changes=changes,tolerance=tol,object_up_averaging=False,qwen_relations=False)
 write(root/'final-report.json',report);write(root/'final-matrices.json',{k:v.tolist() for k,v in matrices.items()})
 print(root.name,json.dumps(changes),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['init','analyze','correct']);p.add_argument('root',type=Path);p.add_argument('--source',type=Path);a=p.parse_args()
 if a.action=='init':initialize(a.source,a.root)
 elif a.action=='analyze':analyze(a.root)
 else:correct(a.root)
