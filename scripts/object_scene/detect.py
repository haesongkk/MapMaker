"""Detect objects.json concepts in every calibrated RGB output, with resume support."""
import argparse,hashlib,json,os,time
from pathlib import Path
import numpy as np
from PIL import Image
import torch
from transformers import Sam3Model,Sam3Processor
from transformers.utils import logging
from hyworld2.worldgen.src.sam3_cache import infer_with_vision_cache


def main():
 p=argparse.ArgumentParser();p.add_argument('scene',type=Path);p.add_argument('--limit',type=int);a=p.parse_args();scene=a.scene.resolve();out=scene/'object_scene';out.mkdir(exist_ok=True);dest=out/'detections';dest.mkdir(exist_ok=True)
 labels=list(dict.fromkeys(json.loads((scene/'objects.json').read_text())));assert labels and all(isinstance(x,str) and x.strip() for x in labels)
 cameras=json.loads((scene/'gs_data/cameras.json').read_text());views=sorted(k for k,v in cameras.items() if isinstance(v,dict) and 'extrinsic' in v and (scene/'gs_data/images'/f'{k}.png').exists())
 if not views:raise RuntimeError('No calibrated RGB images found; detection cannot be complete')
 config=dict(labels=labels,model='facebook/sam3',score_threshold=.5,mask_threshold=.5,min_mask_pixels=64,views=views,cameras_sha256=hashlib.sha256((scene/'gs_data/cameras.json').read_bytes()).hexdigest(),version=1)
 signature=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest();config['signature']=signature;(out/'detection_manifest.json').write_text(json.dumps(config,indent=2))
 logging.disable_progress_bar();model=Sam3Model.from_pretrained('facebook/sam3',local_files_only=True).to('cuda').eval();processor=Sam3Processor.from_pretrained('facebook/sam3',local_files_only=True)
 started=time.monotonic();done=0;total_masks=0
 for vi,name in enumerate(views[:a.limit] if a.limit else views):
  path=scene/'gs_data/images'/f'{name}.png';sha=hashlib.sha256(path.read_bytes()).hexdigest();record_path=dest/f'{name}.json';maskpath=dest/f'{name}.npz'
  if record_path.exists() and maskpath.exists():
   previous=json.loads(record_path.read_text())
   if previous.get('signature')==signature and previous.get('image_sha256')==sha:done+=1;total_masks+=len(previous['instances']);continue
  im=Image.open(path).convert('RGB');cache={};rows=[];bits=[]
  for start in range(0,len(labels),4):
   batch=labels[start:start+4];texts=batch+[batch[-1]]*(4-len(batch));inputs=processor(images=[im]*4,text=texts,return_tensors='pt').to('cuda')
   with torch.inference_mode():
    results=processor.post_process_instance_segmentation(infer_with_vision_cache(model,inputs,cache),threshold=.5,mask_threshold=.5,target_sizes=[im.size[::-1]]*4)
   for label,res in zip(batch,results):
    for mask,score in zip(res['masks'],res['scores']):
     mask=mask.cpu().numpy().astype(bool).reshape(im.height,im.width);count=int(mask.sum())
     if count<64:continue
     yy,xx=np.where(mask);idx=len(rows);rows.append(dict(index=idx,label=label,score=float(score),pixels=count,bbox=[int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)]));bits.append(np.packbits(mask.ravel()))
  packed=np.stack(bits) if bits else np.empty((0,(im.width*im.height+7)//8),np.uint8)
  temp=maskpath.with_suffix('.tmp.npz');np.savez_compressed(temp,masks_packed=packed,shape=np.array([im.height,im.width]));os.replace(temp,maskpath)
  record=dict(view=name,signature=signature,image_sha256=sha,image=str(path),depth_available=(scene/'gs_data/depths'/f'{name}.png').exists(),instances=rows)
  temp=record_path.with_suffix('.tmp.json');temp.write_text(json.dumps(record,indent=2));os.replace(temp,record_path);done+=1;total_masks+=len(rows)
  status=dict(completed_views=done,total_views=len(views),instances=total_masks,last_view=name,seconds=time.monotonic()-started,complete=done==len(views));(out/'detection_status.json').write_text(json.dumps(status,indent=2));print(json.dumps(status),flush=True)
 status=dict(completed_views=done,total_views=len(views),instances=total_masks,complete=done==len(views));(out/'detection_status.json').write_text(json.dumps(status,indent=2));print('DETECTION_RESULT',json.dumps(status),flush=True)

if __name__=='__main__':main()
