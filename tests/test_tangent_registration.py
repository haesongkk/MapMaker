import numpy as np
import trimesh
import pytest
from mapmaker.scene_tangent_registration import propose_tangent_pose


def fixture():
    mesh=trimesh.creation.box(extents=[.4,.6,.3]);mesh.apply_translation([0,.3,0])
    dense=mesh.subdivide().subdivide().vertices
    return mesh,dense


@pytest.mark.parametrize('fit_fraction',[.8,1.])
def test_recovers_tangent_translation_without_changing_plane_height(fit_fraction):
    mesh,observed=fixture();mesh.apply_translation([.02,0,.01])
    before=mesh.vertices.copy()
    t,e=propose_tangent_pose(mesh,np.eye(4),observed,np.array([0.,1.,0.]),fit_fraction=fit_fraction)
    assert t is not None and e['candidate_score']<e['baseline_score']
    moved=trimesh.transform_points(before,t)
    np.testing.assert_allclose(moved[:,1],before[:,1],atol=1e-12)
    np.testing.assert_array_equal(mesh.vertices,before)
    assert np.linalg.norm(moved-before,axis=1).max()<=np.linalg.norm(mesh.extents)*.08


def test_contact_filter_can_reject_all_improvements():
    mesh,observed=fixture();mesh.apply_translation([.02,0,.01])
    t,e=propose_tangent_pose(mesh,np.eye(4),observed,np.array([0.,1.,0.]),candidate_filter=lambda _:False)
    assert t is None and e['history'][0]['reason']=='candidate_filter_rejected'
