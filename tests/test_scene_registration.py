import numpy as np
import pytest
import trimesh
from mapmaker.scene_registration import propose_translation


def observed_box():
    mesh=trimesh.creation.box()
    # Deterministic points on three visible surfaces constrain translation.
    a,b=np.meshgrid(np.linspace(-.45,.45,12),np.linspace(-.45,.45,12))
    points=np.concatenate([np.stack([a,b,np.full_like(a,-.5)],-1).reshape(-1,3),
        np.stack([np.full_like(a,-.5),a,b],-1).reshape(-1,3),
        np.stack([a,np.full_like(a,-.5),b],-1).reshape(-1,3)])
    return mesh,points


@pytest.mark.parametrize('scale',[.01,1.,100.])
def test_bounded_registration_reduces_independent_observation_error(scale):
    mesh,points=observed_box();mesh.vertices*=scale;points*=scale
    offset=np.array([.04,.03,.02])*scale;mesh.apply_translation(offset)
    delta,report=propose_translation(mesh,points)
    assert delta is not None
    assert np.linalg.norm(delta+offset)<np.linalg.norm(offset)*.5
    assert report['after']<report['before']*.8
    assert np.linalg.norm(delta)<=report['budget']


def test_correct_pose_remains_unchanged_and_order_does_not_matter():
    mesh,points=observed_box()
    delta,report=propose_translation(mesh,points)
    assert delta is None and report['reason']=='already_matches_observed_depth'
    mesh.apply_translation([.04,.03,.02])
    a,ra=propose_translation(mesh,points)
    b,rb=propose_translation(mesh,points[::-1])
    np.testing.assert_allclose(a,b)
    assert ra==rb


def test_large_mismatch_does_not_exceed_budget():
    mesh,points=observed_box();mesh.apply_translation([0,2,0])
    delta,report=propose_translation(mesh,points)
    assert delta is None


def test_noisy_correct_pose_with_sparse_outliers_is_not_moved():
    mesh,points=observed_box()
    rng=np.random.default_rng(17)
    noisy=points+rng.normal(0,.002,points.shape)
    noisy[::17]+=[.3,-.2,.1]
    delta,report=propose_translation(mesh,noisy)
    assert delta is None


def test_one_observed_plane_does_not_invent_tangential_translation():
    mesh=trimesh.creation.box()
    x,y=np.meshgrid(np.linspace(-.25,.25,12),np.linspace(-.25,.25,12))
    observed=np.stack([x,y,np.full_like(x,-.5)],-1).reshape(-1,3)
    mesh.apply_translation([0,0,.04])
    delta,report=propose_translation(mesh,observed)
    assert delta is not None
    np.testing.assert_allclose(delta[:2],[0,0],atol=1e-8)
    assert abs(delta[2]+.04)<.001
