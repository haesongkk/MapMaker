"""Explicit extra depth conditioning for the checkpoint's ordinary CFG sampler.

Keep its existing RGB/all-condition CFG result and add a separately measured
full-minus-depth-dropped prediction. This does not replace model weights.
"""
from contextlib import contextmanager
import math


def tree_map(fn, *trees):
    first=trees[0]
    if isinstance(first,dict):
        if any(t.keys()!=first.keys() for t in trees):raise ValueError('Prediction keys differ')
        return {k:tree_map(fn,*(t[k] for t in trees)) for k in first}
    if isinstance(first,(list,tuple)):
        if any(len(t)!=len(first) for t in trees):raise ValueError('Prediction shapes differ')
        return type(first)(tree_map(fn,*(t[i] for t in trees)) for i in range(len(first)))
    return fn(*trees)


def max_delta(a,b):
    values=[]
    tree_map(lambda x,y:values.append(float(abs(x-y).max())),a,b)
    result=max(values,default=0.)
    if not math.isfinite(result):raise ValueError('Nonfinite conditioning difference')
    return result


@contextmanager
def additional_depth_guidance(model, strength, schedule):
    """Patch only this isolated inference instance and restore even on failure.

    `schedule` is the upstream get_strength function, passed explicitly so CPU
    tests need no model runtime. Strength zero invokes the original methods.
    """
    if not math.isfinite(strength) or strength<0:raise ValueError('Invalid depth guidance')
    pipeline=model._pipeline
    reverse=pipeline.models['ss_generator'].reverse_fn
    embedder=pipeline.condition_embedders['ss_condition_embedder']
    if reverse.training or embedder.training:raise ValueError('Evaluation mode is required')
    if not hasattr(embedder,'force_drop_modalities'):raise ValueError('Modality dropout is unavailable')
    original_condition=pipeline.get_condition_input
    original_forward=reverse.inner_forward
    sentinel=object()
    saved_condition=pipeline.__dict__.get('get_condition_input',sentinel)
    saved_forward=reverse.__dict__.get('inner_forward',sentinel)
    cache={}
    stats=dict(condition_pairs=0,prediction_pairs=0,max_condition_delta=0.,max_prediction_delta=0.)

    def condition_input(condition_embedder,input_dict,input_mapping):
        full=original_condition(condition_embedder,input_dict,input_mapping)
        if condition_embedder is not embedder or strength==0:return full
        if embedder.force_drop_modalities:raise ValueError('Baseline already drops modalities')
        previous=embedder.force_drop_modalities
        try:
            embedder.force_drop_modalities=['pointmap','rgb_pointmap']
            dropped=original_condition(condition_embedder,input_dict,input_mapping)
        finally:
            embedder.force_drop_modalities=previous
        if len(full[0])!=1 or len(dropped[0])!=1 or full[1] or dropped[1]:
            raise ValueError('Expected one precomputed condition token tensor')
        delta=max_delta(full[0][0],dropped[0][0])
        if delta==0:raise ValueError('Depth dropout did not change condition tokens')
        cache['dropped_args']=dropped[0]
        stats['condition_pairs']+=1
        stats['max_condition_delta']=max(stats['max_condition_delta'],delta)
        return full

    def inner_forward(x,t,is_cond,cfg_strength,*args,**kwargs):
        weight=schedule(strength,reverse.interval,t)
        if weight==0:return original_forward(x,t,is_cond,cfg_strength,*args,**kwargs)
        if len(args)!=1 or 'dropped_args' not in cache:
            raise ValueError('Missing paired condition tokens')
        conditional=reverse.backbone(x,t,*args,**kwargs)
        if is_cond:
            baseline=conditional
        else:
            # Upstream add_flag mutates its dictionary. Keep the depth-dropped
            # prediction conditional, otherwise this measures RGB + depth.
            unconditional_args,unconditional_kwargs=reverse._make_unconditional_args(args,dict(kwargs))
            unconditional=reverse.backbone(x,t,*unconditional_args,**unconditional_kwargs)
            baseline=reverse._cfg_step(conditional,unconditional,cfg_strength)
        dropped=reverse.backbone(x,t,*cache['dropped_args'],**kwargs)
        delta=max_delta(conditional,dropped)
        stats['prediction_pairs']+=1
        stats['max_prediction_delta']=max(stats['max_prediction_delta'],delta)
        return tree_map(lambda b,c,d:b+weight*(c-d),baseline,conditional,dropped)

    try:
        pipeline.get_condition_input=condition_input
        reverse.inner_forward=inner_forward
        yield stats
    finally:
        if saved_condition is sentinel:del pipeline.get_condition_input
        else:pipeline.get_condition_input=saved_condition
        if saved_forward is sentinel:del reverse.inner_forward
        else:reverse.inner_forward=saved_forward
