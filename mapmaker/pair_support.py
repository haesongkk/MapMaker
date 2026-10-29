"""Category-independent mask identity and short pair-relation responses."""
import re
import numpy as np
from scipy.ndimage import distance_transform_edt
from .scene_geometry import HorizontalSurface,contact_footprint,inside_support_polygon,contact_polygon_margin


def contained_translation(vertices,container,carry):
    """Project parent-following motion into the container's vertical extent.

    This is a bounds constraint, not a certification of watertight containment.
    It prevents a reconstructed stem/base passing through the container bottom.
    """
    low,high=container.min(0),container.max(0)
    feet=contact_footprint(vertices)
    overlap=np.all((feet[:,[0,2]]>=low[[0,2]]) & (feet[:,[0,2]]<=high[[0,2]]),axis=1)
    if overlap.mean()<.5:return None,dict(reason='no_container_footprint_overlap')
    bottom=float(vertices[:,1].min())
    dy=float(np.clip(carry,low[1]-bottom,high[1]-bottom))
    return dy,dict(reason='preserve_containment_offset' if abs(dy-carry)<1e-9 else 'project_containment_above_container_bottom',containment_adjustment=dy-carry)


def nearby_contact(vertices,target_faces,tolerance,*,support_center=None,surface=None):
    """Minimal bounded horizontal repair when the existing footprint misses a support.

    Search within a quarter of the object's horizontal size. Require broad finite
    surface coverage and a support polygon around its geometric center.
    """
    feet=contact_footprint(vertices);size=np.ptp(vertices,axis=0)
    radius=float(np.linalg.norm(size[[0,2]]))*.25
    vertical_limit=float(np.linalg.norm(size))*.75
    surface=surface if surface is not None else HorizontalSurface(target_faces);center=(vertices.min(0)+vertices.max(0))/2 if support_center is None else np.asarray(support_center)
    bottom=float(vertices[:,1].min())
    for distance in np.linspace(radius/8,radius,8):
        candidates=[]
        for angle in np.linspace(0,2*np.pi,16,endpoint=False):
            xz=distance*np.array([np.cos(angle),np.sin(angle)])
            heights=[surface.height(p[[0,2]]+xz,maximum=bottom+vertical_limit) for p in feet]
            known=np.array([h is not None for h in heights])
            if known.sum()<max(3,int(np.ceil(len(feet)*.75))):continue
            offsets=np.array([h for h in heights if h is not None])-feet[known,1]
            dy=float(offsets.max())
            if abs(dy)>vertical_limit:continue
            contacts=feet[known][offsets>=dy-tolerance][:,[0,2]]+xz
            if not inside_support_polygon(contacts,center[[0,2]]+xz,margin=contact_polygon_margin(contacts)):continue
            candidates.append((abs(dy),np.array([xz[0],dy,xz[1]]),float(known.mean())))
        if candidates:
            _,delta,coverage=min(candidates,key=lambda x:x[0])
            return delta,dict(reason='bounded_horizontal_contact_repair',horizontal_distance=float(distance),horizontal_limit=radius,footprint_coverage=coverage)
    return None,dict(reason='no_nearby_stable_support')

def mask_aliases(masks, threshold=.95):
    """Only nearly identical pixel sets are aliases; containment is not duplication."""
    representatives=[];aliases={}
    for key in sorted(masks,key=lambda k:(-int(masks[k].sum()),k)):
        for other in representatives:
            inter=np.logical_and(masks[key],masks[other]).sum()
            union=np.logical_or(masks[key],masks[other]).sum()
            if inter/union>=threshold:
                aliases[key]=other;break
        else:representatives.append(key)
    return aliases

def nearby_supports(subject,masks,aliases,limit=4):
    """Shortlist by original-image proximity, independent of semantic labels."""
    a=masks[subject];distance=distance_transform_edt(~a);ay,ax=np.where(a)
    scores=[]
    for key,b in masks.items():
        if key==subject or key in aliases:continue
        by,bx=np.where(b)
        # A support normally reaches below the subject's lower contour; permit
        # a tolerance proportional to the subject's image size.
        size=max(np.ptp(ax),np.ptp(ay),1)
        if by.max()<ay.max()-.15*size:continue
        gap=float(distance[b].min())/size
        scores.append((gap,abs(float(by.max()-ay.max()))/max(size,1),key))
    return [k for _,__,k in sorted(scores)[:limit]]

def parse_verdict(text,allowed):
    match=re.match(r'^\s*(?:\*\*)?([A-Z]+)\b',text)
    if not match or match[1] not in allowed:raise ValueError('Unrecognized verdict')
    return match[1]

def direct_edges(edges):
    """Remove a proposed indirect edge only when a separate support path exists."""
    direct={a:dict(bs) for a,bs in edges.items()}
    def reaches(start,end,seen):
        if start==end:return True
        if start in seen:return False
        return any(reaches(n,end,seen|{start}) for n in edges.get(start,{}))
    for a,bs in edges.items():
        for b in bs:
            if any(c!=b and reaches(c,b,{a}) for c in bs):direct[a].pop(b,None)
    return direct
