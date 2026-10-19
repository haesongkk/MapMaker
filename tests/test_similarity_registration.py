import numpy as np
import trimesh
import pytest
from mapmaker.scene_registration import propose_similarity_transform


def test_uniform_size_error_is_corrected_without_changing_proportions():
    mesh=trimesh.creation.icosphere(subdivisions=3)
    observed=mesh.vertices*.94+np.array([.02,-.01,.015])
    transform,report=propose_similarity_transform(mesh,observed)
    assert transform is not None
    assert .9 <= report['scale_factor'] <= 1.1
    assert abs(report['scale_factor']-.94)<.005
    assert report['after'] < report['before']*.1
    singular=np.linalg.svd(transform[:3,:3],compute_uv=False)
    np.testing.assert_allclose(singular,singular[0],atol=1e-10)
    reverse,reverse_report=propose_similarity_transform(mesh,observed[::-1])
    np.testing.assert_allclose(transform,reverse)
    assert reverse_report==report


def test_correct_shape_is_unchanged_and_large_scale_change_not_authorized():
    mesh=trimesh.creation.icosphere(subdivisions=3)
    transform,report=propose_similarity_transform(mesh,mesh.vertices)
    assert transform is None
    assert report['reason']=='already_matches_observed_depth'
    transform,report=propose_similarity_transform(mesh,mesh.vertices*.6)
    assert transform is None or .9 <= report['scale_factor'] <= 1.1


def test_external_constraint_can_recover_an_earlier_depth_valid_pose():
    mesh=trimesh.creation.box(extents=[2,2,2])
    y,z=np.meshgrid(np.linspace(-.75,.75,20),np.linspace(-.75,.75,20))
    observed=np.column_stack([np.full(y.size,1.4),y.ravel(),z.ravel()])
    unconstrained,_=propose_similarity_transform(mesh,observed,scale_fraction=0.)
    assert unconstrained[0,3]>.21
    transform,report=propose_similarity_transform(mesh,observed,scale_fraction=0.,
                                                 candidate_filter=lambda matrix:matrix[0,3]<=.21)
    assert transform is not None and 0<transform[0,3]<=.21
    assert report['after']<report['before']*.8
    assert report['after_p90']<=report['before_p90']
    assert report['candidate_filter_rejections']>0
    assert report['selected_iteration']<report['fitting_iterations']
    rejected,evidence=propose_similarity_transform(mesh,observed,scale_fraction=0.,
                                                   candidate_filter=lambda matrix:False)
    assert rejected is None and evidence['reason']=='candidate_constraints_rejected'
    calls=[]
    rejected,evidence=propose_similarity_transform(mesh,observed+[10,0,0],scale_fraction=0.,
        candidate_filter=lambda matrix:calls.append(matrix) or True)
    assert rejected is None and not calls


@pytest.mark.parametrize('units', [.1, 1., 10.])
def test_partial_first_step_preserves_depth_gain_without_crossing_a_finite_wall(units):
    from mapmaker.scene_collision import MeshIndex
    mesh = trimesh.creation.box(extents=np.array([2., 2., 2.]) * units)
    y, z = np.meshgrid(np.linspace(-.75, .75, 20), np.linspace(-.75, .75, 20))
    observed = np.column_stack([np.full(y.size, 1.4), y.ravel(), z.ravel()]) * units
    wall = trimesh.creation.box(extents=np.array([.1, 3., 3.]) * units)
    wall.apply_translation(np.array([1.2, 0., 0.]) * units)
    index = MeshIndex(wall.triangles)
    verdicts = []

    def clear(matrix):
        result = index.similarity_swept_collision(mesh.triangles, matrix)
        verdicts.append(result)
        return result is False

    transform, evidence = propose_similarity_transform(mesh, observed, scale_fraction=0.,
                                                       candidate_filter=clear)
    assert transform is not None
    assert evidence['partial_step_fraction'] == .5
    assert True in verdicts and verdicts[-1] is False
    assert evidence['after'] <= evidence['before'] * .8
    assert evidence['after_p90'] <= evidence['before_p90']
    assert index.similarity_swept_collision(mesh.triangles, transform) is False
