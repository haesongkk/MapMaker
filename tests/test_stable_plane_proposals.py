import numpy as np
import pytest
from mapmaker.stable_plane_proposals import propose_plane
from mapmaker.scene_structure import fit_surfaces, observed_normals


def floor():
    y,x=np.mgrid[:70,:80]
    return np.stack([(x-40)/30,np.full_like(x,-1,dtype=float),1+y/30],axis=-1)


def test_mask_removal_does_not_reshuffle_other_pixel_identities():
    world=floor();available=np.ones(world.shape[:2],bool)
    normals,reliable=observed_normals(world,available)
    before=propose_plane(world,available,normals,reliable,.01)
    removed=before[2]['candidate_pixels'][30]
    available.flat[removed]=False
    after=propose_plane(world,available,normals,reliable,.01)
    assert len(set(before[2]['candidate_pixels'])-set(after[2]['candidate_pixels']))==1
    assert removed not in after[2]['candidate_pixels']
    for center,normal,_ in (before,after):
        np.testing.assert_allclose(abs(normal),[0,1,0],atol=1e-10)
        assert np.isclose(abs(center@normal),1)


def test_no_reliable_normals_abstains():
    world=floor()
    assert propose_plane(world,np.ones(world.shape[:2],bool),np.zeros_like(world),
                         np.zeros(world.shape[:2],bool),.01) is None


def test_stable_fit_keeps_plane_but_does_not_fill_missing_surface():
    world=floor();excluded=np.zeros(world.shape[:2],bool)
    baseline,_=fit_surfaces(world,excluded,np.eye(4),proposal_method='stable_normals')
    excluded[25:45,30:50]=True
    changed,report=fit_surfaces(world,excluded,np.eye(4),proposal_method='stable_normals')
    assert report['proposal_method']=='stable_normals' and report['seed'] is None
    assert len(baseline)==len(changed)==1
    a,b=baseline[0][1],changed[0][1]
    assert a['kind']==b['kind']=='floor'
    np.testing.assert_allclose(a['normal'],b['normal'],atol=1e-10)
    assert np.isclose(np.dot(a['point'],a['normal']),np.dot(b['point'],b['normal']))
    assert b['inferred_pixels']==0
    assert len(changed[0][0].faces)<len(baseline[0][0].faces)


def test_global_depth_proposals_are_identical_under_local_mask_changes():
    world=floor();world[...,1]+=.001*np.sin(world[...,0]*7)*np.cos(world[...,2]*5)
    excluded=np.zeros(world.shape[:2],bool)
    before,_=fit_surfaces(world,excluded,np.eye(4),proposal_method='global_stable_normals')
    excluded[25:45,30:50]=True
    after,_=fit_surfaces(world,excluded,np.eye(4),proposal_method='global_stable_normals')
    assert len(before)==len(after)==1
    for key in ('normal','point'):
        np.testing.assert_array_equal(before[0][1][key],after[0][1][key])
    assert len(after[0][0].faces)<len(before[0][0].faces)
    assert after[0][1]['inferred_pixels']==0


def test_global_fit_abstains_without_reliable_depth_neighborhoods():
    world=floor();world[::2]=np.nan
    patches,report=fit_surfaces(world,np.zeros(world.shape[:2],bool),np.eye(4),proposal_method='global_stable_normals')
    assert not patches and report['reason']=='insufficient_reliable_shared_depth'


def test_original_mask_reference_preserves_existing_fit_exactly():
    world=floor();world[...,1]+=.002*np.sin(world[...,0]*4)*np.cos(world[...,2]*3)
    reference=np.zeros(world.shape[:2],bool);reference[10:15,15:25]=True
    baseline,_=fit_surfaces(world,reference,np.eye(4),proposal_method='stable_normals')
    changed=reference.copy();changed[25:45,30:50]=True
    actual,_=fit_surfaces(world,changed,np.eye(4),proposal_method='reference_stable_normals',reference_excluded=reference)
    assert len(actual)==len(baseline)==1
    for key in ('normal','point'):
        np.testing.assert_array_equal(actual[0][1][key],baseline[0][1][key])
    assert len(actual[0][0].faces)<len(baseline[0][0].faces)
    assert actual[0][1]['inferred_pixels']==0
    with pytest.raises(ValueError,match='Reference fitting'):
        fit_surfaces(world,changed,np.eye(4),proposal_method='reference_stable_normals')
