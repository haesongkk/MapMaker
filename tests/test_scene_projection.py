import numpy as np
import pytest
from mapmaker.scene_projection import silhouette_evidence, inconsistent_spanning_context
from test_scene_geometry_v6 import room_pointmap


def image_quad(points):
    # Constant-depth rectangle spanning the pointmap's fitted camera frame.
    from mapmaker.scene_vanishing import fit_camera
    matrix = np.asarray(fit_camera(points)['matrix'])
    h, w = points.shape[:2]
    pixels = np.array([[0,0,1], [w-1,0,1], [w-1,h-1,1], [0,h-1,1]])
    vertices = pixels @ np.linalg.inv(matrix).T * 4
    return vertices[[[0,1,2],[0,2,3]]]


@pytest.mark.parametrize('scale', [.1, 1., 10.])
def test_multiplane_frame_and_gross_overcompletion_required_together(scale):
    points = room_pointmap(100)*scale
    mask = np.zeros((100,100),bool)
    mask[:5,:] = True
    mask[:, :5] = True
    mask[:, -5:] = True
    faces = image_quad(points)*scale
    report = inconsistent_spanning_context(mask, points, faces)
    assert report and report['observed_context']
    assert report['projection']['silhouette_outside_mask_fraction'] > .8
    # A solid silhouette must remain an object regardless of size or depth planes.
    assert inconsistent_spanning_context(np.ones_like(mask), points, faces) is None
    # A small object with a poorly fitting mesh is not a room/context region.
    tiny = np.zeros_like(mask); tiny[40:55,40:55] = True
    assert inconsistent_spanning_context(tiny, points, faces) is None


def test_sparse_planar_frame_does_not_become_room_context():
    y,x=np.mgrid[:100,:100]
    points=np.stack([(x-50)/50,(y-50)/50,np.ones_like(x)],-1)*3
    mask=np.zeros((100,100),bool);mask[:5,:]=True;mask[:,:5]=True;mask[:,-5:]=True
    assert inconsistent_spanning_context(mask,points,image_quad(points)) is None


def test_matching_silhouette_and_wrong_camera_halfspace():
    points=room_pointmap(100);faces=image_quad(points)
    evidence=silhouette_evidence(faces,points,np.ones((100,100),bool))
    assert evidence['accepted'] and evidence['silhouette_iou'] > .98
    assert not silhouette_evidence(-faces,points,np.ones((100,100),bool))['accepted']
