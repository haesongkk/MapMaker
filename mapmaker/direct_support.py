"""Direct-support parsing and evidence gates, independent of scene/object categories."""
import re
from collections import Counter

RELATIONS={'rests_on','inside','attached_to','hanging','uncertain'}
ENV={'floor','wall','ceiling','unrepresented','unknown'}

def parse_observation(raw, subject, ids, *, verification=False):
    fields={}
    for line in raw.strip().splitlines():
        match=re.fullmatch(r'\s*(?:[-*]\s*)?(Object|Support|Support name|Relation|Evidence|Identity)\s*:\s*(.+?)\s*',line,re.I)
        if not match:raise ValueError('Expected labeled plain-text lines')
        key=match[1].lower()
        if key in fields:raise ValueError('Duplicate field')
        fields[key]=match[2].strip()
    expected={'object','support','support name','relation','evidence'}|({'identity'} if verification else set())
    if set(fields)!=expected:raise ValueError('Incomplete observation')
    target=fields['support'];relation=fields['relation'].lower()
    if target not in set(ids)|ENV or target==subject:raise ValueError('Invalid direct supporter')
    if relation not in RELATIONS:raise ValueError('Invalid relation')
    identity=fields.get('identity','unverified').lower()
    if verification and identity not in {'match','mismatch','uncertain'}:raise ValueError('Invalid identity check')
    if target=='floor' and relation!='rests_on':raise ValueError('Floor must be a direct resting surface')
    return dict(subject=subject,object_name=fields['object'],target=target,support_name=fields['support name'],
                relation=relation,evidence=fields['evidence'],identity=identity)

def resolve_observations(observations):
    """A localized identity check must corroborate a relation, with at most one retry.

    Agreement is model evidence, not human/physical ground truth. Names are never
    matched against pipeline category labels (those can be wrong).
    """
    # A mismatch retracts the original name; the localized answer is a new
    # hypothesis, usable only if a later check matches that corrected identity.
    mismatch=[i for i,o in enumerate(observations) if o and o['identity']=='mismatch']
    if mismatch:observations=observations[mismatch[-1]:]
    valid=[o for o in observations if o and o['identity']!='uncertain'
           and o['relation']!='uncertain' and o['target'] not in {'unknown','unrepresented'}]
    counts=Counter((o['relation'],o['target']) for o in valid)
    accepted=[o for o in valid if o['identity']=='match' and counts[(o['relation'],o['target'])]>=2]
    keys={(o['relation'],o['target']) for o in accepted}
    if len(keys)!=1:return None
    return accepted[-1]

def cycle_members(relations):
    """Reject support/containment dependency cycles, including cycles of length > 2."""
    cyclic=set()
    for start in relations:
        path=[];cur=start
        while cur in relations:
            if cur in path:
                cyclic.update(path[path.index(cur):]);break
            path.append(cur);cur=relations[cur]['target']
    return cyclic

def floor_ids(relations):
    return [k for k,v in relations.items() if v['target']=='floor' and v['relation']=='rests_on']
