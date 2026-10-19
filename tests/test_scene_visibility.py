import numpy as np
import pytest
from mapmaker.scene_visibility import ray_depth, visibility_evidence


def plane(z, radius=3.):
    vertices=np.array([[-radius,-radius,z],[radius,-radius,z],[radius,radius,z],[-radius,radius,z]])
    return vertices[[[0,1,2],[0,2,3]]]


@pytest.mark.parametrize('sign', [1., -1.])
def test_nearest_surface_and_outside_ray(sign):
    faces=np.concatenate([plane(4*sign),plane(2*sign)])
    values, report=ray_depth(faces,np.array([[0,0,sign],[10,0,sign]]),depth_sign=sign)
    assert values[0] == 2 and np.isnan(values[1])
    assert report['completed']


def test_perspective_depth_is_reciprocal_not_linear_interpolation():
    face=np.array([[[0,0,2],[4,0,4],[0,8,8]]],float)
    depth,_=ray_depth(face,np.array([[1/3,1/3,1.]]))
    np.testing.assert_allclose(depth,[1/((1/2+1/4+1/8)/3)])


def test_query_budget_cannot_silently_certify_empty_geometry():
    _, report=ray_depth(np.tile(plane(2),(10,1,1)),np.array([[0,0,1.]]),max_pairs=1)
    assert not report['completed'] and report['reason']=='triangle_query_budget_exhausted'


def test_visible_foreground_error_is_distinct_from_hidden_completion():
    y,x=np.mgrid[:80,:80]
    points=np.stack([(x-40)/30,(y-40)/30,np.full_like(x,3.)],-1)
    mask=np.zeros((80,80),bool);mask[25:55,25:55]=True
    front=visibility_evidence(plane(2),points,mask)
    behind=visibility_evidence(plane(4),points,mask)
    assert front['outside_front_fraction']==1.
    assert behind['outside_front_fraction']==0.
    assert behind['outside_hidden_pixels']>0
    assert not front['quality_passed'] and not behind['quality_passed']


def test_invalid_pointmap_cannot_supply_visibility_evidence():
    points=np.full((80,80,3),np.nan)
    assert not visibility_evidence(plane(2),points,np.ones((80,80),bool))['accepted']
