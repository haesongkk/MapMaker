"""Complete observed missing supports, then solve actual finite surface contact."""
import json,sys,shutil,struct
from pathlib import Path
import numpy as np
import trimesh
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapmaker.depth_attachment import recover_attachment,surface_mesh,join_body,settle_rigid,fit_attachment_contact
from mapmaker.scene_geometry import support_translation
from mapmaker.pair_support import nearby_contact
from mapmaker.staged_placement import geometry,write_scene,node_matrix
from mapmaker.baseline_assembly import read_header
from mapmaker.scene_run import write

def read(p):return json.loads(p.read_text(encoding='utf8'))

def append_patches(source,destination,patches):
 doc,offset,size=read_header(source)
 with source.open('rb') as inp:inp.seek(offset);binary=bytearray(inp.read(size))
 original_length=len(binary)
 def accessor(array,kind,component):
  nonlocal binary
  binary.extend(b'\0'*(-len(binary)%4));start=len(binary);binary.extend(array.tobytes())
  view=len(doc['bufferViews']);doc['bufferViews'].append(dict(buffer=0,byteOffset=start,byteLength=array.nbytes))
  acc=dict(bufferView=view,componentType=component,count=len(array),type=kind)
  if kind=='VEC3' and array.dtype==np.float32:acc.update(min=array.min(0).tolist(),max=array.max(0).tolist())
  if component==5121:acc['normalized']=True
  idx=len(doc['accessors']);doc['accessors'].append(acc);return idx
 doc.setdefault('extensionsUsed',[])
 if 'KHR_materials_unlit' not in doc['extensionsUsed']:doc['extensionsUsed'].append('KHR_materials_unlit')
 material=len(doc.setdefault('materials',[]));doc['materials'].append(dict(name='Observed RGB-D surface',doubleSided=True,pbrMetallicRoughness=dict(metallicFactor=0,roughnessFactor=1),extensions={'KHR_materials_unlit':{}}))
 for key,v,f,color in patches:
  roots=[i for i,n in enumerate(doc['nodes']) if n.get('name')==key]
  if len(roots)!=1:raise ValueError('Attachment requires one object root')
  owner=roots[0];v=trimesh.transform_points(v,np.linalg.inv(node_matrix(doc['nodes'][owner])))
  rgb=color.astype(float)/255.;linear=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
  position=accessor(v.astype('<f4'),'VEC3',5126);colors=accessor(linear.astype('<f4'),'VEC3',5126);faces=accessor(f.astype('<u4').reshape(-1),'SCALAR',5125)
  mesh=len(doc['meshes']);doc['meshes'].append(dict(name=key+'_observed_connection',primitives=[dict(attributes=dict(POSITION=position,COLOR_0=colors),indices=faces,material=material)]))
  node=len(doc['nodes']);doc['nodes'].append(dict(name=key+'_observed_connection',mesh=mesh))
  doc['nodes'][owner].setdefault('children',[]).append(node)
 binary.extend(b'\0'*(-len(binary)%4));doc['buffers'][0]['byteLength']=len(binary)
 payload=json.dumps(doc,separators=(',',':')).encode();payload+=b' '*(-len(payload)%4)
 with destination.open('wb') as out:
  out.write(struct.pack('<4sII',b'glTF',2,28+len(payload)+len(binary)));out.write(struct.pack('<II',len(payload),0x4e4f534a));out.write(payload);out.write(struct.pack('<II',len(binary),0x004e4942));out.write(binary)
 return dict(original_binary_prefix_bytes=original_length,appended_bytes=len(binary)-original_length)

def run(source,dest):
 if dest.exists():raise ValueError('Choose a fresh output directory')
 dest.mkdir(parents=True)
 for name in ['state.json','original.png','floor-report.json','floor-matrices.json','world-pointmap.npz','comparison-camera.json']:
  shutil.copy2(source/name,dest/name)
 shutil.copy2(source/'final.glb',dest/'previous.glb')
 s=read(source/'state.json');report=read(source/'group-report.json');tol=report['tolerance'];world=np.load(source/'world-pointmap.npz')['points']
 base={k:np.array(v) for k,v in read(source/'floor-matrices.json').items()};current={k:np.array(v) for k,v in read(source/'final-matrices.json').items()}
 geo=geometry(s['source'],s['objects'],base);colors=np.array(Image.open(source/'original.png').convert('RGB').resize((world.shape[1],world.shape[0])))
 masks={o['id']:np.array(Image.open(Path(s['source'])/o['mask']).convert('L').resize((world.shape[1],world.shape[0]),Image.Resampling.NEAREST))>0 for o in s['objects']}
 patches=[];results={}
 for key,decision in report['decisions'].items():
  if decision['reason']!='carry_mesh_dependency_preserve_gap' or decision.get('observed_intermediate_surface_points',0):continue
  parent=decision['parent'];gap=decision['evidence']['gap'];v,f=geo[key];pv,pf=geo[parent]
  other=np.logical_or.reduce([m for k,m in masks.items() if k!=key])
  support_pixels=masks[parent]&np.isfinite(world).all(-1)&(abs(world[...,1]-(v[:,1].min()-gap))<tol)
  parent_color=np.median(colors[support_pixels],axis=0) if support_pixels.sum()>=30 else None
  mask,e=recover_attachment(v,world,masks[key],other,gap,tol,colors,parent_color);results[key]=dict(recovery=e,applied=False)
  if mask is None:continue
  patch_v,patch_f,patch_c=surface_mesh(world,colors,mask,tol)
  if not len(patch_f):results[key]['reason']='no_continuous_surface';continue
  patch_v,join=join_body(patch_v,v,f,tol);results[key]['body_registration']=join
  if patch_v is None:continue
  combined=np.concatenate([v,patch_v])
  body_mesh=trimesh.Trimesh(v,f,process=False)
  center=body_mesh.center_mass if body_mesh.is_watertight and abs(body_mesh.volume)>1e-12 else body_mesh.centroid
  results[key]['support_center']=dict(point=center.tolist(),method='uniform_density_body_volume_centroid' if body_mesh.is_watertight else 'body_surface_centroid',limitation='Estimated body center; attachment mass and true material densities unknown.')
  fitted,adjustment,contact=fit_attachment_contact(patch_v,v,f,pv[pf],tol,center)
  if fitted is not None:patch_v=fitted
  results[key]['contact']=contact
  if adjustment is None:continue
  # Parent's solved motion is shared; the contact correction acts on the body
  # and recovered connection together. Apply to existing dependent descendants.
  parent_shift=current[parent][:3,3]-base[parent][:3,3];solved=adjustment.copy();solved[:3,3]+=parent_shift
  updated=solved@base[key];change=updated@np.linalg.inv(current[key]);current[key]=updated
  descendants=[];queue=[key]
  while queue:
   owner=queue.pop()
   for child,p in report['edges'].items():
    if p==owner and child not in descendants:descendants.append(child);queue.append(child);current[child]=change@current[child]
  for i,(child,pv0,pf0,pc0) in enumerate(patches):
   if child in descendants:patches[i]=(child,trimesh.transform_points(pv0,change),pf0,pc0)
  finished=trimesh.transform_points(patch_v,solved);patches.append((key,finished,patch_f,patch_c))
  np.savez_compressed(dest/(key+'-support.npz'),vertices=finished,faces=patch_f,colors=patch_c)
  Image.fromarray((mask*255).astype('uint8')).save(dest/(key+'-recovered-mask.png'))
  overlay=colors.copy();overlay[mask]=overlay[mask]*.3+np.array([0,180,255])*.7;Image.fromarray(overlay).save(dest/(key+'-evidence.png'))
  results[key].update(applied=True,solved_transform=solved.tolist(),relative_contact_transform=adjustment.tolist(),descendants=descendants,added_vertices=len(patch_v),added_triangles=len(patch_f))
 temp=dest/'placed-original.glb';write_scene(Path(s['source'])/'scene.glb',temp,current)
 binary=append_patches(temp,dest/'final.glb',patches) if patches else (shutil.copy2(temp,dest/'final.glb') and {})
 write(dest/'completion-report.json',dict(objects=results,binary=binary,source=str(source),limitation='Observed surface reconstruction; no unseen back-side completion or global collision guarantee.'))
 write(dest/'final-matrices.json',{k:v.tolist() for k,v in current.items()})
 print(dest.name,json.dumps(results),flush=True)

if __name__=='__main__':run(Path(sys.argv[1]),Path(sys.argv[2]))
