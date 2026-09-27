from pathlib import Path
import os, json, time

os.environ["LIDRA_SKIP_INIT"] = "true"
import torch
from sam3d_objects.model.backbone.dit.embedder.dino import Dino

start = time.monotonic()
model = Dino(dino_model="dinov2_vitl14_reg", input_size=518).eval().cuda()
assert model.backbone.num_register_tokens == 4
with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
    output = model(torch.zeros(1, 3, 518, 518, device="cuda"))
assert output.is_cuda and torch.isfinite(output).all()
report = {
    "same_sam3d_embedder": True,
    "pretrained": True,
    "model": "dinov2_vitl14_reg",
    "register_tokens": model.backbone.num_register_tokens,
    "output_shape": list(output.shape),
    "finite": True,
    "device": str(output.device),
    "gpu": torch.cuda.get_device_name(0),
    "seconds": time.monotonic() - start,
}
p = Path(__file__).resolve().parents[1] / ".runtime/sam3d-recovery/dino-smoke.json"
p.write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
