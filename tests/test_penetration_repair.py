from mapmaker.scene_collision import certified_penetration_repair
import numpy as np
import trimesh
import pytest
from mapmaker.scene_collision import MeshIndex,initial_penetration_evidence


def test_only_measured_initial_intersections_can_explain_blocked_paths():
    repaired=dict(before='intersection',after='clear',path_result='intersection',penetration_confirmed=True)
    unaffected=dict(before='clear',after='clear',path_result='clear')
    assert certified_penetration_repair([repaired,unaffected])
    assert not certified_penetration_repair([])
    assert not certified_penetration_repair([unaffected])
    for changed in (dict(repaired,after='intersection'),dict(repaired,after='unknown'),
                    dict(repaired,before='unknown'),dict(repaired,path_result='unknown'),dict(repaired,penetration_confirmed=False),
                    dict(unaffected,path_result='intersection')):
        assert not certified_penetration_repair([repaired,changed])


def test_measured_shallow_intersection_can_be_repaired_by_uniform_scale():
    fixed=trimesh.creation.box()
    moving=trimesh.creation.box();moving.apply_translation([.95,0,0])
    transform=np.diag([.8,.8,.8,1.]);transform[0,3]=.19
    end=trimesh.transform_points(moving.vertices,transform)[moving.faces]
    index=MeshIndex(fixed.triangles)
    assert index.swept_collision(moving.triangles,np.zeros(3)) is True
    assert index.swept_collision(end,np.zeros(3)) is False
    assert index.similarity_swept_collision(moving.triangles,transform) is True
    evidence=initial_penetration_evidence(index,moving.triangles)
    assert evidence['penetration_confirmed']
    assert certified_penetration_repair([dict(before='intersection',after='clear',path_result='intersection',**evidence)])


def test_touching_surfaces_are_not_penetration_repair_candidates():
    fixed=trimesh.creation.box()
    moving=trimesh.creation.box();moving.apply_translation([1.,0,0])
    index=MeshIndex(fixed.triangles)
    assert index.swept_collision(moving.triangles,np.zeros(3)) is True
    evidence=initial_penetration_evidence(index,moving.triangles)
    assert not evidence['penetration_confirmed']
    assert not certified_penetration_repair([dict(before='intersection',after='clear',path_result='intersection',**evidence)])


def test_closed_volume_proves_intersection_missed_by_sparse_inside_samples():
    pytest.importorskip('manifold3d')
    fixed=trimesh.creation.box();moving=trimesh.creation.box()
    moving.apply_translation([.9999,0,0])
    evidence=initial_penetration_evidence(MeshIndex(fixed.triangles),moving.triangles)
    assert evidence['initial_inside_samples']==[0,0]
    assert evidence['penetration_confirmed']
    assert evidence['penetration_method']=='verified_positive_closed_boolean_volume'
    assert evidence['closed_volume_evidence']['before']==pytest.approx(.0001)
