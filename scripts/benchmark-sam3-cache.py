"""Compare uncached and cached SAM3 inference on the same image batch."""
import argparse
from pathlib import Path
import time,json
import torch
from PIL import Image
from transformers import Sam3Model,Sam3Processor
from transformers.utils import logging
from hyworld2.worldgen.src.sam3_cache import infer_with_vision_cache
logging.disable_progress_bar()
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--image', type=Path, default=Path('outputs/images/A_MARCEAU/panorama.png'))
parser.add_argument('--output', type=Path, default=Path('outputs/quality-audit/sam-cache-benchmark.json'))
args=parser.parse_args()
p=Sam3Processor.from_pretrained('facebook/sam3',local_files_only=True)
m=Sam3Model.from_pretrained('facebook/sam3',local_files_only=True).to('cuda').eval()
im=Image.open(args.image).convert('RGB')
a=p(images=[im]*4,text=['building','tree','wall','ground'],return_tensors='pt').to('cuda')
cache={}
with torch.inference_mode():
 m(**a);torch.cuda.synchronize()
 t=time.monotonic();original=m(**a);torch.cuda.synchronize();baseline=time.monotonic()-t
 first=infer_with_vision_cache(m,a,cache);torch.cuda.synchronize()
 t=time.monotonic();cached=infer_with_vision_cache(m,a,cache);torch.cuda.synchronize();duration=time.monotonic()-t
 diffs={key:float((original[key]-cached[key]).abs().max()) for key in ['pred_masks','pred_boxes','pred_logits']}
 assert all(v==0 for v in diffs.values()),diffs
report={'baseline_seconds':baseline,'cached_seconds':duration,'maximum_absolute_difference':diffs,'batch_size':4,'image':str(args.image)}
print(json.dumps(report,indent=2),flush=True)
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(report,indent=2))
