"""Candidate reconstruction partitions using mask components and observed gaps.

Partitions preserve every mask pixel. They are not semantic instance labels and
do not authorize replacing an existing mesh without paired reconstruction review.
"""
import numpy as np
from scipy.ndimage import label, binary_erosion
from scipy.spatial import cKDTree


def partition_evidence(mask, points, *, maximum_parts=4):
    mask, points = np.asarray(mask, bool), np.asarray(points, float)
    if mask.ndim != 2 or points.shape != (*mask.shape, 3):
        raise ValueError('Expected matching mask and pointmap')
    components, count = label(mask, np.ones((3, 3)))
    sizes = np.bincount(components.ravel())
    major = [i for i in range(1, count+1) if sizes[i] >= max(64, mask.sum()*.05)]
    report = dict(accepted=False, reason='insufficient_separate_components',
                  components=count, major_components=len(major), pairs=[], uses_object_names=False)
    if not 2 <= len(major) <= maximum_parts:
        return [mask.copy()], report
    if any(np.any(components[edge] == i) for i in major
           for edge in ((0, slice(None)), (-1, slice(None)), (slice(None), 0), (slice(None), -1))):
        report['reason'] = 'component_touches_image_boundary'
        return [mask.copy()], report
    valid = np.isfinite(points).all(-1) & (np.linalg.norm(points, axis=-1)>1e-6)
    if np.count_nonzero(valid & mask) < mask.sum()*.95:
        report['reason'] = 'unreliable_component_depth'
        return [mask.copy()], report
    cloud=points[valid & mask]
    scale=float(np.linalg.norm(np.quantile(cloud,.95,axis=0)-np.quantile(cloud,.05,axis=0)))
    sign=float(np.sign(np.median(cloud[:,2])))
    if scale < 1e-8 or sign == 0:
        report['reason']='degenerate_component_depth'
        return [mask.copy()], report
    tolerance=scale*.02
    boundary={}
    for i in major:
        region=components==i
        coords=np.argwhere(region & ~binary_erosion(region))
        boundary[i]=coords[np.linspace(0,len(coords)-1,min(512,len(coords))).astype(int)]
    parent={i:i for i in major}
    def root(i):
        while parent[i]!=i:i=parent[i]
        return i
    for n,a in enumerate(major):
        for b in major[n+1:]:
            distance, nearest=cKDTree(boundary[b]).query(boundary[a])
            proposals=np.argsort(distance,kind='stable')[:16]
            paths=[]
            for k in proposals:
                start,end=boundary[a][k],boundary[b][nearest[k]]
                length=int(np.ceil(np.linalg.norm(end-start)))+1
                alpha=np.linspace(0,1,length)
                pixels=np.rint(start[None]+alpha[:,None]*(end-start)).astype(int)
                yy,xx=pixels.T
                gap=~mask[yy,xx]
                if gap.sum()<2 or not valid[yy[gap],xx[gap]].all():
                    paths.append(False);continue
                depths=points[tuple(np.stack([start,end]).T)][:,2]*sign
                if not np.isfinite(depths).all() or (depths <= 1e-8).any():
                    paths.append(False);continue
                # Perspective-correct depth between projected endpoints.
                expected=1/((1-alpha)/depths[0]+alpha/depths[1])
                measured=points[yy,xx,2]*sign
                if (measured[gap] <= 1e-8).any():
                    paths.append(False);continue
                behind=measured[gap] > expected[gap]+tolerance
                paths.append(bool(behind.mean() >= .9))
            separated=bool(paths and all(paths))
            report['pairs'].append(dict(component_a=a,component_b=b,
                sampled_paths=len(paths),background_gap_paths=sum(paths),
                separated=separated,closest_pixel_gap=float(distance.min())))
            if not separated:parent[root(b)]=root(a)
    groups={}
    for i in major:groups.setdefault(root(i),[]).append(i)
    if len(groups)<2:
        report['reason']='occlusion_or_connection_not_excluded'
        return [mask.copy()], report
    parts=[np.isin(components,group) for group in groups.values()]
    # Tiny islands stay in a reconstruction unit, never disappear through a
    # component-size cutoff. Assign by image distance, independent of labels.
    minor=mask & ~np.logical_or.reduce(parts)
    if minor.any():
        from scipy.ndimage import distance_transform_edt
        distances=np.stack([distance_transform_edt(~part)[minor] for part in parts])
        assigned=distances.argmin(0)
        for i,part in enumerate(parts):part[minor]=assigned==i
    assert np.array_equal(np.logical_or.reduce(parts),mask)
    report.update(accepted=True,reason='disconnected_masks_with_observed_background_gaps',
        parts=len(parts),part_areas=[int(p.sum()) for p in parts],depth_tolerance=tolerance,
        limitation='Candidate units only; thin unobserved connections may exist; paired reconstruction validation remains required')
    return parts,report
