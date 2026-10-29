import pytest
from mapmaker.direct_support import parse_observation,resolve_observations,cycle_members,floor_ids

def answer(target='O002',relation='rests_on',identity=None):
    raw=f'Object: book\nSupport: {target}\nSupport name: surface\nRelation: {relation}\nEvidence: visible resting contact'
    return raw+(f'\nIdentity: {identity}' if identity else '')

def test_direct_support_is_not_transitive_floor_contact():
    book=parse_observation(answer(),'O001',['O001','O002'])
    table=parse_observation(answer('floor'),'O002',['O001','O002'])
    assert floor_ids({'O001':book,'O002':table})==['O002']

def test_identity_and_independent_agreement_required():
    a=parse_observation(answer(),'O001',['O001','O002'])
    bad=parse_observation(answer(identity='mismatch'),'O001',['O001','O002'],verification=True)
    good=parse_observation(answer(identity='match'),'O001',['O001','O002'],verification=True)
    assert resolve_observations([a,bad]) is None
    assert resolve_observations([good,bad]) is None
    assert resolve_observations([a,bad,good])['target']=='O002'
    assert resolve_observations([a,good])['target']=='O002'

def test_retry_resolves_disagreement_only_with_corroboration():
    a=parse_observation(answer('floor'),'O001',['O001','O002'])
    b=parse_observation(answer(identity='match'),'O001',['O001','O002'],verification=True)
    assert resolve_observations([a,b]) is None
    assert resolve_observations([a,b,b])['target']=='O002'

def test_unknown_and_cycles_are_not_actionable():
    a=parse_observation(answer('unknown',identity='match'),'O001',['O001'],verification=True)
    assert resolve_observations([a,a]) is None
    assert cycle_members({'a':{'target':'b'},'b':{'target':'c'},'c':{'target':'a'},'d':{'target':'a'}})=={'a','b','c'}

@pytest.mark.parametrize('raw',[answer('O999'),answer('O001'),answer('floor','inside'),answer()+'\nSupport: floor'])
def test_bad_observation_never_moves_objects(raw):
    with pytest.raises(ValueError):parse_observation(raw,'O001',['O001','O002'])
