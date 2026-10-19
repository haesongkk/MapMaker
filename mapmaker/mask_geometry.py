"""Conservative label-free partial-mask redundancy evidence."""
import numpy as np
import hashlib


def structural_mask_evidence(mask, points, *, minimum_borders=3):
    """Recognize a sparse image-spanning, multi-plane region, not a solid object.

    Border extent alone is never enough: require distinct observed planes too.
    This conservative geometric routing remains fallible and retains the mask.
    """
    ys, xs = np.where(mask)
    if not len(xs):
        return None
    h, w = mask.shape
    span = [(xs.max()-xs.min()+1)/w, (ys.max()-ys.min()+1)/h]
    borders = sum((xs.min() <= w*.01, xs.max() >= w*.99-1,
                   ys.min() <= h*.01, ys.max() >= h*.99-1))
    occupancy = float(mask.sum()/((xs.max()-xs.min()+1)*(ys.max()-ys.min()+1)))
    if borders < minimum_borders or min(span) < .6 or max(span) < .9 or occupancy > .4:
        return None
    valid = mask & np.isfinite(points).all(axis=-1) & (np.linalg.norm(points, axis=-1) > 1e-6)
    cloud = points[valid]
    if len(cloud) < 200 or len(cloud) < mask.sum()*.9:
        return None
    cloud = cloud[::max(1, len(cloud)//2000)][:2000]
    scale = float(np.linalg.norm(np.quantile(cloud,.95,axis=0)-np.quantile(cloud,.05,axis=0)))
    if scale < 1e-6:
        return None
    remaining = cloud.copy(); planes = []; rng = np.random.default_rng(14)
    for _ in range(3):
        if len(remaining) < 100:
            break
        best = None
        for _ in range(96):
            a,b,c = remaining[rng.choice(len(remaining),3,replace=False)]
            n = np.cross(b-a,c-a); length = np.linalg.norm(n)
            if length < 1e-10: continue
            n /= length
            inside = abs((remaining-a)@n) < scale*.008
            if best is None or inside.sum() > best[0]: best=(int(inside.sum()),inside,n)
        if best is None or best[0] < len(cloud)*.15:
            break
        planes.append(dict(fraction=best[0]/len(cloud),normal=best[2].tolist()))
        remaining=remaining[~best[1]]
    distinct = any(abs(np.dot(a['normal'],b['normal'])) < .8 for i,a in enumerate(planes) for b in planes[i+1:])
    covered = sum(p['fraction'] for p in planes)
    if not distinct or covered < .7:
        return None
    return dict(reason='sparse_image_spanning_multiplane_region', borders=int(borders),
                image_span=span, bbox_occupancy=occupancy, plane_coverage=covered, planes=planes,
                confidence_kind='conjunctive_geometric_evidence_not_probability',
                limitation='May confuse cropped open architectural furniture; retain source mask for review')


def review_composites(masks, points):
    """Only suppress a disconnected union fully represented by independent masks.

    Broad connected masks remain review candidates, not automatic deletions.
    No image-specific regions, object names, or absolute depth units are used.
    """
    keys = sorted(masks, key=lambda k: (int(masks[k].sum()),
                  hashlib.sha256(np.packbits(masks[k]).tobytes()).hexdigest()))
    reviews = []
    suppressed = set()
    valid = np.isfinite(points).all(axis=-1) & (np.linalg.norm(points, axis=-1) > 1e-6)
    for parent in keys:
        mask = masks[parent]
        area = int(mask.sum())
        if not area:
            continue
        children = [k for k in keys if k != parent and k not in suppressed
                    and 0 < masks[k].sum() < area * .8
                    and np.count_nonzero(masks[k] & mask) / masks[k].sum() >= .98]
        if len(children) < 2:
            continue
        union = np.logical_or.reduce([masks[k] for k in children])
        coverage = float(np.count_nonzero(union & mask) / area)
        disjoint = all(not np.any(masks[a] & masks[b])
                       for i, a in enumerate(children) for b in children[i+1:])
        # Any uncovered parent pixels could be a connecting frame or body.
        # Preserve that parent: near-total coverage alone cannot prove redundancy.
        exact_union = np.array_equal(union, mask)
        separated = disjoint
        for child in children:
            m = masks[child]
            h, w = m.shape
            pad = np.pad(m, 1)
            dilated = np.logical_or.reduce([pad[y:y+h, x:x+w] for y in range(3) for x in range(3)])
            if np.any(dilated & union & ~m):
                separated = False
        reliable_depth = all(np.count_nonzero(masks[k] & valid) >= .95 * masks[k].sum() for k in children)
        # Independent depth extents must be separated, not simply different colors.
        intervals = [np.quantile(points[masks[k] & valid, 2], [.05, .95])
                     for k in children if np.any(masks[k] & valid)]
        depth_separated = len(intervals) == len(children) and all(
            a[1] < b[0] or b[1] < a[0] for i, a in enumerate(intervals) for b in intervals[i+1:])
        redundant = bool(exact_union and separated and reliable_depth and depth_separated)
        reviews.append(dict(object_id=parent, child_ids=children, child_coverage=coverage,
                            exact_union=exact_union, separated=bool(separated),
                            reliable_depth=bool(reliable_depth), depth_separated=bool(depth_separated),
                            action='suppress' if redundant else 'retain_ambiguous',
                            reason='disconnected_depth_separated_union' if redundant else 'composite_evidence_insufficient'))
        if redundant:
            suppressed.add(parent)
    return reviews


def erode(mask):
    h,w = mask.shape
    padded = np.pad(mask, 1)
    return np.logical_and.reduce([padded[y:y+h,x:x+w] for y in range(3) for x in range(3)])


def partial_duplicate(small, large, points, rgb):
    """Reject only a contained, shared-boundary, coplanar, low-contrast part.

    Small independent objects, depth discontinuities and visible color boundaries
    stay intact. This is evidence of redundancy, not a semantic part classifier.
    """
    small, large = np.asarray(small,bool), np.asarray(large,bool)
    if small.shape != large.shape or points.shape != (*small.shape,3) or rgb.shape != (*small.shape,3):
        raise ValueError('Mask, pointmap and RGB resolutions must match')
    area = int(small.sum())
    if area < 64 or area/max(1,int(large.sum())) < .15:
        return False
    if np.count_nonzero(small & large)/area < .95:
        return False
    boundary = small & ~erode(small)
    large_edge = large & ~erode(large)
    if np.count_nonzero(boundary & large_edge)/max(1,int(boundary.sum())) < .5:
        return False
    h,w = small.shape
    p = np.pad(small,1)
    dilated = np.logical_or.reduce([p[y:y+h,x:x+w] for y in range(3) for x in range(3)])
    ring = dilated & large & ~small
    valid = np.isfinite(points).all(axis=-1) & (np.linalg.norm(points,axis=-1)>1e-6)
    interior, outside = points[small & valid], points[ring & valid]
    if len(interior)<64 or len(outside)<16:
        return False
    interior=interior[::max(1,len(interior)//2048)]
    center=interior.mean(axis=0)
    _, singular, vh=np.linalg.svd(interior-center,full_matrices=False)
    if singular[1] < 1e-8:
        return False
    scale=max(float(np.linalg.norm(np.ptp(interior,axis=0))),1e-6)
    tolerance=scale*.01
    planar = (np.quantile(abs((interior-center)@vh[-1]),.95)<=tolerance and
              np.quantile(abs((outside-center)@vh[-1]),.95)<=tolerance)
    # Curved upholstery or another continuous surface need not be globally flat.
    # Require local tangent continuity across the shared interior boundary instead.
    normals = np.zeros_like(points, dtype=float)
    normals[1:-1,1:-1] = np.cross(points[1:-1,2:]-points[1:-1,:-2], points[2:,1:-1]-points[:-2,1:-1])
    lengths = np.linalg.norm(normals,axis=-1)
    normal_valid = erode(large & valid) & (lengths>1e-12)
    normals = np.divide(normals,lengths[...,None],out=np.zeros_like(normals),where=lengths[...,None]>1e-12)
    # Pair adjacent pixels across the internal boundary (not global mean color).
    contrasts=[]; jumps=[]; tangent_agreement=[]
    for axis in (0,1):
        a=[slice(None),slice(None)];b=a.copy();a[axis]=slice(None,-1);b[axis]=slice(1,None)
        a,b=tuple(a),tuple(b)
        edge=(small[a] != small[b]) & large[a] & large[b] & valid[a] & valid[b]
        contrasts.extend(np.linalg.norm(rgb[a].astype(float)-rgb[b].astype(float),axis=-1)[edge].tolist())
        jumps.extend(np.linalg.norm(points[a]-points[b],axis=-1)[edge].tolist())
        tangent_edge = edge & normal_valid[a] & normal_valid[b]
        tangent_agreement.extend(abs(np.einsum('ijk,ijk->ij',normals[a],normals[b]))[tangent_edge].tolist())
    smooth = len(tangent_agreement)>=max(16,len(contrasts)*.8) and np.quantile(tangent_agreement,.1)>.97
    return bool((planar or smooth) and len(contrasts)>=16 and np.quantile(contrasts,.9)<20 and np.quantile(jumps,.9)<scale*.04)


def refine_selected(run, meta, points, rgb):
    """Retain rejected candidates in metadata; never delete their masks/assets."""
    from PIL import Image
    h,w=points.shape[:2]
    masks={o['id']:np.asarray(Image.open(run/o['mask']).convert('L').resize((w,h),Image.Resampling.NEAREST))>0 for o in meta['objects']}
    rgb=np.asarray(Image.fromarray(rgb[...,:3]).resize((w,h),Image.Resampling.BILINEAR))
    decisions=[]
    structural={key: evidence for key, mask in masks.items()
                if (evidence := structural_mask_evidence(mask, points)) is not None}
    # A nearly full-frame mask containing several independent regions has no
    # observed instance silhouette. Preserve it as measured context rather than
    # asking the object prior to invent a closed object around the entire view.
    valid = np.isfinite(points).all(-1) & (np.linalg.norm(points, axis=-1) > 1e-6)
    for key, mask in masks.items():
        children = [child for child, other in masks.items() if child != key
                    and 64 <= other.sum() < mask.sum() * .2
                    and np.count_nonzero(mask & other) >= other.sum() * .98]
        if mask.mean() >= .95 and len(children) >= 2 and np.count_nonzero(mask & valid) >= mask.sum() * .95:
            structural[key] = dict(reason='full_frame_context_without_instance_silhouette',
                observed_context=True, image_fraction=float(mask.mean()), child_ids=children,
                confidence_kind='observed_depth_not_semantic_room_classification',
                limitation='Visible surface only; hidden shape and room category remain unknown')
    reviews=review_composites(masks, points)
    composites={r['object_id']: r for r in reviews if r['action']=='suppress'}
    protected={child for r in composites.values() for child in r['child_ids']}
    ordered=sorted(meta['objects'],key=lambda o:(-int(masks[o['id']].sum()),
        hashlib.sha256(np.packbits(masks[o['id']]).tobytes()).hexdigest()))
    kept=[]
    for obj in ordered:
        if obj['id'] in structural:
            obj.update(status='structural', structural_evidence=structural[obj['id']])
            continue
        if obj['id'] in composites:
            evidence=composites[obj['id']]
            obj.update(status='duplicate', duplicate_of=evidence['child_ids'])
            decisions.append(dict(object_id=obj['id'], duplicate_of=evidence['child_ids'], reason=evidence['reason']))
            continue
        duplicate_of=None if obj['id'] in protected else next((other['id'] for other in kept if partial_duplicate(masks[obj['id']], masks[other['id']], points, rgb)),None)
        if duplicate_of is not None:
            obj.update(status='duplicate', duplicate_of=duplicate_of)
            decisions.append(dict(object_id=obj['id'],duplicate_of=duplicate_of,reason='shared_boundary_continuous_low_contrast_surface_part'))
        else:
            kept.append(obj)
    meta['geometric_mask_selection']=dict(uses_object_names=False, decisions=decisions, candidate_reviews=reviews,
        structural_regions=structural,
        limitation='Only observed redundant parts/unions suppressed; broad connected scene masks and ambiguous containment retained')
