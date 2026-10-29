"""Refine a completed depth-floor experiment into a fresh output directory."""
import sys,json,shutil
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapmaker.staged_placement import geometry,write_scene
from mapmaker.group_placement import refine_groups
from mapmaker.scene_run import write
from mapmaker.scene_structure import observed_normals
from PIL import Image

def read(p):return json.loads(p.read_text(encoding='utf8'))
def run(source,dest,verify=False):
 if dest.exists() and not verify:raise ValueError('Output directory already exists')
 if not verify:
  dest.mkdir(parents=True)
  for name in ['state.json','raw.glb','original.png','pointmap.npz','depth-provenance.json','floor-aligned.glb','floor-report.json','floor-matrices.json','world-pointmap.npz','comparison-camera.json','observed-contacts.json']:
   shutil.copy2(source/name,dest/name)
  shutil.copy2(source/'final.glb',dest/'previous.glb')
 s=read(source/'state.json');floor=read(source/'floor-report.json');base={k:np.array(v) for k,v in read(source/'floor-matrices.json').items()}
 geo=geometry(s['source'],s['objects'],base);proposed={r['object_id']:r for r in read(source/'final-report.json')['changes']}
 for k in base:
  proposed.setdefault(k,dict(applied=False,target=None,translation=[0,0,0]))
 world=np.load(source/'world-pointmap.npz')['points'];valid=np.isfinite(world).all(-1)
 normals,reliable=observed_normals(world,valid);horizontal=valid&reliable&(abs(normals[...,1])>.75)
 surfaces={}
 for obj in s['objects']:
  mask=np.array(Image.open(Path(s['source'])/obj['mask']).convert('L').resize((world.shape[1],world.shape[0]),Image.Resampling.NEAREST))>0
  surfaces[obj['id']]=world[horizontal&~mask]
 delta,details=refine_groups(geo,proposed,read(source/'observed-contacts.json'),floor['plane']['tolerance'],surfaces)
 matrices={k:m.copy() for k,m in base.items()}
 for k,d in delta.items():matrices[k][:3,3]+=d
 if verify:
  existing=read(dest/'final-matrices.json')
  for k,m in matrices.items():assert np.allclose(m,existing[k]),'Existing output differs from current solver'
  report=read(dest/'group-report.json')
 else:report=write_scene(Path(s['source'])/'scene.glb',dest/'final.glb',matrices)
 report.update(details,tolerance=floor['plane']['tolerance'],object_up_averaging=False,qwen_relations=False)
 write(dest/'group-report.json',report);write(dest/'final-matrices.json',{k:v.tolist() for k,v in matrices.items()})
 print(source.name,json.dumps(details['decisions']),flush=True)

if __name__=='__main__':run(Path(sys.argv[1]),Path(sys.argv[2]))
