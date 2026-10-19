import copy

import pytest

from scripts.alignment_reference import alignment_objects


def test_excluded_node_remains_in_original_alignment_reference():
    meta = {'objects': [
        {'id': 'a', 'status': 'generated', 'placement': {'original_matrix': 'a'}},
        {'id': 'b', 'status': 'duplicate', 'placement': {'original_matrix': 'b'}}],
        'placement': {'object_ids': ['a', 'b']}}
    assert [o['id'] for o in alignment_objects(meta)] == ['a', 'b']
    original = copy.deepcopy(meta)
    for invalid in (['a', 'a'], ['b'], ['a', 'missing']):
        meta['placement']['object_ids'] = invalid
        with pytest.raises(ValueError):
            alignment_objects(meta)
    meta = original
    meta['objects'][1]['placement'].clear()
    with pytest.raises(ValueError, match='original alignment transform'):
        alignment_objects(meta)


def test_legacy_artifact_without_reference_set_uses_generated_objects():
    meta = {'objects': [{'id': 'a', 'status': 'generated'},
                        {'id': 'b', 'status': 'duplicate'}], 'placement': {}}
    assert alignment_objects(meta) == [meta['objects'][0]]
