import numpy as np
import pytest
import trimesh
from mapmaker.scene_geometry import support_translation, surface_height
from mapmaker.scene_orientation import estimate_up
from test_scene_geometry_v6 import room_pointmap
from mapmaker.mask_geometry import structural_mask_evidence, partial_duplicate
from mapmaker.scene_placement import remove_object_tree
from mapmaker.scene_structure import enclosed_occlusion_points


def test_four_feet_on_open_patches_without_center_support():
    patches = []
    feet = []
    for x in (-.8, .8):
        for z in (-.8, .8):
            patch = trimesh.Trimesh(vertices=[[x-.2,0,z-.2],[x+.2,0,z-.2],[x+.2,0,z+.2],[x-.2,0,z+.2]], faces=[[0,1,2],[0,2,3]])
            patches.extend(patch.triangles)
            foot = trimesh.creation.box(extents=[.1,1,.1])
            foot.apply_translation([x,.6,z]); feet.extend(foot.vertices)
    assert surface_height(np.array(patches), [0,0]) is None
    delta, evidence = support_translation(np.array(feet), np.array(patches), .2, .01)
    np.testing.assert_allclose(delta, [0,-.1,0], atol=1e-8)
    # Removing one foot's support must not be interpreted as a stable contact.
    delta, evidence = support_translation(np.array(feet), np.array(patches)[:-2], .2, .01)
    assert delta is None and evidence['reason'] == 'missing_support_surface'


def test_bounded_ray_chooses_lower_shelf_and_preserves_correct_contact():
    floor = trimesh.creation.box(extents=[2,.1,2]); floor.apply_translation([0,-.05,0])
    shelf = floor.copy(); shelf.apply_translation([0,2,0])
    faces = np.concatenate([floor.triangles, shelf.triangles])
    item = trimesh.creation.box(extents=[.5,.5,.5]); item.apply_translation([0,.25,0])
    delta, _ = support_translation(item.vertices, faces, .2, .01)
    np.testing.assert_allclose(delta, [0,0,0], atol=1e-8)


@pytest.mark.parametrize('angle', [-.3, 0., .3])
@pytest.mark.parametrize('scale', [.1, 1., 10.])
def test_surface_orientation_from_tilted_room(angle, scale):
    rotation = trimesh.transformations.rotation_matrix(angle, [0,0,1])[:3,:3]
    points = room_pointmap() @ rotation.T * scale
    evidence = estimate_up(points)
    assert evidence['accepted']
    assert np.dot(evidence['up'], rotation @ [0,1,0]) > .995


def test_single_wall_does_not_determine_up():
    y,x = np.mgrid[:80,:80]
    points = np.stack([x/80,y/80,np.ones_like(x)], axis=-1)
    assert not estimate_up(points)['accepted']
    assert not estimate_up(np.full_like(points, np.nan))['accepted']


def test_structural_routing_requires_spatial_and_multiplane_evidence():
    points = room_pointmap(100)
    mask = np.zeros((100,100),bool)
    mask[:8,:] = True; mask[:75,:8] = True; mask[:75,-8:] = True
    assert structural_mask_evidence(mask,points) is not None
    # A solid furniture silhouette spanning the same borders must remain an object.
    solid=mask.copy();solid[:75,:]=True
    assert structural_mask_evidence(solid,points) is None
    # A sparse planar frame is not a multi-plane room just because it spans the image.
    y,x=np.mgrid[:100,:100]
    flat=np.stack([x/100,y/100,np.ones_like(x)],axis=-1)
    assert structural_mask_evidence(mask,flat) is None
    # A small inner object cannot be routed away as architecture.
    small=np.zeros_like(mask);small[20:40,20:40]=True
    assert structural_mask_evidence(small,points) is None


def test_removing_structural_object_does_not_leave_orphan_export_nodes():
    scene=trimesh.Scene(base_frame='Scene')
    scene.graph.update(frame_from='Scene',frame_to='broad')
    scene.add_geometry(trimesh.creation.box(),parent_node_name='broad',node_name='broad_mesh')
    scene.add_geometry(trimesh.creation.box(),node_name='keep')
    remove_object_tree(scene,'broad')
    assert 'broad' not in scene.graph.nodes
    assert 'broad_mesh' not in scene.graph.nodes
    assert scene.export(file_type='glb')


def test_only_bounded_foreground_holes_extend_observed_plane():
    y,x=np.mgrid[:80,:80]
    world=np.stack([(x-40)/40,(y-40)/40,np.full_like(x,3)],axis=-1)
    excluded=np.zeros((80,80),bool);excluded[37:43,37:43]=True
    observed=~excluded
    world[excluded]*=.5
    fill, projected=enclosed_occlusion_points(world,observed,excluded,np.zeros(3),[0,0,3],[0,0,1])
    assert np.array_equal(fill,excluded)
    np.testing.assert_allclose(projected[fill,2],3)
    # A window/opening whose depth is behind the wall is not a foreground occluder.
    world[excluded]*=4
    fill,_=enclosed_occlusion_points(world,observed,excluded,np.zeros(3),[0,0,3],[0,0,1])
    assert not fill.any()
    # No evidence on one side: do not invent a continuation out of the frame.
    excluded[:,:5]=True;observed=~excluded;world[excluded]*=.1
    fill,_=enclosed_occlusion_points(world,observed,excluded,np.zeros(3),[0,0,3],[0,0,1])
    assert not fill[:,:5].any()


def test_curved_surface_part_keeps_real_depth_boundary():
    y,x=np.mgrid[:100,:100]
    points=np.stack([x/100,y/100,1+.3*(x/100)**2],axis=-1)
    large=np.zeros((100,100),bool);large[10:90,10:90]=True
    small=np.zeros_like(large);small[10:30,10:90]=True
    rgb=np.full((100,100,3),128,np.uint8)
    assert partial_duplicate(small,large,points,rgb)
    points[small,2]+=.2
    assert not partial_duplicate(small,large,points,rgb)
