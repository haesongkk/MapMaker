import copy
import numpy as np
import pytest
import trimesh
from PIL import Image
from mapmaker.baseline_assembly import assemble_streamed,read_header


@pytest.mark.parametrize('textured',[False,True])
def test_streamed_assembly_preserves_meshes_materials_and_child_transforms(tmp_path,textured):
    mesh=trimesh.creation.box(extents=[1,2,3])
    if textured:
        mesh.visual=trimesh.visual.TextureVisuals(uv=np.zeros((len(mesh.vertices),2)),image=Image.new('RGB',(4,4),'red'))
    else:
        mesh.visual.vertex_colors=[20,60,180,255]
    child=trimesh.transformations.translation_matrix([.5,.2,-.3])
    source=trimesh.Scene();source.add_geometry(mesh,node_name='child',transform=child)
    source.export(tmp_path/'object.glb')
    loaded=trimesh.load(tmp_path/'object.glb',force='scene',process=False)
    original=loaded.to_geometry()
    objects=[dict(id=f'object_{i}',asset='object.glb',pose={'i':i}) for i in range(3)]
    def pose(p):
        matrix=trimesh.transformations.rotation_matrix(.4,[0,1,0]);matrix[:3,3]=[p['i']*4,1,2];return matrix
    assemble_streamed(tmp_path,objects,matrix_for_pose=pose)
    result=trimesh.load(tmp_path/'scene.glb',force='scene',process=False)
    assert len(result.graph.nodes_geometry)==3
    for obj in objects:
        np.testing.assert_allclose(result.graph[obj['id']][0],pose(obj['pose']),atol=1e-7)
        node=next(n for n in result.graph.nodes_geometry if n.startswith(obj['id']+'__'))
        matrix,name=result.graph[node];g=result.geometry[name]
        actual=trimesh.transform_points(g.vertices,matrix)
        expected=trimesh.transform_points(original.vertices,pose(obj['pose']))
        np.testing.assert_allclose(actual,expected,atol=1e-7)
        np.testing.assert_array_equal(g.faces,original.faces)
        assert g.visual.kind==original.visual.kind
    _,offset,size=read_header(tmp_path/'object.glb');_,combined_offset,total=read_header(tmp_path/'scene.glb')
    raw=(tmp_path/'object.glb').read_bytes()[offset:offset+size]
    assert (tmp_path/'scene.glb').read_bytes()[combined_offset:]==raw*3
    assert total==size*3


def test_streamed_assembly_keeps_all_149_duplicate_instances(tmp_path):
    trimesh.creation.box().export(tmp_path/'object.glb')
    objects=[dict(id=f'object_{i}',asset='object.glb',pose={}) for i in range(149)]
    answer=assemble_streamed(tmp_path,objects,matrix_for_pose=lambda p:np.eye(4))
    scene=trimesh.load(tmp_path/'scene.glb',force='scene',process=False)
    assert len(scene.graph.nodes_geometry)==149
    assert answer['independent_object_nodes']==[o['id'] for o in objects]
