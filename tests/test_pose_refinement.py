import numpy as np
from PIL import Image
import trimesh
from scipy.spatial.transform import Rotation
from mapmaker.scene_pose_refinement import refine_poses


def test_runtime_repairs_existing_intersection_without_using_names(tmp_path,monkeypatch):
    def run(name, directory, fixed_x=.515):
        directory.mkdir()
        y,x=np.mgrid[:200,:200]
        points=np.stack([(100-x)*.03,(100-y)*.03,np.full_like(x,3.)],-1)
        mask=np.zeros((200,200),np.uint8);mask[85:116,85:116]=255
        Image.fromarray(mask).save(directory/'mask.png')
        scene=trimesh.Scene(base_frame='Scene')
        mesh=trimesh.creation.box(extents=[1,1,.2]);mesh.apply_translation([0,0,3.1])
        fixed=trimesh.creation.box(extents=[.05,1,.2]);fixed.apply_translation([fixed_x,0,3.1])
        for oid,geometry in [('target',mesh),('fixed',fixed)]:
            scene.graph.update(frame_from='Scene',frame_to=oid,matrix=np.eye(4))
            scene.add_geometry(geometry,node_name=oid+'_mesh',parent_node_name=oid)
        obj=dict(id='target',name=name,mask='mask.png',transform={},placement={})
        objects=[obj,dict(id='fixed',name='')]
        transform=np.diag([.94,.94,.94,1.]);transform[2,3]=3.1*.06
        def proposal(mesh,observed,**kwargs):
            return transform,dict(reason='test_known_pose',rotation_degrees=0.,scale_factor=.94)
        monkeypatch.setattr('mapmaker.scene_pose_refinement.propose_similarity_transform',proposal)
        result=refine_poses(directory,scene,objects,points,dict(common_transform=np.eye(4)),{})
        return result,scene.graph['target'][0]
    result,matrix=run('arbitrary',tmp_path/'named')
    assert len(result['changes'])==1
    assert result['changes'][0]['existing_penetration_repair']
    assert result['changes'][0]['collision_checks'][0]['after']=='clear'
    renamed,renamed_matrix=run('',tmp_path/'nameless')
    assert renamed==result
    np.testing.assert_array_equal(matrix,renamed_matrix)
    touching,touching_matrix=run('',tmp_path/'touching',fixed_x=.525)
    assert not touching['changes']
    np.testing.assert_array_equal(touching_matrix,np.eye(4))


def test_pose_fit_is_independent_of_room_alignment(tmp_path):
    y,x=np.mgrid[:100,:100]
    points=np.stack([(50-x)*.02,(50-y)*.02,np.full_like(x,3.)],-1)
    mask=np.zeros((100,100),np.uint8);mask[28:73,28:73]=255
    results=[]
    for i in range(2):
        directory=tmp_path/str(i);directory.mkdir()
        Image.fromarray(mask).save(directory/'mask.png')
        common=np.eye(4)
        if i:
            common[:3,:3]=Rotation.from_euler('xyz',[17,-23,11],degrees=True).as_matrix()
            common[:3,3]=[.4,-1.2,.7]
        mesh=trimesh.creation.box(extents=[1,1,.2])
        mesh.apply_translation([.035,0,2.98])
        scene=trimesh.Scene(base_frame='Scene')
        scene.graph.update(frame_from='Scene',frame_to='target',matrix=common)
        scene.add_geometry(mesh,node_name='target_mesh',parent_node_name='target')
        obj=dict(id='target',mask='mask.png',transform={},placement={'original_matrix':np.eye(4).tolist()})
        report=refine_poses(directory,scene,[obj],points,dict(common_transform=common),{})
        results.append((report,np.linalg.inv(common)@scene.graph['target'][0]))
    assert results[0][0]['changes']
    assert len(results[1][0]['changes'])==len(results[0][0]['changes'])
    np.testing.assert_allclose(results[0][1],results[1][1],atol=1e-8)
    for key in ('before','after','scale','validation_samples','selected_iteration'):
        np.testing.assert_allclose(results[0][0]['changes'][0][key],results[1][0]['changes'][0][key],atol=1e-8)
    for report,camera_matrix in results:
        np.testing.assert_allclose(report['changes'][0]['camera_transform'],camera_matrix,atol=1e-8)


def test_collision_filter_keeps_earlier_clear_pose(tmp_path,monkeypatch):
    """A later blocked fit must not erase an earlier collision-free candidate."""
    projection=dict(accepted=True,silhouette_iou=1.,mask_covered_fraction=1.)
    monkeypatch.setattr('mapmaker.scene_pose_refinement.silhouette_evidence',lambda *args:projection.copy())
    bad=np.eye(4);bad[0,3]=.06
    earlier=np.eye(4);earlier[0,3]=.02
    def proposal(mesh,observed,*,candidate_filter):
        assert not candidate_filter(bad.copy())
        assert candidate_filter(earlier.copy())
        return earlier.copy(),dict(reason='test_history',rotation_degrees=0.,scale_factor=1.)
    monkeypatch.setattr('mapmaker.scene_pose_refinement.propose_similarity_transform',proposal)
    results=[]
    for number,name in enumerate(['unrelated display name','']):
        directory=tmp_path/str(number);directory.mkdir()
        Image.fromarray(np.full((10,10),255,np.uint8)).save(directory/'mask.png')
        y,x=np.mgrid[:10,:10]
        points=np.stack([x*.02,y*.02,np.full_like(x,3.)],-1)
        scene=trimesh.Scene(base_frame='Scene')
        moving=trimesh.creation.box(extents=[1,1,.2]);moving.apply_translation([0,0,3.1])
        obstacle=trimesh.creation.box(extents=[.05,1,.2]);obstacle.apply_translation([.57,0,3.1])
        for oid,mesh in [('target',moving),('obstacle',obstacle)]:
            scene.graph.update(frame_from='Scene',frame_to=oid,matrix=np.eye(4))
            scene.add_geometry(mesh,node_name=oid+'_mesh',parent_node_name=oid)
        objects=[dict(id='target',name=name,mask='mask.png',transform={},placement={}),dict(id='obstacle')]
        report=refine_poses(directory,scene,objects,points,dict(common_transform=np.eye(4)),{})
        assert len(report['changes'])==1
        assert len(report['changes'][0]['rejected_collision_candidates'])==1
        assert report['changes'][0]['rejected_collision_candidates'][0]['collision_checks'][0]['after']=='intersection'
        np.testing.assert_array_equal(scene.graph['target'][0],earlier)
        results.append(report)
    assert results[0]==results[1]
