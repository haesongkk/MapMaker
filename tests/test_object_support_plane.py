import numpy as np
import trimesh
from mapmaker.scene_object_support import measured_support_plane


def test_local_shelf_inside_tall_body_uses_actual_mesh_and_is_order_invariant():
    prop=trimesh.creation.box(extents=[.4,.4,.4])
    prop.apply_translation([0,.72,0])
    shelf=trimesh.creation.box(extents=[2,.04,2]);shelf.apply_translation([0,.48,0])
    upper=trimesh.creation.box(extents=[2,.04,2]);upper.apply_translation([0,2,0])
    faces=np.concatenate([shelf.triangles,upper.triangles])
    plane,evidence=measured_support_plane(prop.vertices,faces,.05,.001)
    assert plane is not None and evidence['hits']>=3
    np.testing.assert_allclose(plane['point'][1],.5)
    other,_=measured_support_plane(prop.vertices[::-1],faces[::-1],.05,.001)
    np.testing.assert_allclose(plane['normal'],other['normal'])
    np.testing.assert_allclose(plane['point'],other['point'])
    # Empty enclosing bounds and distant surfaces provide no support evidence.
    assert measured_support_plane(prop.vertices,faces+[5,0,0],.05,.001)[0] is None
    assert measured_support_plane(prop.vertices,faces-[0,.2,0],.05,.001)[0] is None


def test_one_sided_hits_cannot_certify_balanced_support():
    prop=trimesh.creation.box(extents=[.4,.4,.4]).subdivide().subdivide()
    prop.apply_translation([0,.72,0])
    shelf=trimesh.creation.box(extents=[.1,.04,2]);shelf.apply_translation([.18,.48,0])
    assert measured_support_plane(prop.vertices,shelf.triangles,.05,.001)[0] is None


def test_refinement_checks_object_support_without_room_planes_and_preserves_names(tmp_path):
    from PIL import Image
    from mapmaker.scene_supported_refinement import refine_supported_poses
    scene=trimesh.Scene()
    prop=trimesh.creation.box(extents=[.4,.4,.4]);prop.apply_translation([0,.7,0])
    shelf=trimesh.creation.box(extents=[2,.04,2]);shelf.apply_translation([0,.48,0])
    scene.add_geometry(prop,node_name='a',geom_name='a')
    scene.add_geometry(shelf,node_name='b',geom_name='b')
    mask=np.zeros((8,8),np.uint8);mask[2:6,2:6]=255
    Image.fromarray(mask).save(tmp_path/'a.png')
    Image.fromarray(255-mask).save(tmp_path/'b.png')
    objects=[dict(id=k,name='anything',mask=k+'.png') for k in ('a','b')]
    placement=dict(contact_tolerance=.001,common_transform=np.eye(4).tolist())
    points=np.zeros((8,8,3))
    before={k:scene.graph[k][0].copy() for k in ('a','b')}
    first=refine_supported_poses(tmp_path,scene,objects,points,placement,dict(surfaces=[]))
    record=next(r for r in first['records'] if r['object_id']=='a')
    pair=next(r for r in record['support_assessments'] if r['surface_id']=='b')
    assert pair['reason']=='already_supported'
    assert pair['object_support_evidence']['reason']=='measured_local_support_plane'
    assert not first['changes']
    for obj in objects:obj['name']=''
    second=refine_supported_poses(tmp_path,scene,objects,points,placement,dict(surfaces=[]))
    assert first==second
    for k in before:np.testing.assert_array_equal(scene.graph[k][0],before[k])
