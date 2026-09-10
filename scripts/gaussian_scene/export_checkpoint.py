"""Export every trained Gaussian without filtering, decimation, or quantization."""
import json,hashlib
from pathlib import Path
import numpy as np,torch
from plyfile import PlyData,PlyElement
from gsplat.rendering import rasterization
from PIL import Image
scene=(Path(__file__).resolve().parents[2]/'outputs/images/A_MARCEAU');out=scene/'gaussian_editable';out.mkdir(parents=True,exist_ok=True);ckpt=torch.load(scene/'gs/ckpts/ckpt_7999_rank0.pt',map_location='cpu',weights_only=False);s=ckpt['splats'];n=len(s['means']);fields={}
for i,k in enumerate(['x','y','z']):fields[k]=s['means'][:,i].numpy()
for i in range(3):fields[f'f_dc_{i}']=s['sh0'][:,0,i].numpy()
rest=s['shN'].numpy().transpose(0,2,1).reshape(n,-1)
for i in range(rest.shape[1]):fields[f'f_rest_{i}']=rest[:,i]
fields['opacity']=s['opacities'].numpy().reshape(-1)
for i in range(3):fields[f'scale_{i}']=s['scales'][:,i].numpy()
for i in range(4):fields[f'rot_{i}']=s['quats'][:,i].numpy()
vertices=np.empty(n,dtype=[(k,'<f4') for k in fields])
for k,v in fields.items():vertices[k]=v
PlyData([PlyElement.describe(vertices,'vertex')],text=False,byte_order='<').write(out/'trained_full.ply');loaded=PlyData.read(out/'trained_full.ply')['vertex'];assert all(np.array_equal(loaded[k],v) for k,v in fields.items());print('FULL_GAUSSIANS',n,flush=True)
T=np.array(ckpt['transform']);scale=np.cbrt(np.linalg.det(T[:3,:3]));cameras=json.loads((scene/'gs_data/cameras.json').read_text());v='reconstruct_2-traj1_000003';pose=T@np.linalg.inv(np.array(cameras[v]['extrinsic']));pose[:3,:3]/=scale;K=np.array(cameras[v]['intrinsic']);data={k:t.cuda() for k,t in s.items()};colors=torch.cat([data['sh0'],data['shN']],1);degree=int(np.sqrt(colors.shape[1])-1)
for size in [(.5,416,240),(1.,832,480)]:
 factor,w,h=size;kk=K.copy();kk[:2]*=factor
 with torch.inference_mode():rgb,alpha,_=rasterization(data['means'],torch.nn.functional.normalize(data['quats'],dim=-1),data['scales'].exp(),data['opacities'].sigmoid().reshape(-1),colors,torch.tensor(np.linalg.inv(pose),dtype=torch.float32,device='cuda')[None],torch.tensor(kk,dtype=torch.float32,device='cuda')[None],w,h,sh_degree=degree,radius_clip=3,backgrounds=torch.zeros(3,device='cuda'),render_mode='RGB')
 arr=rgb[0].cpu().numpy();np.save(out/f'reference_{w}.npy',arr);Image.fromarray((np.clip(arr,0,1)*255).round().astype(np.uint8)).save(out/f'reference_{w}.png')
(out/'source_manifest.json').write_text(json.dumps(dict(gaussians=n,source='gs/ckpts/ckpt_7999_rank0.pt',attributes_bitwise_equal=True,reference_view=v,sh_degree=degree,camera_pose=pose.tolist(),K=K.tolist()),indent=2))
