import numpy as np
import trimesh
from mapmaker.scene_supported_pose import supported_pose_candidates


def test_supported_candidates_keep_bounds_contact_and_ignore_mesh_label():
    mesh=trimesh.creation.box(extents=[.4,.6,.3]);mesh.apply_translation([0,.3,0])
    observed=mesh.subdivide().subdivide().vertices
    plane=np.array([[[-2.,0,-2],[2,0,-2],[2,0,2]],[[-2.,0,-2],[2,0,2],[-2,0,2]]])
    before=mesh.vertices.copy()
    def proposals():return list(supported_pose_candidates(mesh,np.eye(4),observed,plane,[0,1,0],[0,0,0],.001))
    mesh.metadata['name']='arbitrary';first=proposals()
    mesh.metadata['name']='';second=proposals()
    assert first and len(first)==len(second)
    for (t,e),(other,_) in zip(first,second):
        np.testing.assert_array_equal(t,other)
        moved=trimesh.transform_points(before,t)
        assert moved[:,1].min()>=0
        assert e['final']['motion']<=e['motion_budget']
        assert e['final']['contact']['load_bearing_queries']>=3
        assert e['requires_source_and_collision_validation']
    np.testing.assert_array_equal(mesh.vertices,before)
    assert not list(supported_pose_candidates(mesh,np.eye(4),observed,plane+[10,0,0],[0,1,0],[0,0,0],.001))
