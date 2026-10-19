import numpy as np
import trimesh
from mapmaker.scene_collision import MeshIndex
from mapmaker.scene_plane_penetration import planar_penetration_evidence


def plane():
    return np.array([[[-1.,0,-1],[1,0,-1],[1,0,1]],[[-1.,0,-1],[1,0,1],[-1,0,1]]])


def test_finite_plane_witness_and_clear_endpoint():
    body=trimesh.creation.box(extents=[.2,.2,.2])
    evidence=planar_penetration_evidence(MeshIndex(plane()),body.triangles,body.triangles+[0,.11,0],[0,1,0],.001)
    assert evidence['penetration_confirmed'] and evidence['finite_patch_witnesses']>0
    assert evidence['requires_confirmed_initial_finite_intersection']


def test_missing_patch_warped_patch_and_unrepaired_endpoint_abstain():
    body=trimesh.creation.box(extents=[.2,.2,.2])
    warped=plane();warped[0,0,1]=.05
    cases=[(plane()+[5,0,0],body.triangles+[0,.11,0]),(warped,body.triangles+[0,.11,0]),(plane(),body.triangles)]
    for surface,end in cases:
        assert not planar_penetration_evidence(MeshIndex(surface),body.triangles,end,[0,1,0],.001)['penetration_confirmed']


def test_touch_is_not_initial_intrusion():
    body=trimesh.creation.box(extents=[.2,.2,.2]);body.apply_translation([0,.1,0])
    assert not planar_penetration_evidence(MeshIndex(plane()),body.triangles,body.triangles+[0,.01,0],[0,1,0],.001)['penetration_confirmed']


def test_collision_checker_requires_explicit_planar_evidence():
    from mapmaker.scene_pose_refinement import pose_collision_checks
    from mapmaker.scene_collision import certified_penetration_repair
    body=trimesh.creation.box(extents=[.2,.2,.2]);fixed=plane();index=MeshIndex(fixed)
    transform=np.eye(4);transform[1,3]=.11
    bounds={'body':body.bounds,'surface':np.array([fixed.min((0,1)),fixed.max((0,1))])}
    args=(body.triangles,transform,bounds,'body',{'surface'},lambda _:index)
    assert not certified_penetration_repair(pose_collision_checks(*args))
    checks=pose_collision_checks(*args,surface_planes={'surface':dict(normal=[0,1,0],tolerance=.001)})
    assert certified_penetration_repair(checks)
