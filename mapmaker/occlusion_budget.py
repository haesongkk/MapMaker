"""Select complete supported patches under a shared inferred-pixel budget."""
import numpy as np


def select_components(sizes, values, budget):
    """Exact 0/1 allocation maximizing total geometric evidence, with stable ties."""
    sizes=np.asarray(sizes)
    values=np.asarray(values,float)
    if (sizes.ndim!=1 or sizes.shape!=values.shape or not np.issubdtype(sizes.dtype,np.integer)
            or np.any(sizes<=0) or not np.isfinite(values).all() or np.any(values<0)
            or not isinstance(budget,(int,np.integer)) or budget<0):
        raise ValueError('Expected positive integer sizes, finite nonnegative values, and integer budget')
    budget=min(int(budget),int(sizes.sum()))
    score=np.zeros(budget+1)
    decisions=np.zeros((len(sizes),budget+1),bool)
    for i,(size,value) in enumerate(zip(sizes,values)):
        if size>budget:continue
        candidate=score[:-size]+value
        better=candidate>score[size:]+1e-12
        decisions[i,size:]=better
        score[size:]=np.where(better,candidate,score[size:])
    chosen=np.zeros(len(sizes),bool)
    remaining=budget
    for i in range(len(sizes)-1,-1,-1):
        if decisions[i,remaining]:
            chosen[i]=True;remaining-=int(sizes[i])
    return chosen
