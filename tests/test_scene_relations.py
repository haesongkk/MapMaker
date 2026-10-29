import json

import pytest
from PIL import Image

from mapmaker.scene_relations import prepare, verify_bundle, parse_response, graph_issues
from mapmaker.relation_experiment import collect, evaluate
from mapmaker.scene_run import write, sha


def response(subject='O001', target='O002', relation='supported_by'):
    return dict(subject=subject, target=target, relation=relation,
                evidence='visible_contact', reason='The base meets the surface.')


def test_multiple_supporters_and_unknown_are_representable():
    data = dict(relations=[response(), response(target='floor')], unresolved=['O002'])
    assert parse_response(json.dumps(data), ['O001', 'O002'], ['O001', 'O002']) == data


@pytest.mark.parametrize('data', [
    dict(relations=[response(target='invented')], unresolved=['O002']),
    dict(relations=[response(target='O001')], unresolved=['O002']),
    dict(relations=[response()], unresolved=['O001', 'O002']),
    dict(relations=[], unresolved=['O001']),
    dict(relations=[response(), response()], unresolved=['O002']),
    dict(relations=[response(relation='above')], unresolved=['O002']),
    dict(relations=[response(target='unknown')], unresolved=['O002']),
])
def test_invalid_or_incomplete_answers_are_rejected(data):
    with pytest.raises(ValueError):
        parse_response(json.dumps(data), ['O001', 'O002'], ['O001', 'O002'])


def test_cross_batch_cycle_is_flagged_after_id_mapping():
    bundle = dict(input_sha256='x', source_run_id='run',
                  objects=[dict(id='O001', object_id='a'), dict(id='O002', object_id='b')],
                  requests=[dict(id='one', subjects=['O001']), dict(id='two', subjects=['O002'])])
    result = collect(bundle, dict(one=json.dumps(dict(relations=[response()], unresolved=[])),
                                 two=json.dumps(dict(relations=[response('O002', 'O001')], unresolved=[]))))
    assert not result['valid']
    assert result['graph_issues'] == ['supported_by_cycle']
    assert result['relations'][0]['subject'] == 'a'


def test_invalid_batch_cannot_be_scored_as_abstention():
    bundle = dict(input_sha256='x', source_run_id='run', objects=[dict(id='O001', object_id='a')],
                  requests=[dict(id='one', subjects=['O001'])])
    result = collect(bundle, {'one': '{}'})
    assert not result['valid']
    with pytest.raises(ValueError):
        evaluate(result, {})


def make_run(tmp_path):
    run = tmp_path / 'run'
    run.mkdir()
    Image.new('RGB', (32, 32), 'white').save(run / 'image.png')
    Image.new('L', (32, 32), 255).save(run / 'mask.png')
    (run / 'object.glb').write_bytes(b'geometry fixture')
    obj = dict(id='original-a', name='box', status='generated', mask='mask.png',
               asset='object.glb', mask_sha256=sha(run/'mask.png'), asset_sha256=sha(run/'object.glb'))
    write(run / 'scene_metadata.json', dict(run_id='fixture', input_image='image.png',
          input_sha256=sha(run/'image.png'), objects=[obj]))
    return run


def test_bundle_integrity_and_source_preservation(tmp_path):
    run = make_run(tmp_path)
    before = {p.name: sha(p) for p in run.iterdir()}
    out = tmp_path / 'bundle'
    bundle = prepare(run, out)
    assert bundle['objects'][0]['object_id'] == 'original-a'
    assert before == {p.name: sha(p) for p in run.iterdir()}
    assert verify_bundle(out) == bundle
    (out / 'O001.png').write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash mismatch'):
        verify_bundle(out)


def test_tampered_source_rejected_before_output(tmp_path):
    run = make_run(tmp_path)
    (run / 'object.glb').write_bytes(b'changed')
    with pytest.raises(ValueError, match='mismatch'):
        prepare(run, tmp_path / 'bundle')
    assert not (tmp_path / 'bundle').exists()


def test_empty_reference_does_not_report_perfect_precision():
    prediction = dict(valid=True, input_sha256='x', objects=['a'], relations=[], unresolved=['a'])
    labels = dict(input_sha256='x', reviewer='human', review_kind='human', frozen_before_inference=True,
                  relations=[], unresolved=['a'])
    report = evaluate(prediction, labels)
    assert report['precision'] is None
    assert report['recall'] is None
    assert report['resolved_fraction'] == 0


def test_inside_is_not_a_support_edge():
    assert graph_issues([response('a', 'b', 'inside'), response('b', 'a')]) == []


def test_reciprocal_attachment_is_not_a_support_cycle():
    assert graph_issues([response('a', 'b', 'attached_to'), response('b', 'a', 'attached_to')]) == []


def test_source_run_cannot_be_used_as_output_parent(tmp_path):
    run = make_run(tmp_path)
    with pytest.raises(ValueError, match='outside'):
        prepare(run, run/'relations')
