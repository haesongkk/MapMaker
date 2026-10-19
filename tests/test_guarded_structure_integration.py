import numpy as np
import pytest
import trimesh
from mapmaker.scene_run import sha
from mapmaker.scene_structure import restore_structure


def test_restore_guards_in_world_frame_independent_of_object_name(tmp_path,monkeypatch):
    def patch(x):
        return trimesh.Trimesh([[x,0,0],[x+1,0,0],[x,0,1],[x+1,0,1]],[[0,1,2],[1,3,2]],process=False)
    baseline=patch(0);candidate=trimesh.util.concatenate([baseline,patch(2)])
    calls=[]
    def fit(*args,**kwargs):
        mode=kwargs['occlusion_method'];calls.append(mode)
        mesh=baseline if mode=='local_plane_evidence' else candidate
        return [(mesh.copy(),dict(kind='floor',normal=[0.,1.,0.],point=[0.,0.,0.],
            fully_observed_triangles=2,inferred_pixels=0 if mode=='local_plane_evidence' else 4))],{}
    monkeypatch.setattr('mapmaker.scene_structure.fit_surfaces',fit)
    np.savez(tmp_path/'points.npz',points=np.ones((4,4,3)))
    placement=dict(common_transform=np.eye(4),orientation_evidence=dict(accepted=True),contact_tolerance=.001)
    results=[]
    for name in ('arbitrary_label',''):
        scene=trimesh.Scene();body=trimesh.creation.box(extents=[.4,1,.4])
        scene.add_geometry(body,node_name='body',transform=trimesh.transformations.translation_matrix([2.4,0,.4]))
        meta=dict(pointmap=dict(asset='points.npz',sha256=sha(tmp_path/'points.npz'),frame='sam3d_pytorch3d_camera'),
            objects=[dict(id='body',status='generated',name=name)])
        result=restore_structure(tmp_path,scene,meta,placement,include_unclaimed=False,
            proposal_method='reference_stable_normals',occlusion_method='guarded_enclosed_plane_evidence')
        surface=result['surfaces'][0]
        assert surface['extension_guard']['rejected_added_triangles']==2
        assert surface['extension_guard']['baseline_preserved']
        assert surface['inferred_pixels'] is None and surface['proposed_inferred_pixels']==4
        assert surface['occlusion_extended_triangles']==0
        results.append(surface)
    assert results[0]==results[1]
    assert calls==['local_plane_evidence','enclosed_plane_evidence']*2
    with pytest.raises(ValueError,match='missing from extension guard scene'):
        restore_structure(tmp_path,trimesh.Scene(),meta,placement,include_unclaimed=False,
            proposal_method='reference_stable_normals',occlusion_method='guarded_enclosed_plane_evidence')
