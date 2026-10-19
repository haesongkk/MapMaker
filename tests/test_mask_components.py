import numpy as np
from mapmaker.mask_components import partition_evidence


def sample(gap_depth=5.):
    y,x=np.mgrid[:100,:100]
    mask=np.zeros((100,100),bool);mask[25:75,15:35]=True;mask[25:75,65:85]=True
    depth=np.full((100,100),gap_depth);depth[mask]=2.
    points=np.stack([(x-50)/80*depth,(y-50)/80*depth,depth],-1)
    return mask,points


def test_background_gap_partitions_without_losing_tiny_island():
    mask,points=sample();mask[18:20,18:20]=True
    points[18:20,18:20,2]=2.
    parts,report=partition_evidence(mask,points)
    assert report['accepted'] and len(parts)==2
    assert np.array_equal(np.logical_or.reduce(parts),mask)
    assert sum(p.sum() for p in parts)==mask.sum()


def test_foreground_occluder_and_same_depth_connection_preserve_one_unit():
    for gap in [1.,2.]:
        mask,points=sample(gap)
        parts,report=partition_evidence(mask,points)
        assert not report['accepted'] and len(parts)==1


def test_unknown_gap_and_image_boundary_do_not_prove_separation():
    mask,points=sample();points[:,40:60]=np.nan
    assert not partition_evidence(mask,points)[1]['accepted']
    mask,points=sample();mask[:25,15:35]=True
    assert not partition_evidence(mask,points)[1]['accepted']


def test_units_are_invariant_to_metric_scale():
    mask,points=sample()
    a,_=partition_evidence(mask,points)
    b,_=partition_evidence(mask,points*100)
    assert len(a)==len(b)
    assert all(np.array_equal(x,y) for x,y in zip(a,b))
