import numpy as np
import trimesh
from mapmaker.reconstruction_context import contact_context_screen,SavedContactContext
from mapmaker.scene_run import sha


def test_contact_loss_veto_is_name_and_order_independent_and_not_quality_proof():
    old=trimesh.creation.box();new=old.copy();new.apply_translation([0,-.1,0])
    prop=trimesh.creation.box(extents=[.2]*3);prop.apply_translation([0,.6,0])
    far=prop.copy();far.apply_translation([5,0,0])
    result=contact_context_screen(old.triangles,new.triangles,[('plant',prop.triangles),('tv',far.triangles)],.01)
    renamed=contact_context_screen(old.triangles,new.triangles,[('',far.triangles),('x',prop.triangles)],.01)
    assert not result['accepted'] and not renamed['accepted']
    unchanged=contact_context_screen(old.triangles,old.triangles,[('x',prop.triangles)],.01)
    assert unchanged['accepted'] and unchanged['quality_gate_passed'] is False
    empty=contact_context_screen(old.triangles,new.triangles,[],.01)
    assert empty['quality_gate_passed'] is False


def test_saved_context_invalidates_cached_geometry_after_asset_or_pose_change(tmp_path):
    path=tmp_path/'body.glb';trimesh.creation.box().export(path)
    obj=dict(id='arbitrary',asset='body.glb',asset_sha256=sha(path),
        pose=dict(rotation=[1,0,0,0],translation=[0,0,0],scale=[1,1,1]))
    context=SavedContactContext(tmp_path,[obj],lambda _:None)
    before=context.faces(obj).copy()
    obj['pose']['translation']=[1,0,0]
    np.testing.assert_allclose(context.faces(obj),before+[1,0,0])
    trimesh.creation.box(extents=[2]*3).export(path);obj['asset_sha256']=sha(path)
    assert not np.allclose(context.faces(obj),before+[1,0,0])
