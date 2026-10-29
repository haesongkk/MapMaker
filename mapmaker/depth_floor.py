"""Floor-first geometry in the original SAM3D camera frame; no object-up prior."""
import numpy as np
from scipy.ndimage import binary_dilation
from scipy.spatial import cKDTree
from .scene_structure import observed_normals
from .scene_placement import rotation_to_world_up


def estimate_floor(points, excluded, *, seed=42):
    """Robust background plane, ranked by lower-image and above-plane evidence.

    Camera +Y only disambiguates horizontal ground from walls and ceiling.
    No object pose, category, mean-up, or generated mesh minimum is consulted.
    """
    points=np.asarray(points,float);excluded=np.asarray(excluded,bool)
    if points.ndim!=3 or points.shape[-1]!=3 or excluded.shape!=points.shape[:2]:
        raise ValueError('Expected aligned pointmap and exclusion mask')
    h,w=excluded.shape;step=max(1,int(np.ceil(max(h,w)/180)))
    p=points[::step,::step];yy,xx=np.mgrid[:h:step,:w:step]
    valid=np.isfinite(p).all(-1)&(p[...,2]>0)
    available=valid&~binary_dilation(excluded,iterations=2)[::step,::step]
    if available.sum()<200:raise ValueError('Insufficient observed background for floor')
    all_points=p[valid];span=np.linalg.norm(np.quantile(all_points,.95,axis=0)-np.quantile(all_points,.05,axis=0))
    tolerance=max(float(span)*.006,1e-6);rng=np.random.default_rng(seed)
    candidates=[]
    for _ in range(8):
        cloud=p[available]
        if len(cloud)<150:break
        sample=cloud[rng.choice(len(cloud),min(5000,len(cloud)),replace=False)]
        triples=sample[rng.integers(len(sample),size=(800,3))]
        normals=np.cross(triples[:,1]-triples[:,0],triples[:,2]-triples[:,0]);length=np.linalg.norm(normals,axis=1)
        good=length>1e-9;normals=normals[good]/length[good,None];anchors=triples[good,0]
        counts=[]
        for start in range(0,len(normals),64):
            distances=np.abs(normals[start:start+64]@sample.T-np.einsum('ij,ij->i',normals[start:start+64],anchors[start:start+64])[:,None])
            counts.extend((distances<tolerance).sum(1))
        if not counts:break
        winner=int(np.argmax(counts));n=normals[winner];center=anchors[winner]
        for __ in range(4):
            keep=abs((cloud-center)@n)<tolerance
            if keep.sum()<100:break
            center=cloud[keep].mean(0);_,_,vt=np.linalg.svd(cloud[keep]-center,full_matrices=False);n=vt[-1]
        if n[1]<0:n=-n
        inliers=available&(abs((p-center)@n)<tolerance)
        available[inliers]=False
        if inliers.sum()<100:continue
        above=float(np.mean((all_points-center)@n>=-tolerance*2))
        pixel_span=np.array([np.ptp(xx[inliers])/w,np.ptp(yy[inliers])/h])
        lower=float(np.mean(yy[inliers]>.6*h))
        camera_above=float(-center@n)
        accepted=bool(n[1]>.5 and camera_above>tolerance and above>.8 and pixel_span[0]>.3 and lower>.1)
        residual=np.abs((p[inliers]-center)@n)
        score=int(inliers.sum())*(.25+lower)*above
        candidates.append(dict(normal=n.tolist(),point=center.tolist(),inliers=int(inliers.sum()),accepted=accepted,
            score=score,above_fraction=above,lower_image_fraction=lower,pixel_span=pixel_span.tolist(),
            camera_above=camera_above,residual_p90=float(np.quantile(residual,.9))))
    accepted=[r for r in candidates if r['accepted']]
    if not accepted:raise ValueError('No sufficiently supported floor plane: '+str(candidates))
    winner=max(accepted,key=lambda r:r['score']);normal=np.array(winner['normal']);center=np.array(winner['point'])
    transform=np.eye(4);transform[:3,:3]=rotation_to_world_up(normal);transform[1,3]=-normal@center
    return transform,dict(method='background_ransac_floor_no_object_up',selected=winner,candidates=candidates,tolerance=tolerance,
        rotation_degrees=float(np.degrees(np.arccos(np.clip(normal[1],-1,1)))),transform=transform.tolist())


def observed_bottom(points,mask):
    observed=np.asarray(points)[np.asarray(mask,bool)]
    observed=observed[np.isfinite(observed).all(1)]
    if len(observed)<30:return None
    return dict(bottom=float(np.quantile(observed[:,1],.01)),height=float(np.ptp(np.quantile(observed[:,1],[.01,.99]))),
        count=len(observed),q05=float(np.quantile(observed[:,1],.05)))


def infer_contacts(points,masks,tolerance):
    """Propose contacts from observed 3D neighborhoods, without object names."""
    valid=np.isfinite(points).all(-1)
    normals,reliable=observed_normals(points,valid)
    clouds={};trees={};rows={}
    for key,mask in masks.items():
        p=points[mask&valid];n=normals[mask&valid];r=reliable[mask&valid]
        if len(p)<30:continue
        ids=np.linspace(0,len(p)-1,min(len(p),20000)).astype(int)
        clouds[key]=(p[ids],n[ids],r[ids]);trees[key]=cKDTree(p[ids])
        low=float(np.quantile(p[:,1],.001));height=float(np.ptp(np.quantile(p[:,1],[.001,.99])))
        rows[key]=dict(observed_bottom=low,observed_height=height,source_floor_contact=bool(abs(low)<2*tolerance),candidates=[])
    for key,row in rows.items():
        p=clouds[key][0];low=row['observed_bottom'];band=max(tolerance,.04*row['observed_height'])
        feet=p[p[:,1]<=low+band]
        feet=feet[np.linspace(0,len(feet)-1,min(len(feet),128)).astype(int)]
        for other,target in rows.items():
            if other==key:continue
            # Duplicate observations and same-height peers are not stacked.
            overlap=np.logical_and(masks[key],masks[other]).sum()/max(1,np.logical_or(masks[key],masks[other]).sum())
            if overlap>.95:continue
            thin_ground=target['source_floor_contact'] and target['observed_height']<2*tolerance and row['observed_height']>4*tolerance
            if not thin_ground and target['observed_bottom']>=low-tolerance*.25:continue
            d,idx=trees[other].query(feet);q,n,r=(a[idx] for a in clouds[other])
            close=(d<3*tolerance)&(q[:,1]<=feet[:,1]+tolerance)
            if close.mean()<.3:continue
            horizontal=close&r&(abs(n[:,1])>.75)
            row['candidates'].append(dict(target=other,contact_fraction=float(close.mean()),horizontal_fraction=float(horizontal.mean()),
                distance=float(np.median(d[close])),thin_ground=thin_ground,
                kind='surface' if horizontal.mean()>=.2 else 'contact_carry'))
        row['candidates'].sort(key=lambda x:(-x['contact_fraction'],x['distance']))
        if row['source_floor_contact']:
            thin=[c for c in row['candidates'] if c['thin_ground'] and c['kind']=='surface' and c['contact_fraction']>=.8]
            row.update(target=thin[0]['target'] if thin else 'floor',kind='surface')
        elif row['candidates']:
            best=row['candidates'][0]
            # Keep multiple plausible supports unresolved rather than arbitrarily picking.
            tied=[c for c in row['candidates'] if c['contact_fraction']>=best['contact_fraction']*.9 and c['distance']<=best['distance']+tolerance*.25]
            # Equivalent mask observations must not create artificial ambiguity.
            unique=[]
            for c in sorted(tied,key=lambda c:(-masks[c['target']].sum(),c['target'])):
                if any(np.logical_and(masks[c['target']],masks[b['target']]).sum()/max(1,np.logical_or(masks[c['target']],masks[b['target']]).sum())>.95 for b in unique):continue
                unique.append(c)
            tied=unique
            if len(tied)==1:best=tied[0]
            if len(tied)==1:row.update(target=best['target'],kind=best['kind'])
            else:row.update(target=None,kind='ambiguous_contact')
        else:row.update(target=None,kind='no_observed_contact')
    return rows


def projected_support(vertices,points,masks,subject,inverse_common,camera,tolerance,observations):
    """Use reconstructed feet to query the original depth image when a mask omits its base."""
    from .scene_geometry import contact_footprint
    base_feet=contact_footprint(vertices);h,w=points.shape[:2]
    limit=max(float(np.linalg.norm(np.ptp(vertices,axis=0)))*.25,tolerance*3)
    evidence=[]
    for drop in np.linspace(0,limit,9):
        feet=base_feet-np.array([0,drop,0])
        raw=feet@inverse_common[:3,:3].T+inverse_common[:3,3]
        uv=(raw/raw[:,2,None])@camera.T
        xy=np.rint(uv[:,:2]).astype(int)
        valid=(xy[:,0]>=0)&(xy[:,0]<w)&(xy[:,1]>=0)&(xy[:,1]<h)&(raw[:,2]>0)
        if valid.sum()<3:continue
        feet=feet[valid];xy=xy[valid];observed=points[xy[:,1],xy[:,0]]
        close=np.isfinite(observed).all(1)&(np.linalg.norm(observed-feet,axis=1)<tolerance*5)
        found=[]
        for key,mask in masks.items():
            if key==subject or key not in observations:continue
            if observations[key]['observed_bottom']>=observations[subject]['observed_bottom']-tolerance*.25:continue
            hit=close&mask[xy[:,1],xy[:,0]]
            if hit.sum()>=3 and hit.mean()>=.4:found.append(dict(target=key,fraction=float(hit.mean()),distance=float(np.median(np.linalg.norm(observed[hit]-feet[hit],axis=1))),probe_drop=float(drop)))
        found.sort(key=lambda r:(-r['fraction'],r['distance']));evidence.extend(found)
        if len(found)==1 or (len(found)>1 and found[0]['fraction']>found[1]['fraction']+.2):return found[0]['target'],evidence
        if len(found)>1:return None,evidence
    return None,evidence
