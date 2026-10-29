"""CLI for prepare, local Qwen inference, response import and independent evaluation."""
import argparse
import json
import time
from pathlib import Path

from .scene_run import read, write, sha
from .scene_relations import prepare, verify_bundle, parse_response, graph_issues


def collect(bundle, responses):
    catalog = {o['id']: o['object_id'] for o in bundle['objects']}
    expected = {r['id'] for r in bundle['requests']}
    if set(responses) != expected:
        raise ValueError('Responses must match all request IDs exactly')
    records, relations, unresolved = [], [], []
    for request in bundle['requests']:
        raw = responses[request['id']]
        row = dict(request_id=request['id'], raw_response=raw)
        try:
            parsed = parse_response(raw, catalog, request['subjects'])
            for relation in parsed['relations']:
                relation = dict(relation)
                relation['subject'] = catalog[relation['subject']]
                relation['target'] = catalog.get(relation['target'], relation['target'])
                relations.append(relation)
            unresolved.extend(catalog[x] for x in parsed['unresolved'])
            row['status'] = 'valid'
        except (ValueError, TypeError) as exc:
            row.update(status='invalid', error=str(exc))
        records.append(row)
    issues = graph_issues(relations)
    return dict(input_sha256=bundle['input_sha256'], source_run_id=bundle['source_run_id'],
                objects=[o['object_id'] for o in bundle['objects']], records=records,
                relations=relations, unresolved=unresolved, graph_issues=issues,
                valid=all(r['status'] == 'valid' for r in records) and not issues,
                geometry_modified=False, quality_verified=False)


def infer(bundle_path, output, model_name, revision):
    # Lazy imports: preparation, validation and evaluation require no GPU dependencies.
    import torch
    import transformers
    from PIL import Image
    from transformers import AutoProcessor
    from huggingface_hub import HfApi
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA required for this inference runner')
    bundle_path, output = Path(bundle_path), Path(output)
    bundle = verify_bundle(bundle_path)
    if output.exists():
        raise ValueError('Output already exists')
    classes = {
        'Qwen/Qwen2.5-VL-7B-Instruct': 'Qwen2_5_VLForConditionalGeneration',
        'Qwen/Qwen3-VL-8B-Instruct': 'Qwen3VLForConditionalGeneration',
    }
    if model_name not in classes:
        raise ValueError('Unsupported model')
    cls = getattr(transformers, classes[model_name], None)
    if cls is None:
        raise RuntimeError(f'Installed transformers lacks {classes[model_name]}')
    revision = HfApi().model_info(model_name, revision=revision).sha
    output.mkdir(parents=True)
    evidence = dict(model=model_name, revision=revision,
                    inputs_sha256=sha(bundle_path / 'inputs.json'),
                    transformers=transformers.__version__, torch=torch.__version__,
                    gpu=torch.cuda.get_device_name(), generation=dict(seed=42, do_sample=False,
                    max_new_tokens=2048), requests=[])
    write(output / 'execution.json', evidence)
    processor = AutoProcessor.from_pretrained(model_name, revision=revision)
    model = cls.from_pretrained(model_name, revision=revision,
                               torch_dtype=torch.bfloat16).eval().to('cuda')
    responses = {}
    for request in bundle['requests']:
        images = [Image.open(bundle_path / p).convert('RGB') for p in request['images']]
        content = [{'type': 'image'} for _ in images] + [{'type': 'text', 'text': request['prompt']}]
        text = processor.apply_chat_template([dict(role='user', content=content)],
                                             tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[text], images=images, return_tensors='pt', padding=True).to('cuda')
        torch.manual_seed(42)
        started = time.monotonic()
        with torch.inference_mode():
            generated = model.generate(**inputs, **{k: v for k, v in evidence['generation'].items() if k != 'seed'})
        tokens = generated[:, inputs.input_ids.shape[1]:]
        raw = processor.batch_decode(tokens, skip_special_tokens=True,
                                     clean_up_tokenization_spaces=False)[0]
        responses[request['id']] = raw
        evidence['requests'].append(dict(id=request['id'], seconds=time.monotonic()-started,
                                        generated_tokens=tokens.shape[1],
                                        token_limit_reached=tokens.shape[1] >= 2048))
        write(output / 'responses.json', responses)
        write(output / 'execution.json', evidence)
        if tokens.shape[1] >= 2048:
            raise RuntimeError('Token limit reached; raw response saved, inference incomplete')
    result = collect(bundle, responses)
    result['inputs_sha256'] = evidence['inputs_sha256']
    write(output / 'relations.json', result)
    return result


def relation_set(data):
    return {(r['subject'], r['relation'], r['target']) for r in data['relations']}


def evaluate(prediction, labels):
    if not prediction['valid']:
        raise ValueError('Invalid prediction cannot be scored as a valid scene')
    if (not labels.get('reviewer') or labels.get('frozen_before_inference') is not True
            or labels.get('review_kind') not in {'human', 'agent_preliminary'}):
        raise ValueError('Attributed labels with explicit review kind must be frozen before inference')
    if labels['input_sha256'] != prediction['input_sha256']:
        raise ValueError('Evaluation image mismatch')
    expected, actual = relation_set(labels), relation_set(prediction)
    ambiguous = set(labels['unresolved'])
    covered = {x[0] for x in expected}
    ids = set(prediction['objects'])
    if ambiguous & covered or ambiguous | covered != ids:
        raise ValueError('Labels must cover the same objects, with no resolved/unresolved overlap')
    if any(a not in ids or b not in ids | {'floor', 'wall', 'ceiling', 'unknown'}
           or k not in {'supported_by', 'attached_to', 'inside'} for a, k, b in expected):
        raise ValueError('Invalid reference relation')
    if graph_issues(labels['relations']):
        raise ValueError('Reference relations contain cycles')
    scored = {r for r in actual if r[0] not in ambiguous}
    correct = len(scored & expected)
    return dict(review_kind=labels['review_kind'], human_verified=labels['review_kind']=='human',
                reference_relations=len(expected), predicted_relations=len(scored),
                precision=correct / len(scored) if scored else None,
                recall=correct / len(expected) if expected else None,
                resolved_fraction=len({r[0] for r in actual}) / len(ids),
                ambiguous_subjects=len(ambiguous),
                asserted_on_ambiguous=len({r[0] for r in actual} & ambiguous),
                missing=sorted(expected-scored), extra=sorted(scored-expected),
                scope='relation_extraction_only_not_geometry_quality')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('run', type=Path)
    prep.add_argument('output', type=Path)
    prep.add_argument('--batch-size', type=int, default=4)
    prep.add_argument('--reverse', action='store_true')
    inf = commands.add_parser('infer')
    inf.add_argument('bundle', type=Path)
    inf.add_argument('output', type=Path)
    inf.add_argument('--model', default='Qwen/Qwen2.5-VL-7B-Instruct')
    inf.add_argument('--revision', required=True)
    imp = commands.add_parser('import-responses')
    imp.add_argument('bundle', type=Path)
    imp.add_argument('responses', type=Path)
    imp.add_argument('output', type=Path)
    ev = commands.add_parser('evaluate')
    ev.add_argument('prediction', type=Path)
    ev.add_argument('labels', type=Path)
    ev.add_argument('output', type=Path)
    compare = commands.add_parser('compare-order')
    compare.add_argument('first', type=Path)
    compare.add_argument('second', type=Path)
    compare.add_argument('output', type=Path)
    args = p.parse_args()
    if args.output.exists():
        p.error('Output already exists')
    if args.command == 'prepare':
        prepare(args.run, args.output, batch_size=args.batch_size, reverse=args.reverse)
    elif args.command == 'infer':
        infer(args.bundle, args.output, args.model, args.revision)
    elif args.command == 'import-responses':
        result = collect(verify_bundle(args.bundle), read(args.responses))
        result['inputs_sha256'] = sha(args.bundle / 'inputs.json')
        write(args.output, result)
    elif args.command == 'evaluate':
        write(args.output, evaluate(read(args.prediction), read(args.labels)))
    else:
        a, b = read(args.first), read(args.second)
        if (a['input_sha256'] != b['input_sha256'] or set(a['objects']) != set(b['objects'])
                or not a['valid'] or not b['valid']):
            raise ValueError('Order comparison requires valid results for the same image and objects')
        x, y = relation_set(a), relation_set(b)
        changed = {r[0] for r in x ^ y} | (set(a['unresolved']) ^ set(b['unresolved']))
        write(args.output, dict(consistent_objects=len(a['objects'])-len(changed),
                               objects=len(a['objects']), changed=sorted(changed),
                               only_first=sorted(x-y), only_second=sorted(y-x),
                               scope='consistency_not_accuracy'))
    print(args.output)


if __name__ == '__main__':
    main()
