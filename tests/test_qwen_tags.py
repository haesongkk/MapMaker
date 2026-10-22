import json
import pytest
from mapmaker.qwen_tags import parse_tags


@pytest.mark.parametrize('wrapper', ['{}', '```json\n{}\n```', '```\n{}\n```', ' \n```JSON\r\n{}\r\n```\n'])
def test_qwen_tags_preserve_structures_small_items_case_order_and_duplicates(wrapper):
    tags = ['wall', 'Pillow', 'chair', 'chair', 'tiny cup', ' desk ']
    assert parse_tags(wrapper.format(json.dumps(tags))) == tags


@pytest.mark.parametrize('raw', ['{"tags":["chair"]}', '["chair", 2]', '[]',
                                  '["chair", " "]', '["chair",', '```json\n["chair"]',
                                  'Here are tags:\n```json\n["chair"]\n```',
                                  '```json\n["chair"]\n```\nExplanation',
                                  '```python\n["chair"]\n```'])
def test_invalid_qwen_response_is_not_silently_filtered(raw):
    with pytest.raises(ValueError):
        parse_tags(raw)
