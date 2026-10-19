import numpy as np
import trimesh
from mapmaker.scene_contact_pose import contact_pose_candidates


def plane():
    return np.array([[[-2.,0,-2],[2,0,-2],[2,0,2]],[[-2.,0,-2],[2,0,2],[-2,0,2]]])


def test_recovers_tilted_rigid_feet_without_mutation():
    mesh=trimesh.creation.box(extents=[.5,.5,.5])
    mesh.apply_translation([0,.27,0])
    mesh.apply_transform(trimesh.transformations.rotation_matrix(np.deg2rad(4),[0,0,1],point=[0,.27,0]))
    before=mesh.vertices.copy()
    candidates=list(contact_pose_candidates(before,plane(),.1,.001))
    assert candidates
    transform,evidence=candidates[0]
    moved=trimesh.transform_points(before,transform)
    assert abs(moved[:,1].min())<1e-10
    assert np.ptp(np.sort(moved[:,1])[:4])<1e-10
    np.testing.assert_array_equal(mesh.vertices,before)
    assert evidence['requires_source_and_collision_validation']
    np.testing.assert_allclose(transform[:3,:3].T@transform[:3,:3],np.eye(3),atol=1e-10)
    reordered=list(contact_pose_candidates(before[::-1],plane(),.1,.001))
    np.testing.assert_allclose(reordered[0][0],transform,atol=1e-10)


def test_no_invented_support_or_motion_for_stable_object():
    mesh=trimesh.creation.box(extents=[.5,.5,.5]);mesh.apply_translation([0,.25,0])
    assert not list(contact_pose_candidates(mesh.vertices,plane(),.1,.001))
    assert not list(contact_pose_candidates(mesh.vertices,plane()+[10,0,0],.1,.001))


def test_large_required_tilt_cannot_escape_motion_bounds():
    mesh=trimesh.creation.box(extents=[.5,.5,.5]);mesh.apply_translation([0,.3,0])
    mesh=mesh.subdivide().subdivide()
    mesh.apply_transform(trimesh.transformations.rotation_matrix(np.deg2rad(20),[0,0,1],point=[0,.3,0]))
    evidence=[]
    candidates=list(contact_pose_candidates(mesh.vertices,plane(),.2,.001,diagnostics=evidence))
    assert not candidates
    assert any(r['reason']=='fit_exceeds_rotation_budget' for r in evidence)
