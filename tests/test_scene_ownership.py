import numpy as np
from mapmaker.scene_ownership import composite_residuals


def fixture():
    y,x=np.mgrid[:100,:100]
    points=np.stack([x/100,y/100,1+x/200],-1)
    parent=np.zeros((100,100),bool);parent[5:95,5:95]=True
    first=np.zeros_like(parent);first[10:35,10:90]=True
    second=np.zeros_like(parent);second[60:85,10:90]=True
    return dict(parent=parent,first=first,second=second),points


def test_composite_preserves_children_and_unique_parent_pixels():
    masks,points=fixture();original={key:mask.copy() for key,mask in masks.items()}
    result=composite_residuals(masks,points)
    assert set(result)=={'parent'}
    residual,evidence=result['parent']
    assert not np.any(residual & (masks['first']|masks['second']))
    assert np.array_equal(residual | masks['first'] | masks['second'], masks['parent'])
    assert all(np.array_equal(masks[key],original[key]) for key in masks)
    renamed=composite_residuals({str(i):mask for i,mask in enumerate(masks.values())},points)
    np.testing.assert_array_equal(renamed['0'][0],residual)


def test_two_tiny_props_do_not_turn_whole_furniture_into_residual():
    masks,points=fixture()
    for key,offset in [('first',20),('second',60)]:
        masks[key][:]=False;masks[key][offset:offset+9,offset:offset+9]=True
    assert not composite_residuals(masks,points)


def test_bad_depth_or_one_contained_object_abstains():
    masks,points=fixture();points[:50]=np.nan
    assert not composite_residuals(masks,points)
    masks,points=fixture();masks.pop('second')
    assert not composite_residuals(masks,points)
