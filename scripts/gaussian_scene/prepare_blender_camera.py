"""Save and render the exact initial webviewer camera for Blender parity."""
import json
from pathlib import Path
import torch,numpy as np
from PIL import Image
from gsplat.rendering import rasterization
r=(Path(__file__).resolve().parents[2]/'outputs/images/A_MARCEAU/gaussian_editable');c=torch.load(r.parent/'gs/ckpts/ckpt_7999_rank0.pt',map_location='cuda',weights_only=False);s=c['splats'];position=np.asarray(c['center_point']);up=np.asarray(c['up_direction']);forward=np.asarray(c['facing_direction'])-position;forward/=np.linalg.norm(forward);right=np.cross(forward,up);right/=np.linalg.norm(right);down=np.cross(forward,right);pose=np.eye(4);pose[:3,:3]=np.column_stack([right,down,forward]);pose[:3,3]=position;focal=480/(2*np.tan(np.deg2rad(35)));camera=dict(camera_pose=pose.tolist(),K=[[float(focal),0,416],[0,float(focal),240],[0,0,1]],width=832,height=480,fov_degrees=70,source='Webviewer reset_cameras');(r/'viewer_startup_camera.json').write_text(json.dumps(camera,indent=2));pose=np.array(camera['camera_pose']);K=np.array(camera['K']);w,h=camera['width'],camera['height']
with torch.inference_mode():rgb,alpha,_=rasterization(s['means'],torch.nn.functional.normalize(s['quats'],dim=-1),s['scales'].exp(),s['opacities'].sigmoid().reshape(-1),s['sh0'][:,0]*.28209479177387814+.5,torch.tensor(np.linalg.inv(pose),device='cuda',dtype=torch.float32)[None],torch.tensor(K,device='cuda',dtype=torch.float32)[None],w,h,radius_clip=3,render_mode='RGB')
arr=rgb[0].cpu().numpy();np.save(r/'viewer_startup_reference.npy',arr);Image.fromarray((arr.clip(0,1)*255).round().astype('uint8')).save(r/'viewer_startup_reference.png')
