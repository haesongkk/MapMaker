import numpy as np
import pytest
import trimesh
from mapmaker.scene_visible_depth import visible_depth_evidence


def test_back_surface_cannot_hide_wrong_foreground_depth():
    mesh=trimesh.creation.box(extents=[2,2,1]);mesh.apply_translation([0,0,2.5])
    observed=np.array([[x,y,3.] for x in (-.2,0,.2) for y in (-.2,0,.2)])
    result=visible_depth_evidence(mesh,observed,1.)
    assert result['hit_fraction']==1
    assert result['normalized_median']>=1
    assert result['normalized_signed_median']<=-1
    front=observed.copy();front[:,2]=2
    assert visible_depth_evidence(mesh,front,1.)['normalized_p90']<1e-10


def test_order_invariance_and_missing_ray_reporting():
    mesh=trimesh.creation.box();mesh.apply_translation([0,0,2])
    observed=np.array([[0,0,1.5],[10,0,2.]])
    a=visible_depth_evidence(mesh,observed,1.)
    assert a==visible_depth_evidence(mesh,observed[::-1],1.)
    assert a['hit_fraction']==.5
    with pytest.raises(ValueError):visible_depth_evidence(mesh,observed,0.)
