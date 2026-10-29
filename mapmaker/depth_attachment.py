"""Recover visible, omitted connections from RGB-D, without object categories.

Produces only observed surface triangles, not a hallucinated watertight part.
"""
import numpy as np
from scipy.ndimage import binary_dilation,label
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components


def recover_attachment(vertices,points,subject_mask,other_mask,gap,tolerance,colors=None,parent_color=None):
    if gap<=0:return None,dict(reason='no_positive_gap')
    xz=vertices[:,[0,2]];center=xz.mean(0)
    _,_,axes=np.linalg.svd(xz-center,full_matrices=False)
    local=(xz-center)@axes.T;span=float(np.ptp(local[:,0]));bottom=float(vertices[:,1].min())
    coords=(points[...,[0,2]]-center)@axes.T
    finite=np.isfinite(points).all(-1)
    # Sweep the object's footprint downward; allow an attachment to recede
    # behind its body by a bounded fraction of body width.
    mask=finite&(points[...,1]<bottom+tolerance)&(points[...,1]>bottom-gap-2*tolerance)
    mask&=(coords[...,0]>=local[:,0].min())&(coords[...,0]<=local[:,0].max())
    minor_radius=max(float(np.max(abs(local[:,1]))),.2*span)
    mask&=abs(coords[...,1])<=minor_radius
    # Keep a narrow overlap with the observed body at the top of the sweep;
    # otherwise a one-pixel segmentation boundary severs a real attachment.
    mask&=~other_mask
    labels,_=label(mask)
    touched=np.unique(labels[binary_dilation(subject_mask,iterations=3)&mask]);touched=touched[touched>0]
    if not len(touched):return None,dict(reason='no_observed_connection')
    mask=np.isin(labels,touched)
    minimum=max(3,int(subject_mask.sum()*.001))
    middle=mask&(points[...,1]<bottom-gap*.25)&(points[...,1]>bottom-gap*.75)
    stem=points[middle]
    if len(stem)<minimum:return None,dict(reason='no_vertical_bridge',middle_points=len(stem))
    near=cKDTree(stem[:,[0,2]]).query(points[mask][:,[0,2]])[0]<=.25*float(np.linalg.norm(np.ptp(xz,axis=0)))
    if parent_color is None:
        index=np.argwhere(mask);mask[index[:,0],index[:,1]]=near
    color_evidence=None
    if colors is not None:
        # The bottom of a depth sweep can include the supporting tabletop.
        # Keep material continuity with the observed vertical bridge; never
        # recolor those background pixels to manufacture a clean support.
        sample=colors[middle].astype(float);median=np.median(sample,axis=0)
        distances=np.linalg.norm(sample-median,axis=1)
        cutoff=max(24.,3*float(np.quantile(distances,.75)))
        if parent_color is not None:cutoff=max(cutoff,.45*float(np.linalg.norm(parent_color-median)))
        mask&=np.linalg.norm(colors.astype(float)-median,axis=-1)<=cutoff
        color_evidence=dict(median_rgb=median.tolist(),distance_limit=cutoff)
    p=points[mask]
    if len(p)<minimum or np.ptp(p[:,1])<gap*.7:return None,dict(reason='incomplete_bridge')
    # An observed bridge must approach the generated body in 3D as well as touch
    # its image contour. This rejects most background strips and depth jumps.
    upper=p[p[:,1]>=bottom-tolerance]
    if len(upper)<3:return None,dict(reason='no_upper_connection')
    distance=cKDTree(vertices).query(upper)[0]
    close=distance<=2*tolerance
    if close.sum()<3 or close.mean()<.1:return None,dict(reason='bridge_disconnected_in_depth',distance=float(np.median(distance)),close_fraction=float(close.mean()))
    return mask,dict(reason='observed_rgbd_bridge',pixels=int(mask.sum()),middle_points=len(stem),upper_distance_median=float(np.median(distance)),upper_close_fraction=float(close.mean()),vertical_span=float(np.ptp(p[:,1])),gap=gap,color_continuity=color_evidence,
        limitation='Visible RGB-D surface only; unseen geometry is not reconstructed.')


def surface_mesh(points,colors,mask,max_edge):
    """Triangulate adjacent pixels; never bridge invalid pixels/depth edges."""
    h,w=mask.shape;indices=np.full((h,w),-1,dtype=int);indices[mask]=np.arange(mask.sum())
    a=indices[:-1,:-1].ravel();b=indices[:-1,1:].ravel();c=indices[1:,:-1].ravel();d=indices[1:,1:].ravel()
    faces=np.concatenate([np.stack([a,c,b],1),np.stack([b,c,d],1)])
    faces=faces[np.all(faces>=0,axis=1)];v=points[mask]
    if len(faces):
        tri=v[faces];edges=np.linalg.norm(tri-np.roll(tri,1,axis=1),axis=2)
        faces=faces[np.max(edges,axis=1)<=max_edge]
    if not len(faces):return np.empty((0,3)),np.empty((0,3),int),np.empty((0,3),np.uint8)
    used,remap=np.unique(faces,return_inverse=True);v=v[used];color=colors[mask][used];faces=remap.reshape(-1,3)
    edges=np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]])
    n,labels=connected_components(coo_matrix((np.ones(len(edges)),(edges[:,0],edges[:,1])),shape=(len(v),len(v))),directed=False)
    winner=max(range(n),key=lambda i:(float(np.ptp(v[labels==i,1])),int(np.sum(labels==i))))
    faces=faces[np.all(labels[faces]==winner,axis=1)];used,remap=np.unique(faces,return_inverse=True)
    return v[used],remap.reshape(-1,3),color[used]


def join_body(patch,body,faces,tolerance):
    """Bounded registration of observed bridge top to reconstructed body surface."""
    import trimesh
    height=float(np.ptp(patch[:,1]));lo=float(patch[:,1].min());hi=float(patch[:,1].max())
    top=patch[:,1]>=hi-max(height*.1,1e-8)
    closest,distance,_=trimesh.proximity.closest_point(trimesh.Trimesh(vertices=body,faces=faces,process=False),patch[top])
    # Align the recovered part as a rigid piece first. This corrects the depth
    # bias common to dark/occluded attachments without stretching its stem.
    limit=max(3*tolerance,.25*float(np.linalg.norm(np.ptp(body,axis=0))))
    shift=np.median(closest-patch[top],axis=0)
    if np.linalg.norm(shift)>limit:return None,dict(reason='body_registration_too_far',maximum=float(np.linalg.norm(shift)),limit=limit)
    result=patch+shift
    nearest,residual,_=trimesh.proximity.closest_point(trimesh.Trimesh(vertices=body,faces=faces,process=False),result[top])
    anchored=residual<=2*tolerance
    if anchored.sum()<3 or anchored.mean()<.8:return None,dict(reason='inconsistent_attachment_joint',anchored_fraction=float(anchored.mean()),limit=2*tolerance)
    weight=np.clip((patch[:,1]-(lo+height*.6))/(height*.4),0,1)
    residual_shift=np.median((nearest-result[top])[anchored],axis=0);result+=weight[:,None]*residual_shift
    result[np.flatnonzero(top)[anchored]]=nearest[anchored]
    return result,dict(reason='registered_observed_connection',rigid_translation=shift.tolist(),max_joint_adjustment=float(np.max(residual[anchored])),max_adjustment=float(np.max(np.linalg.norm(result-patch,axis=1))),limit=limit,body_contact_vertices=int(anchored.sum()),anchored_fraction=float(anchored.mean()))


def settle_rigid(vertices,parent_faces,tolerance,support_center=None):
    """Small rigid pose search; contact polygon must contain bounds center."""
    import trimesh
    from .scene_geometry import HorizontalSurface,support_translation
    from .pair_support import nearby_contact
    surface=HorizontalSurface(parent_faces);limit=.25*np.linalg.norm(np.ptp(vertices,axis=0))
    pivot=(vertices.min(0)+vertices.max(0))/2;pivot[1]=vertices[:,1].min()
    for angle in [0,1,2,4,8]:
        accepted=[]
        for azimuth in ([0] if angle==0 else np.linspace(0,2*np.pi,8,endpoint=False)):
            rotation=trimesh.transformations.rotation_matrix(np.deg2rad(angle),[np.cos(azimuth),0,np.sin(azimuth)],point=pivot)
            moved=trimesh.transform_points(vertices,rotation)
            center=None if support_center is None else trimesh.transform_points(np.asarray(support_center)[None],rotation)[0]
            shift,e=support_translation(moved,parent_faces,limit,tolerance,surface=surface,support_center=center)
            if shift is None:shift,e=nearby_contact(moved,parent_faces,tolerance,support_center=center,surface=surface)
            if shift is None:continue
            residual,check=support_translation(moved+shift,parent_faces,limit,tolerance,surface=surface,support_center=None if center is None else center+shift)
            if residual is None or abs(residual[1])>1e-7:continue
            transform=rotation.copy();transform[:3,3]+=shift
            accepted.append((float(np.max(np.linalg.norm(trimesh.transform_points(vertices,transform)-vertices,axis=1))),transform,dict(tilt_degrees=angle,contact=e,verification=check)))
        if accepted:
            _,transform,e=min(accepted,key=lambda a:a[0]);return transform,e
    return None,dict(reason='no_stable_rigid_contact_within_8_degrees')


def fit_attachment_contact(patch,body,body_faces,parent_faces,tolerance,center):
    """Joint fitting: preserve body attachment while placing observed feet under load.

Only the uncertain recovered part is adjusted in XZ, within two depth tolerances.
The existing body's pose is not used as a substitute for an actual contact.
"""
    import trimesh
    from .scene_geometry import HorizontalSurface,support_translation
    surface=HorizontalSurface(parent_faces);mesh=trimesh.Trimesh(body,body_faces,process=False)
    height=float(np.ptp(patch[:,1]));lo=patch[:,1].min();top=patch[:,1]>=patch[:,1].max()-.1*height
    limit=.25*np.linalg.norm(np.ptp(body,axis=0));weight=np.clip((patch[:,1]-(lo+.6*height))/(.4*height),0,1)
    for radius in [0,.25*tolerance,.5*tolerance,tolerance,2*tolerance]:
        proposals=[]
        for angle in ([0] if radius==0 else np.linspace(0,2*np.pi,16,endpoint=False)):
            horizontal=np.array([radius*np.cos(angle),0,radius*np.sin(angle)])
            candidate=patch+horizontal
            # Keep the already registered upper joint fixed while accommodating
            # a bounded correction of the noisy recovered lower surface.
            candidate-=weight[:,None]*horizontal
            combined=np.concatenate([body,candidate])
            shift,e=support_translation(combined,parent_faces,limit,tolerance*.25,surface=surface,support_center=center)
            if shift is None:continue
            check,recheck=support_translation(combined+shift,parent_faces,limit,tolerance*.25,surface=surface,support_center=center+shift)
            if check is None or abs(check[1])>1e-7:continue
            proposals.append((abs(float(shift[1])),candidate,shift,e,recheck,horizontal))
        if proposals:
            _,candidate,shift,e,recheck,horizontal=min(proposals,key=lambda x:x[0]);transform=np.eye(4);transform[:3,3]=shift
            return candidate,transform,dict(reason='joint_body_support_fit',lower_adjustment=horizontal.tolist(),adjustment_limit=2*tolerance,contact=e,verification=recheck,tilt_degrees=0)
    return None,None,dict(reason='no_joint_fit_within_depth_uncertainty')
