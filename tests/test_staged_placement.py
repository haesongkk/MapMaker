import numpy as np
import pytest
import trimesh
from mapmaker.staged_placement import mean_up, floor_align, write_scene, settle_on
from mapmaker.baseline_assembly import assemble_streamed,read_header


def test_all_objects_participate_in_normalized_mean():
    a=trimesh.transformations.rotation_matrix(np.pi/6,[0,0,1])
    b=np.eye(4);b[:3,:3]*=7
    r,e=mean_up([a,b])
    expected=a[:3,1]+[0,1,0];expected/=np.linalg.norm(expected)
    np.testing.assert_allclose(r[:3,:3]@expected,[0,1,0],atol=1e-8)
    np.testing.assert_allclose(r[:3,:3].T@r[:3,:3],np.eye(3),atol=1e-8)
    assert e['object_count']==2
    np.testing.assert_allclose(r[:3,3],0)


def test_cancelling_up_is_not_arbitrarily_resolved():
    a=np.eye(4);b=trimesh.transformations.rotation_matrix(np.pi,[1,0,0])
    with pytest.raises(ValueError,match='cancels'):mean_up([a,b])


def test_floor_anchors_move_individually_other_objects_share_origin_shift():
    geo={k:(np.array([[0,y,0],[1,y+1,1]]),None) for k,y in [('a',1),('b',3),('c',5)]}
    ms={k:np.eye(4) for k in geo}
    result,e=floor_align(geo,ms,['a','b'])
    assert [result[k][1,3] for k in geo]==[-1,-3,-2]
    assert e['original_floor_height']==2
    np.testing.assert_allclose(ms['a'],np.eye(4))


def test_export_preserves_binary_and_positions(tmp_path):
    trimesh.creation.box().export(tmp_path/'object.glb')
    objects=[dict(id='a',asset='object.glb',pose={})]
    assemble_streamed(tmp_path,objects,matrix_for_pose=lambda _:np.eye(4))
    matrix=trimesh.transformations.rotation_matrix(.2,[0,0,1]);matrix[1,3]=2
    evidence=write_scene(tmp_path/'scene.glb',tmp_path/'aligned.glb',{'a':matrix})
    assert evidence['binary_preserved']
    scene=trimesh.load(tmp_path/'aligned.glb',force='scene',process=False)
    np.testing.assert_allclose(scene.graph['a'][0],matrix)

def test_omitted_alias_is_not_in_scene_but_binary_is_preserved(tmp_path):
    trimesh.creation.box().export(tmp_path/'object.glb')
    objects=[dict(id=k,asset='object.glb',pose={}) for k in ['a','b']]
    assemble_streamed(tmp_path,objects,matrix_for_pose=lambda _:np.eye(4))
    evidence=write_scene(tmp_path/'scene.glb',tmp_path/'one.glb',{'a':np.eye(4),'b':np.eye(4)},omit=['b'])
    assert evidence['binary_preserved']
    doc,_,_=read_header(tmp_path/'one.glb')
    root=doc['scenes'][0]['nodes'][0]
    assert [doc['nodes'][i]['name'] for i in doc['nodes'][root]['children']]==['a']


def test_support_does_not_snap_to_infinite_plane():
    support=trimesh.creation.box(extents=[2,.2,2])
    item=trimesh.creation.box(extents=[.3,.3,.3]);item.apply_translation([10,.4,0])
    dy,e=settle_on(item.vertices,support.triangles,.01)
    assert dy is None


def test_vertical_settle_matches_surface_without_scaling():
    support=trimesh.creation.box(extents=[2,.2,2])
    item=trimesh.creation.box(extents=[.3,.3,.3]);item.apply_translation([0,.4,0])
    dy,e=settle_on(item.vertices,support.triangles,.01)
    assert dy==pytest.approx(-.15)
