"""Exhaustively verify every exported Gaussian against the original full PLY."""
import json,hashlib
from pathlib import Path
import numpy as np
from plyfile import PlyData
r=(Path(__file__).resolve().parents[2]/'outputs/images/A_MARCEAU/gaussian_editable');manifest=json.loads((r/'partition.json').read_text());source=PlyData.read(r/'trained_full.ply')['vertex'].data;seen=np.zeros(len(source),np.uint8);maximum_origin_roundtrip_error=0.
for obj in manifest['objects']:
 ids=np.load(r/obj.get('source_ids',f"objects/{obj['name']}/source_gaussian_ids.npy"));part=PlyData.read(r/obj['ply'])['vertex'].data
 assert len(part)==obj['gaussians']==len(ids);assert part.dtype==source.dtype
 assert not np.any(seen[ids]);seen[ids]+=1
 expected=np.ascontiguousarray(source[ids]);actual=np.ascontiguousarray(part)
 assert np.array_equal(actual.view(np.uint8),expected.view(np.uint8)),obj['name']
 if obj['id']:
  xyz=np.column_stack([part[k] for k in ['x','y','z']]);center=np.asarray(obj['center'],np.float32);error=np.max(abs((xyz-center)+center-xyz));maximum_origin_roundtrip_error=max(maximum_origin_roundtrip_error,float(error))
assert np.all(seen==1)
report=dict(gaussians=len(source),objects=len(manifest['objects']),raw_attributes_bitwise_equal=True,omitted_gaussians=0,duplicated_gaussians=0,maximum_float32_origin_roundtrip_error=maximum_origin_roundtrip_error,partition_sha256=hashlib.sha256((r/'partition.json').read_bytes()).hexdigest(),scope='Data integrity only; does not certify semantic instance boundaries.');(r/'partition_integrity.json').write_text(json.dumps(report,indent=2));print('PARTITION_INTEGRITY_PASS',report,flush=True)
