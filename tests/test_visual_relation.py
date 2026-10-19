import json

import pytest

from mapmaker.visual_relation import INVERSE, parse_relation, reconcile_relations


@pytest.mark.parametrize("relation", INVERSE)
def test_reverse_order_maps_back_to_same_relation(relation):
    result = reconcile_relations(json.dumps({"relation": relation}),
                                 json.dumps({"relation": INVERSE[relation]}))
    assert result["relation"] == relation
    assert result["order_consistent"]
    assert not result["suppression_authorized"]


@pytest.mark.parametrize("response", [
    '{"relation":"part_of","relation":"independent"}',
    '{"relation":"part_of","object_name":"anything"}',
    '```json\n{"relation":"part_of"}\n```',
    '{"relation":[]}', 'null', '[]', '{"relation":"PART_OF"}',
    '{"relation":"part_of"} trailing', None,
])
def test_malformed_response_never_becomes_suppression(response):
    assert parse_relation(response) is None
    result = reconcile_relations('{"relation":"part_of"}', response)
    assert result["malformed"] and result["relation"] == "uncertain"
    assert not result["suppression_authorized"]


def test_part_of_in_both_orders_is_inconsistent():
    result = reconcile_relations('{"relation":"part_of"}', '{"relation":"part_of"}')
    assert result["relation"] == "uncertain"
    assert not result["order_consistent"]
