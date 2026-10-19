import numpy as np
from PIL import Image
import trimesh
from mapmaker.scene_composite_review import compound_coverage, review_reconstructed_composites
from mapmaker.scene_vanishing import fit_camera
from test_scene_geometry_v6 import room_pointmap


def fixture():
    children = {}
    for i, (y,x) in enumerate([(10,10),(40,50),(70,20)]):
        mask=np.zeros((100,100),bool);mask[y:y+10,x:x+10]=True
        children[str(i)]=mask
    return np.logical_or.reduce(list(children.values())),children,np.ones((100,100),bool)


def test_all_visible_regions_retained_independent_of_names():
    parent,children,valid=fixture()
    expected=compound_coverage(parent,children,valid)
    assert expected and expected['retained_fraction']==1
    renamed={f'name_{i}':mask for i,mask in enumerate(reversed(list(children.values())))}
    assert compound_coverage(parent,renamed,valid)==expected


def test_missing_small_component_vetoes_suppression_even_with_tiny_area_fraction():
    parent,children,valid=fixture()
    parent[80:88,80:88]=True
    assert compound_coverage(parent,children,valid) is None


def test_connected_body_or_unreliable_depth_is_not_a_compound():
    parent,children,valid=fixture()
    connected=np.ones_like(parent)
    assert compound_coverage(connected,children,valid) is None
    valid[10:20,10:20]=False
    assert compound_coverage(parent,children,valid) is None


def test_only_inconsistent_parent_is_removed_and_children_stay_intact(tmp_path):
    parent,children,_=fixture()
    points=room_pointmap(100)
    inverse=np.linalg.inv(fit_camera(points)['matrix'])
    def quad(x0,y0,x1,y1):
        vertices=np.array([[x0,y0,1],[x1,y0,1],[x1,y1,1],[x0,y1,1]])@inverse.T*4
        return trimesh.Trimesh(vertices=vertices,faces=[[0,1,2],[0,2,3]],process=False)
    masks={**children,'parent':parent}
    meshes={}
    for key,mask in children.items():
        y,x=np.where(mask);meshes[key]=quad(x.min(),y.min(),x.max(),y.max())
    for bad in (False,True):
        scene=trimesh.Scene(base_frame='Scene');objects=[]
        meshes['parent']=quad(0,55,99,99) if bad else trimesh.util.concatenate([meshes[k] for k in children])
        for key,mask in masks.items():
            Image.fromarray(mask.astype('uint8')*255).save(tmp_path/f'{key}.png')
            scene.graph.update(frame_from='Scene',frame_to=key,matrix=np.eye(4))
            scene.add_geometry(meshes[key].copy(),node_name=key+'_mesh',parent_node_name=key)
            objects.append(dict(id=key,name='display only',mask=f'{key}.png',status='generated'))
        before={key:scene.geometry[key].vertices.copy() for key in scene.geometry}
        decisions=review_reconstructed_composites(tmp_path,scene,objects,points)
        assert len(decisions)==int(bad)
        assert (objects[-1]['status']=='duplicate')==bad
        for obj in objects[:-1]:
            assert obj['status']=='generated' and obj['id'] in scene.graph.nodes
        for key in scene.geometry:
            np.testing.assert_array_equal(scene.geometry[key].vertices,before[key])
