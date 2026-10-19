import numpy as np
from mapmaker.scene_free_space import free_space_faces


def scene():
    y,x=np.mgrid[:100,:100]
    points=np.stack([(50-x)*.06,(50-y)*.06,np.full_like(x,3.)],-1)
    faces=np.array([[[-.5,-.5,2],[.5,-.5,2],[0,.5,2]]],float)
    return faces,points,np.zeros((100,100),bool)


def test_only_unmasked_foreground_contradictions_are_selected():
    faces,points,mask=scene()
    keep,evidence=free_space_faces(faces,points,mask)
    assert keep.tolist()==[True] and evidence['removed_area_fraction']==1
    faces[:,:,2]=4
    assert not free_space_faces(faces,points,mask)[0].any()
    faces[:,:,2]=2
    mask[48:53,48:53]=True
    assert not free_space_faces(faces,points,mask)[0].any()


def test_an_interior_depth_hole_or_depth_edge_vetoes_whole_face():
    faces,points,mask=scene()
    points[48,52]=np.nan
    assert not free_space_faces(faces,points,mask)[0].any()
    faces,points,mask=scene()
    points[48,52]*=.5
    assert not free_space_faces(faces,points,mask)[0].any()


def test_vertex_order_and_depth_sign_do_not_change_decision():
    faces,points,mask=scene()
    expected=free_space_faces(faces,points,mask)[0]
    np.testing.assert_array_equal(free_space_faces(faces[:,::-1],points,mask)[0],expected)
    np.testing.assert_array_equal(free_space_faces(-faces,-points,mask)[0],expected)
    assert not free_space_faces(faces,points,mask,max_box_pixels=4)[0].any()
