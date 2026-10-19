from copy import deepcopy
import pytest
from mapmaker.scene_supported_refinement import source_preserved


def evidence():
    return dict(accepted=True,projection=dict(accepted=True,mask_covered_fraction=1.,silhouette_iou=.6),
        normalized_depth_median=.05,normalized_depth_p90=.2,
        visible_depth=dict(available=True,matched_rays=256,hit_fraction=1.,normalized_median=.05,normalized_p90=.2))


def test_depth_improvement_cannot_hide_missing_visible_rays():
    before=evidence();after=deepcopy(before)
    after['visible_depth'].update(normalized_median=.03,normalized_p90=.08,matched_rays=253,hit_fraction=253/256)
    assert not source_preserved(before,after)
    after['visible_depth'].update(matched_rays=256,hit_fraction=1.)
    assert source_preserved(before,after)


@pytest.mark.parametrize('section,key,value',[
    ('projection','silhouette_iou',.59),('projection','mask_covered_fraction',.99),
    ('visible_depth','normalized_p90',.21),('visible_depth','available',False)])
def test_source_guard_rejects_other_regressions(section,key,value):
    before=evidence();after=deepcopy(before);after[section][key]=value
    assert not source_preserved(before,after)
