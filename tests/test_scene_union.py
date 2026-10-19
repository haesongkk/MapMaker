import numpy as np
import pytest
import trimesh
pytest.importorskip('manifold3d')
from mapmaker.scene_union import union_colored_solids


def box(color,offset):
    m=trimesh.creation.box();m.visual.vertex_colors=color;m.apply_translation(offset);return m


def test_union_preserves_exterior_and_colors_without_double_volume():
    a=box([255,0,0,255],[0,0,0]);b=box([0,0,255,255],[.5,0,0]);before=a.vertices.copy()
    result,evidence=union_colored_solids(a,b)
    assert evidence['union_volume']==pytest.approx(1.5)
    assert evidence['overlap_volume']==pytest.approx(.5)
    np.testing.assert_array_equal(a.vertices,before)
    colors=result.visual.vertex_colors
    assert np.any(np.all(colors==[255,0,0,255],axis=1))
    assert np.any(np.all(colors==[0,0,255,255],axis=1))
    assert not evidence['identity_authorized']


def test_open_surface_is_not_silently_filled():
    a=box([255,0,0,255],[0,0,0]);b=a.copy();b.update_faces(np.arange(len(b.faces)-1))
    with pytest.raises(ValueError,match='closed'):union_colored_solids(a,b)
