import numpy as np
import trimesh
from mapmaker.scene_contact_restoration import restore_contact_pose
from mapmaker.reconstruction_context import contact_context_screen


def fixture(shift):
    old=trimesh.creation.box();new=old.copy();new.apply_translation([0,shift,0])
    prop=trimesh.creation.box(extents=[.3,.2,.3]);prop.apply_translation([0,.6,0])
    return old.triangles.copy(),new.triangles.copy(),prop.triangles.copy()


def test_small_contact_gap_has_rigid_bounded_label_independent_proposal():
    old,new,other=fixture(-.03);unchanged=new.copy()
    result=restore_contact_pose(old,new,[('plant',other)],.005)
    assert result['proposed'] and result['requires_source_and_collision_validation']
    matrix=np.array(result['transform'])
    np.testing.assert_allclose(matrix[:3,:3].T@matrix[:3,:3],np.eye(3),atol=1e-10)
    moved=trimesh.transform_points(new.reshape(-1,3),matrix).reshape(-1,3,3)
    assert contact_context_screen(old,moved,[('x',other)],.005)['accepted']
    renamed=restore_contact_pose(old,new,[('',other)],.005)
    np.testing.assert_allclose(matrix,renamed['transform'])
    np.testing.assert_array_equal(new,unchanged)
    assert result['quality_gate_passed'] is False


def test_large_repair_and_no_observed_contacts_abstain():
    old,new,other=fixture(-.5)
    result=restore_contact_pose(old,new,[('x',other)],.005)
    assert not result['proposed'] and result['reason']=='rigid_motion_budget_exceeded'
    assert not restore_contact_pose(old,new,[],.005)['proposed']


def test_fitting_and_final_screen_use_the_same_contact_sample_budget():
    old,new,other=fixture(-.01)
    mesh=trimesh.Trimesh(other.reshape(-1,3),np.arange(len(other)*3).reshape(-1,3),process=True)
    for _ in range(3):mesh=mesh.subdivide()
    for budget in (37,512):
        others=[('any',mesh.triangles)]
        initial=contact_context_screen(old,new,others,.005,samples=budget)
        proposal=restore_contact_pose(old,new,others,.005,samples=budget)
        assert proposal['target_count']==sum(c['observed_contacts'] for c in initial['checks'])
        for step in proposal['iterations']:
            assert [c.get('sampled_points') for c in step['contact_screen']['checks']]==[c.get('sampled_points') for c in initial['checks']]
