"""Experimental coordinate-stable, observed-normal room plane proposals."""
import numpy as np


def propose_plane(world, available, normals, reliable, tolerance, *, budget=256, normal_consistent=False):
    """Use pixel identities rather than positions in a changing masked array.

    Candidates remain correlated depth observations. This supplies a proposal,
    never permission to fill holes or certify support under an occluder.
    """
    world=np.asarray(world,float);available=np.asarray(available,bool)
    normals=np.asarray(normals,float);reliable=np.asarray(reliable,bool)
    if (world.ndim!=3 or world.shape[-1]!=3 or normals.shape!=world.shape
            or available.shape!=world.shape[:2] or reliable.shape!=available.shape
            or not np.isfinite(tolerance) or tolerance<=0 or budget<1):
        raise ValueError('Expected matching observations and a positive proposal budget/tolerance')
    eligible=available & reliable & np.isfinite(world).all(-1) & np.isfinite(normals).all(-1)
    eligible &= (abs(normals[...,1])<=.18)|(abs(normals[...,1])>=.96)
    ids=np.flatnonzero(eligible)
    if not len(ids):return None
    # SplitMix64 ranking: removing a pixel never reassigns another pixel's key.
    rank=ids.astype(np.uint64)+np.uint64(0x9e3779b97f4a7c15)
    rank=(rank^(rank>>30))*np.uint64(0xbf58476d1ce4e5b9)
    rank=(rank^(rank>>27))*np.uint64(0x94d049bb133111eb)
    rank ^= rank>>31
    ids=ids[np.argsort(rank,kind='stable')[:budget]]
    anchors=world.reshape(-1,3)[ids];directions=normals.reshape(-1,3)[ids]
    cloud_mask=eligible if normal_consistent else available & np.isfinite(world).all(-1)
    cloud=world[cloud_mask]
    cloud_normals=normals[cloud_mask]
    if len(cloud)<100:return None
    residual=np.abs(directions@cloud.T-np.sum(anchors*directions,axis=1)[:,None])
    matches=residual<tolerance
    if normal_consistent:matches &= abs(directions@cloud_normals.T)>=np.cos(np.deg2rad(15))
    scores=np.count_nonzero(matches,axis=1)
    winner=int(np.argmax(scores))
    if scores[winner]<max(80,len(cloud)*.06):return None
    keep=matches[winner]
    for _ in range(3):
        inliers=cloud[keep]
        if len(inliers)<80:return None
        center=inliers.mean(axis=0)
        _,_,vh=np.linalg.svd(inliers-center,full_matrices=False)
        normal=vh[-1]
        updated=abs((cloud-center)@normal)<tolerance
        if normal_consistent:updated &= abs(cloud_normals@normal)>=np.cos(np.deg2rad(15))
        if np.array_equal(updated,keep):break
        keep=updated
    return center,normal,dict(method='fixed_pixel_normal_proposals_all_inlier_refit',normal_consistent=normal_consistent,
        candidate_pixels=ids.tolist(),winning_pixel=int(ids[winner]),inlier_points=int(len(inliers)))
