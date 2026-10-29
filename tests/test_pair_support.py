import numpy as np
import pytest
from mapmaker.pair_support import mask_aliases,nearby_supports,parse_verdict,direct_edges
from mapmaker.pair_support import contained_translation,nearby_contact
import trimesh

def test_duplicate_mask_is_alias_but_contained_part_is_not():
 big=np.zeros((30,30),bool);big[2:20,2:20]=True
 small=np.zeros_like(big);small[4:9,4:9]=True
 assert mask_aliases({'a':big,'b':big.copy(),'c':small})=={'b':'a'}

def test_support_shortlist_excludes_alias_and_self():
 top=np.zeros((30,30),bool);top[1:10,10:20]=True
 base=np.zeros_like(top);base[10:25,5:25]=True
 masks={'top':top,'base':base,'duplicate':top.copy()}
 assert nearby_supports('top',masks,{'duplicate':'top'})==['base']

def test_response_requires_explicit_leading_verdict():
 assert parse_verdict('ON. Red book rests on blue table.',{'ON','IN','NONE'})=='ON'
 with pytest.raises(ValueError):parse_verdict('Perhaps ON the table.',{'ON','IN','NONE'})

def test_intervening_container_removes_indirect_support():
 edges={'plant':{'vase':'IN','table':'ON'},'vase':{'table':'ON'}}
 assert direct_edges(edges)=={'plant':{'vase':'IN'},'vase':{'table':'ON'}}
 assert len(edges['plant'])==2

def test_containment_follows_parent_but_does_not_cross_its_bottom():
 container=trimesh.creation.box(extents=[2,2,2]).vertices+np.array([0,1,0])
 child=trimesh.creation.box(extents=[.2,2,.2]).vertices+np.array([0,1.3,0])
 dy,e=contained_translation(child,container,-.8)
 assert dy==pytest.approx(-.3)
 assert e['reason']=='project_containment_above_container_bottom'
 assert contained_translation(child+np.array([5,0,0]),container,-.8)[0] is None

def test_lateral_repair_is_local_and_rejects_distant_support():
 support=trimesh.creation.box(extents=[2,.1,2]);support.apply_translation([0,-.05,0])
 child=trimesh.creation.box(extents=[.2,.4,.2]);child.apply_translation([.93,.3,0])
 delta,e=nearby_contact(child.vertices,support.triangles,1e-4)
 assert delta is not None and delta[0]<0 and abs(delta[0])<=np.hypot(.2,.2)*.25
 assert delta[1]==pytest.approx(-.1)
 assert nearby_contact(child.vertices+np.array([2,0,0]),support.triangles,1e-4)[0] is None
