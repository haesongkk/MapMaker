import numpy as np
import pytest
import trimesh

from mapmaker.scene_collision import MeshIndex


@pytest.mark.parametrize('scale', [.1, 1., 10.])
def test_first_contact_stops_before_rough_surface_without_relaxing_collision(scale):
    prop = trimesh.creation.box(extents=[.4, .6, .4])
    prop.apply_translation([0, .4, 0])
    support = trimesh.creation.box(extents=[2, .1, 2])
    support.apply_translation([0, -.049, 0])
    moving, fixed = prop.triangles * scale, support.triangles * scale
    index = MeshIndex(fixed)
    delta = np.array([0, -.1, 0]) * scale
    refined, evidence = index.first_foot_contact(moving, delta, .002 * scale)
    assert refined is not None
    assert evidence['reason'] == 'finite_mesh_first_foot_contact'
    assert refined[1] == pytest.approx(-.099 * scale, abs=1e-7 * scale)
    assert index.swept_collision(moving, refined, check_containment=False) is False
    assert index.swept_collision(moving, delta, check_containment=False) is True


def test_upper_shelf_body_collision_cannot_be_reclassified_as_foot_contact():
    prop = trimesh.creation.box(extents=[.4, .6, .4])
    prop.apply_translation([0, .4, 0])
    # Horizontal patch hits the top of the body before the desired foot height.
    shelf = trimesh.Trimesh(vertices=[[-1,.65,-1],[1,.65,-1],[1,.65,1],[-1,.65,1]],
                             faces=[[0,1,2],[0,2,3]], process=False)
    refined, evidence = MeshIndex(shelf.triangles).first_foot_contact(
        prop.triangles, [0,-.1,0], .002)
    assert refined is None
    assert evidence['reason'] == 'initial_contact_not_clear'


def test_remote_obstruction_outside_contact_tolerance_abstains():
    prop = trimesh.creation.box(extents=[.4,.6,.4])
    prop.apply_translation([0,.5,0])
    floor = trimesh.creation.box(extents=[2,.1,2])
    refined, evidence = MeshIndex(floor.triangles).first_foot_contact(
        prop.triangles, [0,-.2,0], .002)
    assert refined is None
    assert evidence['reason'] == 'contact_adjustment_out_of_bounds'
