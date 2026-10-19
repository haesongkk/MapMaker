import io
import numpy as np
import trimesh
from mapmaker.scene_placement import group_export_nodes
from test_scene_quality import scene_of


def test_glb_groups_preserve_world_transforms_and_mesh_membership():
    scene,objects,_=scene_of([('one',[1,1,1],[0,.5,0]),('two',[.2,.2,.2],[2,1,0])])
    scene.add_geometry(trimesh.creation.box(extents=[4,.01,4]),node_name='structure_00')
    original={o['id']:scene.graph[o['id']][0].copy() for o in objects}
    groups=group_export_nodes(scene,objects,[dict(node='structure_00')])
    binary=scene.export(file_type='glb')
    loaded=trimesh.load(io.BytesIO(binary),file_type='glb',force='scene',process=False)
    for obj in objects:
        assert loaded.graph.transforms.parents[obj['id']]==groups['objects']
        np.testing.assert_allclose(loaded.graph[obj['id']][0],original[obj['id']])
    assert loaded.graph.transforms.parents['structure_00']==groups['space']
    assert len(loaded.graph.nodes_geometry)==3


def test_regrouping_imported_glb_has_one_parent_per_object():
    scene,objects,_=scene_of([('one',[1,1,1],[0,.5,0]),('two',[.2,.2,.2],[2,1,0])])
    groups=group_export_nodes(scene,objects,[])
    scene=trimesh.load(io.BytesIO(scene.export(file_type='glb')),file_type='glb',force='scene',process=False)
    expected={obj['id']:scene.graph[obj['id']][0].copy() for obj in objects}
    for obj in objects:
        scene.graph.update(frame_from=scene.graph.base_frame,frame_to=obj['id'],matrix=expected[obj['id']])
    group_export_nodes(scene,objects,[])
    loaded=trimesh.load(io.BytesIO(scene.export(file_type='glb')),file_type='glb',force='scene',process=False)
    for obj in objects:
        assert loaded.graph.transforms.parents[obj['id']]==groups['objects']
        np.testing.assert_allclose(loaded.graph[obj['id']][0],expected[obj['id']])
        incoming=[edge for edge in loaded.graph.to_edgelist() if edge[1]==obj['id']]
        assert len(incoming)==1
