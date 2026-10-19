import numpy as np
import trimesh
import pytest
from mapmaker.plane_occlusion import locally_enclosed_points


def fixture():
    y,x=np.mgrid[:60,:60]
    plane=np.stack([(x-30)/30,np.zeros_like(x),1+y/30],-1)
    camera=np.array([0.,2.,0.]);center=np.array([0.,0.,2.]);normal=np.array([0.,1.,0.])
    excluded=np.zeros((60,60),bool);excluded[25:35,25:35]=True
    world=plane.copy();world[excluded]=camera+.5*(plane[excluded]-camera)
    return world,~excluded,excluded,camera,center,normal,plane


def test_local_foreground_hole_has_explicit_inferred_evidence():
    world,observed,excluded,camera,center,normal,plane=fixture()
    mask,projected,evidence=locally_enclosed_points(world,observed,excluded,camera,center,normal)
    assert mask.sum()==excluded.sum() and evidence['inferred_pixels']==int(mask.sum())
    assert not mask[observed].any() and not evidence['budget_exceeded']
    np.testing.assert_allclose(projected[mask],plane[mask])


def test_behind_plane_or_missing_depth_is_not_foreground_occlusion():
    world,observed,excluded,camera,center,normal,plane=fixture()
    for factor in (1.,2.,float('nan')):
        world[excluded]=camera+factor*(plane[excluded]-camera)
        mask,_,_=locally_enclosed_points(world,observed,excluded,camera,center,normal)
        assert not mask.any()


@pytest.mark.parametrize('local_evidence_only',[False,True])
def test_open_edge_and_large_unobserved_region_are_not_extrapolated(local_evidence_only):
    world,_,_,camera,center,normal,plane=fixture()
    for cut in (30,50):
        excluded=np.zeros((60,60),bool);excluded[:,:cut]=True
        world=plane.copy();world[excluded]=camera+.5*(plane[excluded]-camera)
        mask,_,_=locally_enclosed_points(world,~excluded,excluded,camera,center,normal,local_evidence_only=local_evidence_only)
        assert not mask.any()


def test_no_object_exclusion_means_no_inferred_window_or_hole():
    world,observed,excluded,camera,center,normal,_=fixture()
    mask,_,_=locally_enclosed_points(world,observed,np.zeros_like(excluded),camera,center,normal)
    assert not mask.any()


def test_support_is_independent_of_global_rigid_frame():
    world,observed,excluded,camera,center,normal,_=fixture()
    expected,_,_=locally_enclosed_points(world,observed,excluded,camera,center,normal)
    transform=trimesh.transformations.rotation_matrix(.6,[1,2,3]);transform[:3,3]=[3,2,-1]
    moved=trimesh.transform_points(world.reshape(-1,3),transform).reshape(world.shape)
    mask,_,_=locally_enclosed_points(moved,observed,excluded,
        trimesh.transform_points(camera[None],transform)[0],trimesh.transform_points(center[None],transform)[0],transform[:3,:3]@normal)
    np.testing.assert_array_equal(mask,expected)


def test_component_budget_preserves_whole_patches_and_total_limit():
    world,_,_,camera,center,normal,plane=fixture()
    excluded=np.zeros((60,60),bool)
    for y in (5,25,45):
        for x in (5,25,45):excluded[y:y+10,x:x+10]=True
    world=plane.copy();world[excluded]=camera+.5*(plane[excluded]-camera)
    legacy,_,old=locally_enclosed_points(world,~excluded,excluded,camera,center,normal)
    assert old['budget_exceeded'] and not legacy.any()
    mask,_,evidence=locally_enclosed_points(world,~excluded,excluded,camera,center,normal,component_budget=True)
    assert 0<mask.sum()<=(~excluded).sum()*.25
    for y in (5,25,45):
        for x in (5,25,45):assert mask[y:y+10,x:x+10].sum() in (0,100)
    assert sum(c['pixels'] for c in evidence['components'] if c['accepted'])==mask.sum()


def test_independent_local_evidence_does_not_compete_with_distant_holes():
    world,observed,excluded,camera,center,normal,plane=fixture()
    first,_,_=locally_enclosed_points(world,observed,excluded,camera,center,normal,local_evidence_only=True)
    for y in (5,25,45):
        for x in (5,25,45):excluded[y:y+10,x:x+10]=True
    world=plane.copy();world[excluded]=camera+.5*(plane[excluded]-camera)
    second,_,evidence=locally_enclosed_points(world,~excluded,excluded,camera,center,normal,local_evidence_only=True)
    np.testing.assert_array_equal(first[25:35,25:35],second[25:35,25:35])
    assert second.sum()==900 and evidence['maximum_inferred_fraction'] is None


def test_enclosed_policy_requires_foreground_depth_and_never_extends_open_boundary():
    _,_,_,camera,center,normal,plane=fixture()
    for interior in (True,False):
        excluded=np.zeros((60,60),bool)
        if interior:excluded[15:45,15:45]=True
        else:excluded[:,:40]=True
        for factor in (.5,1.,2.,float('nan')):
            world=plane.copy();world[excluded]=camera+factor*(plane[excluded]-camera)
            mask,projected,evidence=locally_enclosed_points(world,~excluded,excluded,camera,center,normal,enclosed_evidence_only=True)
            if interior and factor==.5:
                assert mask.sum()==excluded.sum()
                np.testing.assert_allclose(projected[mask],plane[mask])
                assert evidence['extrapolation_outside_observed_hull'] is False
            else:assert not mask.any()


def test_enclosed_interpolation_is_rigid_frame_invariant():
    world,observed,excluded,camera,center,normal,_=fixture()
    first,_,_=locally_enclosed_points(world,observed,excluded,camera,center,normal,enclosed_evidence_only=True)
    t=trimesh.transformations.rotation_matrix(.7,[2,1,3]);t[:3,3]=[1,-3,2]
    transformed=trimesh.transform_points(world.reshape(-1,3),t).reshape(world.shape)
    second,_,_=locally_enclosed_points(transformed,observed,excluded,trimesh.transform_points(camera[None],t)[0],
        trimesh.transform_points(center[None],t)[0],t[:3,:3]@normal,enclosed_evidence_only=True)
    np.testing.assert_array_equal(first,second)
