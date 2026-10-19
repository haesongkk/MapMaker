import numpy as np
import pytest
import trimesh
from mapmaker.scene_run import write,sha
from scripts.compare_geometry_revisions import compare


@pytest.mark.parametrize('local_shift',[0.,.2])
def test_global_frame_change_is_separate_from_actual_object_motion(tmp_path,local_shift):
    paths=[]
    for index in range(2):
        path=tmp_path/str(index);path.mkdir();paths.append(path)
        common=np.eye(4)
        if index:
            common=trimesh.transformations.rotation_matrix(.4,[1,0,1])
            common[:3,3]=[1,2,3]
        local=np.eye(4);local[:3,3]=[.5+index*local_shift,.2,4]
        mesh=trimesh.creation.box()
        mesh.export(path/'object.glb')
        scene=trimesh.Scene();scene.add_geometry(mesh,node_name='object',transform=common@local)
        scene.export(path/'scene.glb')
        for name in ('input.png','points.npz','mask.png'):
            (path/name).write_bytes(name.encode())
        write(path/'scene_metadata.json',dict(input_image='input.png',input_sha256=sha(path/'input.png'),
            pointmap=dict(asset='points.npz',sha256=sha(path/'points.npz')),
            objects=[dict(id='object',status='generated',asset='object.glb',mask='mask.png',mask_sha256=sha(path/'mask.png'),
                transform=dict(matrix=(common@local).tolist()))],
            placement=dict(scene_sha256=sha(path/'scene.glb'),common_transform=common.tolist(),
                contacts=dict(changes=[])),structure=dict(surfaces=[])))
    report=compare(paths[1],paths[0])
    assert report['global_transform_changed']
    assert report['changed_transforms']==['object']
    assert report['changed_camera_frame_transforms']==(['object'] if local_shift else [])
    assert not report['quality_gate_passed']
    # A matching metadata hash is insufficient if the underlying artifact was changed.
    for filename in ('input.png', 'points.npz', 'mask.png'):
        original=(paths[1]/filename).read_bytes()
        (paths[1]/filename).write_bytes(b'changed')
        with pytest.raises(AssertionError):
            compare(paths[1],paths[0])
        (paths[1]/filename).write_bytes(original)
