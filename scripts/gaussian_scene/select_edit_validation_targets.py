"""Choose visible independent and composite objects for real Blender edit tests."""
import json
from pathlib import Path
import numpy as np,torch
from gsplat.rendering import rasterization
from raster_contributions import contributions
r=(Path(__file__).resolve().parents[2]/'outputs/images/A_MARCEAU/gaussian_editable');manifest=json.loads((r/'partition.json').read_text());ckpt=torch.load(r.parent/'gs/ckpts/ckpt_7999_rank0.pt',map_location='cuda',weights_only=False);s=ckpt['splats'];cam=json.loads((r/'viewer_startup_camera.json').read_text());K=np.array(cam['K']);K[:2]*=.5;pose=np.array(cam['camera_pose']);labels=torch.as_tensor(np.load(r/'gaussian_object_ids.npy'),device='cuda')
with torch.inference_mode():
 _,_,meta=rasterization(s['means'],torch.nn.functional.normalize(s['quats'],dim=-1),s['scales'].exp(),s['opacities'].sigmoid().reshape(-1),s['sh0'][:,0]*.28209479177387814+.5,torch.tensor(np.linalg.inv(pose),device='cuda',dtype=torch.float32)[None],torch.tensor(K,device='cuda',dtype=torch.float32)[None],416,240,radius_clip=3,packed=False);ids,pixels,weights=contributions(meta);mass=torch.bincount(labels[ids],weights,minlength=max(o['id'] for o in manifest['objects'])+1).cpu().numpy()
parents={o.get('parent_object') for o in manifest['objects']};independent=[o for o in manifest['objects'] if o['id'] and o['name'] not in parents and not o.get('parent_object') and o['label'] in ['tree','chair']];unit=max(independent,key=lambda o:mass[o['id']]);composite=max([o for o in manifest['objects'] if o['name'] in parents and not o.get('parent_object')],key=lambda o:mass[o['id']]);report=dict(independent=unit['name'],independent_pixel_weight=float(mass[unit['id']]),assembly=composite['name'],assembly_pixel_weight=float(mass[composite['id']]));(r/'edit_validation_targets.json').write_text(json.dumps(report,indent=2));print('VISIBLE_EDIT_TARGETS',report,flush=True)
