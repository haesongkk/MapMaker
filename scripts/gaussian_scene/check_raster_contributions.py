"""Validate extracted weights against the real renderer, including occlusion."""
import json
from pathlib import Path
import torch,numpy as np
from gsplat.rendering import rasterization
from raster_contributions import contributions
r=(Path(__file__).resolve().parents[2]/'outputs/images/A_MARCEAU/gaussian_editable');c=torch.load(r.parent/'gs/ckpts/ckpt_7999_rank0.pt',map_location='cuda',weights_only=False);s=c['splats'];cam=json.loads((r/'viewer_startup_camera.json').read_text());K=np.array(cam['K']);K[:2]*=.5;pose=np.array(cam['camera_pose']);colors=s['sh0'][:,0]*.28209479177387814+.5
with torch.inference_mode():
 rgb,alpha,meta=rasterization(s['means'],torch.nn.functional.normalize(s['quats'],dim=-1),s['scales'].exp(),s['opacities'].sigmoid().reshape(-1),colors,torch.tensor(np.linalg.inv(pose),device='cuda',dtype=torch.float32)[None],torch.tensor(K,device='cuda',dtype=torch.float32)[None],416,240,radius_clip=3,render_mode='RGB',packed=False)
 ids,pixels,weights=contributions(meta);assert bool((pixels[1:]>=pixels[:-1]).all());aa=torch.bincount(pixels,weights,minlength=416*240).reshape(240,416);rr=torch.stack([torch.bincount(pixels,weights*colors[ids,i],minlength=416*240) for i in range(3)],dim=-1).reshape(240,416,3);alpha_error=float((aa-alpha[0,...,0]).abs().max());rgb_error=float((rr-rgb[0]).abs().max());assert alpha_error<2e-4,(alpha_error,rgb_error);assert rgb_error<2e-4,(alpha_error,rgb_error);report=dict(intersections=len(ids),contributing_gaussians=len(ids.unique()),max_alpha_error=alpha_error,max_rgb_error=rgb_error,passed=True);(r/'contribution_validation.json').write_text(json.dumps(report,indent=2));print('EXACT_CONTRIBUTIONS_PASS',report,flush=True)
