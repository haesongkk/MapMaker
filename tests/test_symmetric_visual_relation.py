import pytest
from mapmaker.visual_relation import reconcile_same_object


@pytest.mark.parametrize('relation', ['same_object','separate_objects','uncertain'])
def test_consistent_outputs_remain_evidence_only(relation):
    response = '{"relation":"'+relation+'"}'
    result = reconcile_same_object(response, response)
    assert result['relation'] == relation and result['order_consistent']
    assert result['suppression_authorized'] is False


@pytest.mark.parametrize('response', [None, '{}', '[]', '{"relation":"part_of"}',
    '{"relation":"same_object","name":"anything"}',
    '{"relation":"same_object","relation":"same_object"}',
    '{"relation":["same_object"]}', '```json\n{"relation":"same_object"}\n```'])
def test_malformed_or_unexpected_output_retains_ambiguity(response):
    result = reconcile_same_object(response, '{"relation":"same_object"}')
    assert result['relation'] == 'uncertain'
    assert result['malformed'] and not result['suppression_authorized']


def test_order_disagreement_does_not_authorize_removal():
    result = reconcile_same_object('{"relation":"same_object"}', '{"relation":"separate_objects"}')
    assert result['relation'] == 'uncertain'
    assert not result['order_consistent'] and not result['suppression_authorized']
