import numpy as np
import trimesh

from mapmaker.scene_collision import MeshIndex, swept_triangle_hits


def test_sweep_catches_thin_obstacle_between_clear_endpoints():
    moving = trimesh.creation.box(extents=[.1,.1,.1])
    moving.apply_translation([-.3,0,0])
    obstacle = trimesh.creation.box(extents=[.01,1,1])
    index = MeshIndex(obstacle.triangles)
    assert index.swept_collision(moving.triangles, [0,0,0]) is False
    assert index.swept_collision(moving.triangles + [.6,0,0], [0,0,0]) is False
    assert index.swept_collision(moving.triangles, [.6,0,0]) is True


def test_hollow_frame_aabb_overlap_can_be_proven_clear():
    bars=[]
    for x in [-1,1]:
        part=trimesh.creation.box(extents=[.1,2,2]);part.apply_translation([x,0,0]);bars.append(part)
    index=MeshIndex(trimesh.util.concatenate(bars).triangles)
    moving=trimesh.creation.box(extents=[.4,.4,.4])
    assert index.swept_collision(moving.triangles,[0,-.1,0]) is False


def test_containment_is_collision_without_surface_intersection():
    outer=trimesh.creation.box(extents=[3,3,3])
    inner=trimesh.creation.box(extents=[.4,.4,.4])
    assert MeshIndex(outer.triangles).swept_collision(inner.triangles,[0,.1,0]) is True
    assert MeshIndex(inner.triangles).swept_collision(outer.triangles,[0,.1,0]) is True


def test_coplanar_disjoint_triangles_and_budget_abstention():
    a=np.array([[[0,0,0],[1,0,0],[0,1,0]]],float)
    assert not swept_triangle_hits(a,[0,0,0],a+[2,2,0])[0]
    assert swept_triangle_hits(a,[0,0,0],a+.1)[0] == False
    assert swept_triangle_hits(a,[0,0,0],a)[0]
    box=trimesh.creation.box()
    assert MeshIndex(box.triangles).swept_collision(box.triangles,[0,0,0],max_pairs=0) is None


def test_finite_wall_does_not_block_crossing_its_infinite_extension():
    wall=np.array([[[-1,-1,0],[1,-1,0],[1,1,0]],[[-1,-1,0],[1,1,0],[-1,1,0]]],float)
    index=MeshIndex(wall)
    box=trimesh.creation.box(extents=[.1,.1,.1]);box.apply_translation([3,0,-.2])
    assert index.swept_collision(box.triangles,[0,0,.4],check_containment=False) is False
    box.apply_translation([-3,0,0])
    assert index.swept_collision(box.triangles,[0,0,.4],check_containment=False) is True


def test_penetration_uses_surface_distance_to_ignore_contact_tolerance():
    base=trimesh.creation.box(extents=[2,1,2])
    prop=trimesh.creation.box(extents=[.4,.2,.4]);prop.apply_translation([0,.599,0])
    index=MeshIndex(base.triangles)
    assert index.penetration_samples(prop.triangles,.01) == 0
    prop.apply_translation([0,-.05,0])
    assert index.penetration_samples(prop.triangles,.01) > 0
