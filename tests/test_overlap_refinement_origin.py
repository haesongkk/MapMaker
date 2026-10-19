"""A depth-fit proposal must never be replayed onto a different starting pose."""
import numpy as np
import pytest
import trimesh
from PIL import Image

from mapmaker.scene_overlap_refinement import refine_overlaps


@pytest.mark.parametrize('record_origin', [False, True])
def test_unrecorded_or_changed_candidate_origin_abstains(tmp_path, record_origin):
    pytest.importorskip('manifold3d')
    Image.fromarray(np.ones((8, 8), dtype=np.uint8)*255).save(tmp_path/'mask.png')
    scene = trimesh.Scene()
    matrix = np.eye(4); matrix[1, 3] = .2
    scene.add_geometry(trimesh.creation.box(), node_name='opaque', transform=matrix)
    obj = dict(id='opaque', mask='mask.png', placement={})
    pose = dict(object_id='opaque', applied=False, rejected_collision_candidates=[{}])
    if record_origin:
        pose['starting_world_transform'] = np.eye(4).tolist()
    placement = dict(common_transform=np.eye(4).tolist(), pose_refinement=dict(records=[pose]), contact_tolerance=.01)
    result = refine_overlaps(tmp_path, scene, [obj], np.ones((8, 8, 3)), placement, dict(surfaces=[]))
    assert not result['changes']
    assert result['records'][0]['reason'] == 'candidate_origin_changed_or_unrecorded'
    np.testing.assert_array_equal(scene.graph['opaque'][0], matrix)
