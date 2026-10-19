import copy
import pytest
from mapmaker.reconstruction_schedule import ranked_depth_retries


def item(key, error, **ray_changes):
    ray=dict(available=True,matched_rays=128,hit_fraction=.8,normalized_median=error)
    ray.update(ray_changes)
    return dict(id='name_'+key,label='plant',status='generated',mask_sha256=key*64,
        reconstruction_review=dict(original=dict(accepted=True,retry_recommended=True,visible_depth=ray)))


def test_scene_ranking_ignores_labels_input_order_and_hash_order_except_ties():
    rows=[item('a',.12),item('b',.32),item('c',.27),item('d',.27)]
    assert [o['mask_sha256'] for o in ranked_depth_retries(rows)]==['b'*64,'c'*64]
    renamed=copy.deepcopy(list(reversed(rows)))
    for i,row in enumerate(renamed):
        row['id']=str(i);row.pop('label')
    assert [o['mask_sha256'] for o in ranked_depth_retries(renamed)]==['b'*64,'c'*64]
    assert len(ranked_depth_retries(rows,1))==1
    assert ranked_depth_retries(rows,0)==[]


def test_unreliable_failed_and_low_error_objects_do_not_consume_budget():
    rows=[item('a',.9,hit_fraction=.2),item('b',.8,matched_rays=10),
          item('c',float('nan')),item('d',.1),item('e',.4),item('f',.5)]
    rows[-1]['status']='failed'
    assert [o['mask_sha256'] for o in ranked_depth_retries(rows)]==['e'*64]
    with pytest.raises(ValueError):ranked_depth_retries([item('a',.2),item('a',.3)])
    with pytest.raises(ValueError):ranked_depth_retries(rows,3)
