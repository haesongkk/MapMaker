import numpy as np
from mapmaker.stable_plane_proposals import propose_plane


def test_nearby_perpendicular_samples_do_not_tilt_supported_plane():
    z,x=np.mgrid[-1:1:30j,-1:1:30j]
    world=np.stack([x,np.zeros_like(x),z],-1)
    normals=np.zeros_like(world);normals[...,1]=1
    world[-5:,:,0]=.7;world[-5:,:,1]=np.linspace(0,.02,5)[:,None]
    normals[-5:]=[1,0,0]
    available=np.ones(x.shape,bool);without=available.copy();without[-5:]=False
    results=[propose_plane(world,m,normals,available,.03,normal_consistent=True) for m in (available,without)]
    assert all(r is not None for r in results)
    for center,normal,evidence in results:
        assert abs(center[1])<1e-12 and abs(abs(normal[1])-1)<1e-12
        assert evidence['normal_consistent']
    np.testing.assert_allclose(results[0][0],results[1][0],atol=1e-12)
