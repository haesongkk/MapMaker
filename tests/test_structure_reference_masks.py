import numpy as np
import pytest
import trimesh
from PIL import Image
from mapmaker.scene_structure import fit_surfaces,restore_structure
from mapmaker.scene_run import sha


def test_restore_uses_verified_original_mask_for_fit_and_current_mask_for_mesh(tmp_path):
    y,x=np.mgrid[:70,:80];points=np.stack([(x-40)/30,np.full_like(x,-1,dtype=float),1+y/30],-1)
    points[...,1]+=.001*np.sin(x*.1)
    original=np.zeros(x.shape,np.uint8);current=original.copy();current[25:45,30:50]=255
    Image.fromarray(original).save(tmp_path/'original.png');Image.fromarray(current).save(tmp_path/'current.png')
    np.savez(tmp_path/'points.npz',points=points)
    meta=dict(pointmap=dict(asset='points.npz',sha256=sha(tmp_path/'points.npz'),frame='sam3d_pytorch3d_camera'),
        objects=[dict(status='generated',mask='current.png',mask_sha256=sha(tmp_path/'current.png'),
            mask_expansion=dict(original_mask='original.png',original_sha256=sha(tmp_path/'original.png')))])
    placement=dict(common_transform=np.eye(4),orientation_evidence=dict(accepted=True))
    baseline,_=fit_surfaces(points,original>0,np.eye(4),proposal_method='stable_normals')
    scene=trimesh.Scene();result=restore_structure(tmp_path,scene,meta,placement,include_unclaimed=False,proposal_method='reference_stable_normals')
    assert len(result['surfaces'])==1
    for key in ('normal','point'):np.testing.assert_array_equal(result['surfaces'][0][key],baseline[0][1][key])
    assert sum(len(m.faces) for m in scene.geometry.values())<len(baseline[0][0].faces)
    (tmp_path/'original.png').write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='Reference mask provenance'):
        restore_structure(tmp_path,trimesh.Scene(),meta,placement,proposal_method='reference_stable_normals')
