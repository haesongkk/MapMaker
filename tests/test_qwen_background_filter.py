import json
import pytest

from mapmaker.qwen_background_filter import PROMPT, MODEL, parse_response, load_result
from mapmaker.scene_run import write, sha


def test_prompt_is_exact_v1():
    assert PROMPT == ('Remove tags that refer to scene backgrounds from the following list.\n\n'
                      'Return the remaining tags as a JSON array.\n'
                      'Do not add or rename tags.\n\nTags: {ram_tags}')


def test_subset_preserves_original_strings_order_and_multiplicity():
    assert parse_response('["chair", "Cup", "chair"]',
                          ['wall', 'Cup', 'chair', 'floor', 'chair']) == ['Cup', 'chair', 'chair']
    assert parse_response('[]', ['wall', 'floor']) == []
    assert parse_response('```json\n["chair"]\n```', ['wall', 'chair']) == ['chair']


def test_saved_empty_answer_with_explanation_requires_explicit_opt_in():
    raw='```json\n[]\n```\n\nNone of the tags refer to movable objects.'
    with pytest.raises(ValueError):
        parse_response(raw,['wall'])
    assert parse_response(raw,['wall'],allow_trailing_explanation=True)==[]
    with pytest.raises(ValueError):
        parse_response('```json\n[]\n```\n["chair"]',['chair'],allow_trailing_explanation=True)


@pytest.mark.parametrize('raw', ['["sofa"]', '["Chair"]', '["chair", "chair"]',
                                  '{}', '[1]', 'Here: ["chair"]'])
def test_invalid_or_invented_output_fails(raw):
    with pytest.raises(ValueError):
        parse_response(raw, ['wall', 'chair'])


def test_saved_evidence_is_bound_to_input_and_response(tmp_path):
    image = tmp_path / 'image.png'
    image.write_bytes(b'input')
    write(tmp_path / 'scene_metadata.json', {'input_image': image.name})
    tags = ['wall', 'chair']
    write(tmp_path / 'logs/ram_filter_input.json', {'input_sha256': sha(image), 'tags': tags})
    record = dict(model=MODEL, input_sha256=sha(image), raw_tags=tags,
                  prompt=PROMPT.format(ram_tags=json.dumps(tags)),
                  raw_response='["chair"]', tags=['chair'])
    write(tmp_path / 'logs/qwen_filter_response.json', record)
    assert load_result(tmp_path)[0] == ['chair']
    record['tags'] = ['wall']
    write(tmp_path / 'logs/qwen_filter_response.json', record)
    with pytest.raises(ValueError):
        load_result(tmp_path)
    record['tags'] = ['chair']
    write(tmp_path / 'logs/qwen_filter_response.json', record)
    image.write_bytes(b'other input')
    with pytest.raises(ValueError):
        load_result(tmp_path)


def test_cli_selects_filtered_baseline(tmp_path, monkeypatch):
    from PIL import Image
    from typer.testing import CliRunner
    from mapmaker.cli import app
    import mapmaker.scene_pipeline as pipeline
    from mapmaker.scene_run import read
    image = tmp_path / 'input.png'
    Image.new('RGB', (8, 8)).save(image)
    seen = []

    class FakePipeline:
        def run(self, path):
            seen.append(read(path / 'scene_metadata.json')['execution'])

        def close(self):
            pass

    monkeypatch.setattr(pipeline, 'configured_pipeline', FakePipeline)
    result = CliRunner().invoke(app, ['run', str(image), '--output', str(tmp_path / 'run'),
                                     '--mode', '1', '--background-filter'])
    assert result.exit_code == 0, result.output
    assert seen[0]['mode'] == 1
    assert seen[0]['tagger'] == 'ram++-qwen-background-v1'
    result = CliRunner().invoke(app, ['run', str(image), '--background-filter'])
    assert result.exit_code != 0
