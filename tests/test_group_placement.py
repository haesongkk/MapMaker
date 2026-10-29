import numpy as np
import trimesh
from mapmaker.group_placement import refine_groups


def box(size,center):
 m=trimesh.creation.box(extents=size);m.apply_translation(center)
 return np.array(m.vertices),np.array(m.faces)


def proposal(target=None,shift=0.,applied=False):
 return dict(target=target,translation=[0.,shift,0.],applied=applied)


def scene(scale=1.):
 g={'base':box([2,.2,2],[0,.9,0]),'upper':box([.3,.3,.3],[0,1.18,0]),'leaf':box([.1,.2,.1],[0,1.43,0])}
 return {k:(v*scale,f) for k,(v,f) in g.items()}


def test_small_gap_closed_and_descendant_carried():
 g=scene();p={'base':proposal('floor',.1,True),'upper':proposal(),'leaf':proposal('upper')}
 obs={'leaf':{'candidates':[dict(target='upper',contact_fraction=1.)]}}
 delta,report=refine_groups(g,p,obs,.01)
 assert report['edges']['upper']=='base'
 assert np.isclose(delta['upper'][1],.07)
 assert np.allclose(delta['leaf'],delta['upper'])
 assert np.isclose(g['upper'][0][:,1].min()+delta['upper'][1],1.1)


def test_large_gap_preserved_while_parent_moves():
 g=scene();g.pop('leaf');g['upper']=(g['upper'][0]+[0,.04,0],g['upper'][1])
 p={'base':proposal('floor',.1,True),'upper':proposal()}
 d,r=refine_groups(g,p,{},.01)
 assert r['decisions']['upper']['reason']=='carry_mesh_dependency_preserve_gap'
 assert np.allclose(d['base'],d['upper'])


def test_scale_and_identifier_invariance():
 p={'base':proposal('floor',.1,True),'upper':proposal(),'leaf':proposal('upper')}
 obs={'leaf':{'candidates':[dict(target='upper',contact_fraction=1.)]}}
 d,_=refine_groups(scene(),p,obs,.01)
 names={'base':'random_z','upper':'random_a','leaf':'random_m'}
 p2={names[k]:dict(v,target=names.get(v['target'],v['target']),translation=(np.array(v['translation'])*17).tolist()) for k,v in p.items()}
 d2,_=refine_groups({names[k]:v for k,v in scene(17).items()},p2,{names['leaf']:{'candidates':[dict(target=names['upper'],contact_fraction=1.)]}},.17)
 for k in d:assert np.allclose(d2[names[k]],d[k]*17)


def test_outside_surface_not_attached_and_next_shelf_not_selected():
 g={'base':box([2,.2,2],[0,.9,0]),'upper':box([.2,.2,.2],[3,1.12,0]),'above':box([2,.1,2],[3,1.8,0])}
 p={k:proposal() for k in g};p['base']=proposal('floor',.1,True)
 d,r=refine_groups(g,p,{},.01)
 assert 'upper' not in r['edges']
 assert np.allclose(d['upper'],0)


def test_new_penetration_rolls_back_ambiguous_group():
 # Two overlapping alternative supports make attachment ambiguous. Raising one
 # into the child must undo the support move rather than bury the stationary child.
 g={'a':box([2,.2,2],[0,.9,0]),'b':box([2,.2,2],[0,.9,0]),'c':box([.3,.3,.3],[0,1.18,0])}
 p={'a':proposal('floor',.1,True),'b':proposal(),'c':proposal()}
 d,r=refine_groups(g,p,{},.01)
 assert r['violations']
 assert np.allclose(d['a'],0) and np.allclose(d['c'],0)


def test_observed_missing_support_prevents_snapping_to_lower_mesh():
 g=scene();g.pop('leaf');p={'base':proposal('floor',.1,True),'upper':proposal()}
 surfaces={'upper':np.array([[-.1,1.025,-.1],[.1,1.025,-.1],[0,1.025,.1]])}
 d,r=refine_groups(g,p,{},.01,surfaces)
 assert np.allclose(d['upper'],d['base'])
 assert r['decisions']['upper']['observed_intermediate_surface_points']==3


def test_relative_horizontal_move_off_support_rolls_back_group():
 g=scene();g.pop('leaf');p={'base':proposal('floor',.1,True),'upper':proposal('base',.1,True)}
 p['upper']['translation'][0]=3.
 d,r=refine_groups(g,p,{},.01)
 assert r['violations'][0]['reason']=='lost_support'
 assert np.allclose(d['base'],0) and np.allclose(d['upper'],0)
