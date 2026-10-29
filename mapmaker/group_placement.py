"""Conservative support-group refinement. No semantic labels or scene identifiers.

Contact distance is a prior, not proof of a semantic support relationship. Broad
horizontal coverage establishes a motion dependency; only small gaps are closed.
"""
import numpy as np
from .scene_geometry import contact_footprint,HorizontalSurface


def support_probe(child,parent,surface,tolerance):
    """Finite surfaces below actual feet, never the next shelf above the child."""
    lo,hi=child.min(0),child.max(0);pl,ph=parent.min(0),parent.max(0)
    if pl[1]>=lo[1]-tolerance:return None
    if np.any(np.minimum(hi,ph)[[0,2]]<=np.maximum(lo,pl)[[0,2]]):return None
    feet=contact_footprint(child)
    heights=[surface.height(p[[0,2]],maximum=lo[1]+2*tolerance) for p in feet]
    known=np.array([h is not None for h in heights])
    if known.sum()<3 or known.mean()<.8:return None
    gaps=feet[known,1]-np.array([h for h in heights if h is not None])
    gap=float(gaps.min());spread=float(np.ptp(gaps))
    limit=max(8*tolerance,.25*float(np.linalg.norm(hi-lo)))
    if gap < -2*tolerance or gap>limit or spread>2*tolerance:return None
    return dict(gap=gap,coverage=float(known.mean()),spread=spread,motion_dependency_limit=limit)


def refine_groups(geometry,proposed,observations,tolerance,observed_surfaces=None):
    """Return translations from the common floor frame and explicit decisions.

Existing accepted translations are proposals. Missing edges are completed by
finite mesh support, then solved parent-first. Ambiguity/cycles do not silently
choose an arbitrary parent. A new penetration rolls back its connected group.
"""
    keys=sorted(geometry);surfaces={k:HorizontalSurface(v[f]) for k,(v,f) in geometry.items()}
    edges={};candidates={};decisions={};own={}
    for child in keys:
        v,_=geometry[child];options=[]
        for parent in keys:
            if parent==child:continue
            evidence=support_probe(v,geometry[parent][0],surfaces[parent],tolerance)
            if evidence is not None:options.append(dict(parent=parent,**evidence))
        options.sort(key=lambda e:(abs(e['gap']),e['parent']));candidates[child]=options
        old=proposed[child];target=old.get('target');obs=observations.get(child,{})
        strong=any(c['target']==target and c['contact_fraction']>=.8 for c in obs.get('candidates',[]))
        if target in geometry and (old['applied'] or strong):
            edges[child]=target
            own[child]=np.array(old.get('translation',[0,0,0]))-np.array(proposed[target].get('translation',[0,0,0])) if old['applied'] else np.zeros(3)
            decisions[child]=dict(reason='retain_accepted_relative_correction' if old['applied'] else 'carry_observed_dependent',parent=target)
        elif target=='floor':
            own[child]=np.array(old.get('translation',[0,0,0]));decisions[child]=dict(reason='retain_floor_proposal',parent='floor')
        else:
            own[child]=np.array(old.get('translation',[0,0,0]));decisions[child]=dict(reason='no_verified_dependency',parent=None)
            unique=bool(options and (len(options)==1 or abs(options[1]['gap'])-abs(options[0]['gap'])>tolerance))
            if unique:
                best=options[0];edges[child]=best['parent'];own[child]=np.zeros(3)
                # Four floor-fit tolerances = 2.4% of robust scene span. Larger
                # offsets can represent missing stands: preserve them, do not snap.
                snap=0<best['gap']<=4*tolerance
                blocker_count=0
                if snap and observed_surfaces is not None:
                    # Depth can reveal a missing intermediate support (e.g. a
                    # stack omitted by instance reconstruction). Never descend
                    # through that observed horizontal surface onto a lower mesh.
                    cloud=observed_surfaces.get(child,np.empty((0,3)))
                    feet=contact_footprint(v);lo,hi=feet.min(0),feet.max(0)
                    near=np.all((cloud[:,[0,2]]>=lo[[0,2]]-tolerance)&(cloud[:,[0,2]]<=hi[[0,2]]+tolerance),axis=1)
                    near&=(cloud[:,1]>lo[1]-best['gap']+tolerance)&(cloud[:,1]<=lo[1]+tolerance*.5)
                    blocker_count=int(near.sum())
                    if blocker_count>=3:snap=False
                if snap:own[child][1]=-best['gap']
                decisions[child]=dict(reason='close_small_supported_gap' if snap else 'carry_mesh_dependency_preserve_gap',parent=best['parent'],evidence=best,snap_limit=4*tolerance)
                decisions[child]['observed_intermediate_surface_points']=blocker_count
    result={};pending=set(keys)
    while pending:
        ready=sorted(k for k in pending if edges.get(k) not in pending)
        if not ready:
            for k in pending:result[k]=np.zeros(3);decisions[k]['reason']='cyclic_group_rollback'
            break
        for k in ready:
            result[k]=own[k]+result.get(edges.get(k),np.zeros(3));pending.remove(k)
    # Validate all broad support candidates, including candidates not chosen as
    # parents. These scalar gaps are a contact proxy, not full mesh collision.
    adjacency={k:set() for k in keys}
    for c,p in edges.items():adjacency[c].add(p);adjacency[p].add(c)
    violations=[]
    for child,options in candidates.items():
        for e in options:
            parent=e['parent'];feet=contact_footprint(geometry[child][0])
            relative=feet+result[child]-result[parent]
            heights=[surfaces[parent].height(p[[0,2]],maximum=float(feet[:,1].min()+2*tolerance)) for p in relative]
            known=np.array([h is not None for h in heights])
            after=float(np.min(relative[known,1]-np.array([h for h in heights if h is not None]))) if known.any() else None
            lost_support=child in edges and edges[child]==parent and known.mean()<.8
            if lost_support or (after is not None and after<min(-tolerance,e['gap']-tolerance)):
                violations.append(dict(child=child,parent=parent,before=e['gap'],after=after,coverage=float(known.mean()),reason='lost_support' if lost_support else 'new_penetration'))
    rolled=set()
    for violation in violations:
        queue=[violation['child'],violation['parent']]
        while queue:
            k=queue.pop()
            if k in rolled:continue
            rolled.add(k);queue.extend(adjacency[k])
    for k in rolled:result[k]=np.zeros(3);decisions[k]['reason']='new_support_penetration_group_rollback'
    for k in keys:
        decisions[k]['translation']=result[k].tolist();decisions[k]['applied']=bool(np.linalg.norm(result[k])>1e-10)
        if k in edges:
            decisions[k]['relative_translation']=(result[k]-result[edges[k]]).tolist()
    return result,dict(decisions=decisions,candidates=candidates,edges=edges,violations=violations,rolled_back=sorted(rolled),
        limitations=['Support-plane gap validation, not full mesh collision detection.',
                    'Small-gap closure intentionally trades source pose agreement for contact.',
                    'No independent semantic support ground truth or center-of-mass guarantee.'])
