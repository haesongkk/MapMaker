import numpy as np
import pytest
import trimesh

from mapmaker.scene_vanishing import fit_camera, image_segments, vanishing_up, reconcile_orientation
from mapmaker.scene_orientation import vertical_plane_up


@pytest.mark.parametrize('focal', [-450., 450.])
def test_camera_recovers_signed_projection_with_depth_outliers(focal):
    y, x = np.mgrid[:240, :320]
    depth = 3 + x / 320 + y / 240
    points = np.stack([(x - 160) / focal, (y - 120) / focal, np.ones_like(x)], -1) * depth[..., None]
    points[::9, ::9, :2] += 3
    report = fit_camera(points)
    assert report['accepted']
    np.testing.assert_allclose(report['matrix'], [[focal, 0, 160], [0, focal, 120], [0, 0, 1]], atol=1e-5)


@pytest.mark.parametrize('angle', [-.3, 0., .3])
def test_projected_vertical_edges_with_outliers(angle):
    matrix = np.array([[-450, 0, 320], [0, -450, 240], [0, 0, 1.]])
    rotation = trimesh.transformations.rotation_matrix(angle, [0, 0, 1])[:3, :3]
    segments = []
    for x in [-2., -1., 1., 2.]:
        p = np.array([[x, -1.5, 5], [x, 1.5, 5]]) @ rotation.T
        pixels = p @ matrix.T
        segments.append(pixels[:, :2] / pixels[:, 2, None])
    segments.extend([[[100, 100], [220, 110]], [[120, 330], [320, 310]]])
    report = vanishing_up(segments, matrix, [640, 480])
    assert report['accepted']
    assert np.dot(report['up'], rotation @ [0, 1, 0]) > .9999


def test_repeated_edges_in_narrow_strip_do_not_certify_up():
    segments = [[[x, 50], [x, 430]] for x in range(300, 320, 2)]
    matrix = [[-450, 0, 320], [0, -450, 240], [0, 0, 1]]
    assert not vanishing_up(segments, matrix, [640, 480])['accepted']


def test_conflicting_lines_and_surfaces_abstain():
    surface = dict(accepted=True, up=[0, 1, 0], orthogonal_fraction=.6)
    lines = dict(accepted=True, up=[.5, np.sqrt(.75), 0])
    assert reconcile_orientation(surface, lines)['reason'] == 'surface_and_vanishing_disagree'
    assert not reconcile_orientation(surface, lines)['accepted']


def test_blank_image_has_no_vanishing_evidence():
    assert len(image_segments(np.full((240, 320, 3), 128, np.uint8))) == 0


def test_detector_recovers_long_distributed_edges():
    image = np.full((240, 320, 3), 128, np.uint8)
    for x in [30, 100, 220, 290]:
        image[20:220, x:x+3] = 0
    segments = image_segments(image)
    report = vanishing_up(segments, [[-300, 0, 160], [0, -300, 120], [0, 0, 1]], [320, 240])
    assert report['accepted']
    assert np.dot(report['up'], [0, 1, 0]) > .999


def test_two_vertical_walls_constrain_up_but_one_does_not():
    y,x = np.mgrid[:100,:100]
    points = np.stack([(x-50)/25, (y-50)/25, np.full_like(x, 3)], -1)
    assert not vertical_plane_up(points)['accepted']
    points[:,50:,0] = 0
    points[:,50:,2] = 3 + (x[:,50:]-50)/25
    report = vertical_plane_up(points)
    assert report['accepted']
    assert np.dot(report['up'], [0,1,0]) > .999


def test_finer_supported_lines_are_used_without_certifying_conflicting_scales():
    from mapmaker.scene_vanishing import select_line_scale
    weak = dict(accepted=False,reason='insufficient_image_lines',maximum_size=320)
    good = dict(accepted=True,reason='image_line_vanishing_consensus',maximum_size=960,
        up=[0,1,0],inlier_lines=6,length_fraction=.5,image_span=[.7,.8])
    assert select_line_scale([weak,good])['maximum_size'] == 960
    conflict = dict(good,maximum_size=640,up=[.3,np.sqrt(.91),0])
    result = select_line_scale([weak,good,conflict])
    assert not result['accepted'] and result['reason']=='vanishing_scales_disagree'
