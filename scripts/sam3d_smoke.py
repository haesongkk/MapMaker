"""Import through the successful official entrypoint, using only the persistent runtime."""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
repo = Path(os.environ['SAM3D_REPO'])
sys.path.insert(0, str(repo / 'notebook'))
# The official notebook entrypoint sets LIDRA_SKIP_INIT before importing the package.
from inference import Inference, load_image, make_scene
import sam3d_objects
import torch
import gsplat
from pytorch3d import _C

assert torch.cuda.is_available()
assert not any(p.startswith('/dev/shm/') for p in sys.path)
site = ROOT / '.venv-sam3d/lib/python3.11/site-packages'
assert Path(torch.__file__).resolve().is_relative_to(site)
assert Path(_C.__file__).resolve().is_relative_to(site)
native = list((site / 'pytorch3d').glob('*.so')) + list((site / 'gsplat').glob('*.so'))
paths = {}
for p in native:
    text = subprocess.check_output(['readelf', '-d', str(p)], text=True)
    search_paths = [line.strip() for line in text.splitlines() if '(RPATH)' in line or '(RUNPATH)' in line]
    assert all('/dev/shm/' not in line and '/tmp/' not in line for line in search_paths), search_paths
    paths[str(p)] = search_paths
report = {'python': sys.version, 'torch': torch.__version__, 'cuda': torch.version.cuda,
          'gpu': torch.cuda.get_device_name(0), 'official_inference_import': True,
          'sam3d_source': sam3d_objects.__file__, 'torch_path': torch.__file__,
          'pytorch3d_native': _C.__file__, 'native_runtime_search_paths': paths,
          'memory_scratch_on_python_path': False}
(ROOT / '.runtime/sam3d-recovery/official-smoke.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
