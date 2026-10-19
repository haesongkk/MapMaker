import numpy as np
import pytest
import trimesh
from mapmaker.scene_extension_guard import guard_plane_extension,triangle_keys


def patch(x):
    return trimesh.Trimesh(vertices=[[x,0,0],[x+1,0,0],[x,0,1],[x+1,0,1]],faces=[[0,1,2],[1,3,2]],process=False)


def test_rejects_whole_intersecting_addition_preserves_baseline_and_clear_addition():
    baseline=patch(0);candidate=trimesh.util.concatenate([baseline,patch(2),patch(4)])
    body=trimesh.creation.box(extents=[.4,1,.4]);body.apply_translation([2.4,0,.4])
    original=candidate.vertices.copy()
    result,e=guard_plane_extension(baseline,candidate,[body.triangles],[0,1,0],[0,0,0],.001)
    assert e['rejected_added_triangles']==2 and e['retained_added_triangles']==2
    assert set(triangle_keys(baseline.triangles)).issubset(triangle_keys(result.triangles))
    np.testing.assert_array_equal(original,candidate.vertices)


def test_contact_is_not_penetration_and_missing_baseline_refused():
    baseline=patch(0);candidate=trimesh.util.concatenate([baseline,patch(2)])
    body=trimesh.creation.box(extents=[.4,1,.4]);body.apply_translation([2.4,.5,.4])
    result,e=guard_plane_extension(baseline,candidate,[body.triangles],[0,1,0],[0,0,0],.001)
    assert len(result.faces)==4 and e['rejected_added_triangles']==0
    with pytest.raises(ValueError,match='preserve every baseline'):
        guard_plane_extension(baseline,patch(2),[],[0,1,0],[0,0,0],.001)


def test_addition_inside_closed_volume_and_unknown_checks_are_withheld(monkeypatch):
    baseline=patch(0);candidate=trimesh.util.concatenate([baseline,patch(2)])
    body=trimesh.creation.box(extents=[2,2,2]);body.apply_translation([2.5,0,.5])
    _,e=guard_plane_extension(baseline,candidate,[body.triangles],[0,1,0],[0,0,0],.001)
    assert e['rejected_added_triangles']==2
    assert e['components'][0]['checks'][0]['result']=='intersection'
    monkeypatch.setattr('mapmaker.scene_extension_guard.MeshIndex.swept_collision',lambda *args,**kw:None)
    _,e=guard_plane_extension(baseline,candidate,[body.triangles],[0,1,0],[0,0,0],.001)
    assert e['rejected_added_triangles']==2
    assert e['components'][0]['checks'][0]['result']=='unknown'


def test_clear_open_patch_inside_object_bounds_is_not_unknown():
    baseline=patch(0);candidate=trimesh.util.concatenate([baseline,patch(2)])
    left=trimesh.creation.box(extents=[.1,1,2]);left.apply_translation([1.9,0,.5])
    right=left.copy();right.apply_translation([1.2,0,0])
    body=trimesh.util.concatenate([left,right])
    result,e=guard_plane_extension(baseline,candidate,[body.triangles],[0,1,0],[0,0,0],.001)
    assert len(result.faces)==4
    assert e['components'][0]['checks'][0]['result']=='clear'


def test_localized_conflicts_preserve_distant_clear_faces_in_same_component():
    baseline=patch(0)
    extension=trimesh.util.concatenate([patch(2),patch(3)]);extension.merge_vertices()
    candidate=trimesh.util.concatenate([baseline,extension])
    body=trimesh.creation.box(extents=[.4,1,.4]);body.apply_translation([2.4,0,.4])
    result,e=guard_plane_extension(baseline,candidate,[body.triangles],[0,1,0],[0,0,0],.001,localize_conflicts=True)
    assert e['retained_added_triangles']==2 and e['rejected_added_triangles']==2
    assert set(triangle_keys(patch(3).triangles)).issubset(triangle_keys(result.triangles))
