import numpy as np
import pytest
import trimesh
from mapmaker.scene_collision import MeshIndex, rigid_triangle_hull_hits


def test_rotation_hits_obstacle_between_clear_endpoints():
    moving = trimesh.creation.box(extents=[2,.1,.1])
    fixed = trimesh.creation.box(extents=[.05,.05,.05])
    fixed.apply_translation([.7,.7,0])
    index = MeshIndex(fixed.triangles)
    transform = trimesh.transformations.rotation_matrix(np.pi/2,[0,0,1])
    end = trimesh.transform_points(moving.vertices,transform)[moving.faces]
    assert index.swept_collision(moving.triangles,np.zeros(3)) is False
    assert index.swept_collision(end,np.zeros(3)) is False
    assert index.rigid_swept_collision(moving.triangles,transform) is True


def test_clear_rotation_and_enclosed_solid_are_distinguished():
    moving = trimesh.creation.box(extents=[2,.1,.1])
    fixed = trimesh.creation.box(extents=[.05,.05,.05])
    fixed.apply_translation([2,2,0])
    transform = trimesh.transformations.rotation_matrix(.1,[0,0,1])
    assert MeshIndex(fixed.triangles).rigid_swept_collision(moving.triangles,transform) is False
    enclosing = trimesh.creation.box(extents=[10,10,10])
    assert MeshIndex(enclosing.triangles).rigid_swept_collision(moving.triangles,transform) is True


def test_coplanar_hulls_and_padding_do_not_miss_touching():
    a = np.array([[[0,0,0],[1,0,0],[0,1,0]]],float)
    b = a+np.array([2,0,0])
    assert not rigid_triangle_hull_hits(a,a,b)[0]
    assert rigid_triangle_hull_hits(a,b,b)[0]
    assert rigid_triangle_hull_hits(a,a,a+[0,0,.001],padding=.002)[0]


def test_nonrigid_transform_is_rejected():
    box = trimesh.creation.box()
    transform = np.diag([2,1,1,1])
    with pytest.raises(ValueError, match='rigid'):
        MeshIndex(box.triangles).rigid_swept_collision(box.triangles,transform)


def test_budget_and_open_volume_are_not_certified_clear():
    moving = trimesh.creation.box(extents=[2,.1,.1])
    obstacle = trimesh.creation.box(extents=[.05,.05,.05])
    obstacle.apply_translation([.7,.7,0])
    transform = trimesh.transformations.rotation_matrix(np.pi/2,[0,0,1])
    assert MeshIndex(obstacle.triangles).rigid_swept_collision(moving.triangles,transform,max_pairs=0) is None
    open_surface = obstacle.triangles[:1]+[5,0,0]
    assert MeshIndex(open_surface).rigid_swept_collision(moving.triangles,transform) is None
    assert MeshIndex(open_surface).rigid_swept_collision(moving.triangles,transform,check_containment=False) is False


def test_uniform_scaling_rotation_checks_entire_path_and_rejects_shear():
    moving=trimesh.creation.box(extents=[2,.1,.1])
    fixed=trimesh.creation.box(extents=[.05,.05,.05])
    fixed.apply_translation([.75,.75,0])
    transform=trimesh.transformations.rotation_matrix(np.pi/2,[0,0,1])
    transform[:3,:3]*=1.2
    index=MeshIndex(fixed.triangles)
    end=trimesh.transform_points(moving.vertices,transform)[moving.faces]
    assert index.swept_collision(moving.triangles,np.zeros(3)) is False
    assert index.swept_collision(end,np.zeros(3)) is False
    assert index.similarity_swept_collision(moving.triangles,transform) is True
    fixed.apply_translation([5,5,0])
    assert MeshIndex(fixed.triangles).similarity_swept_collision(moving.triangles,transform) is False
    with pytest.raises(ValueError):
        index.similarity_swept_collision(moving.triangles,np.diag([1.2,1.,1.,1.]))
