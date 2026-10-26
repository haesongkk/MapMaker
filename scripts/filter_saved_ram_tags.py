"""Filter saved baseline tags only; never loads an image or reconstruction model."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mapmaker.qwen_background_filter import MODEL, PROMPT, parse_response
from mapmaker.scene_run import read, write, sha


def prepare(output):
    samples = read(ROOT / '.runtime/minimal-baseline/comparison.json')['samples']
    records = []
    for name, sample in samples.items():
        if sample['status'] != 'complete':
            raise ValueError(f'Incomplete baseline: {name}')
        folder = ROOT / sample['path']
        meta = read(folder / 'scene_metadata.json')
        extraction = read(folder / 'object_candidates.json')
        tags = extraction['raw_tags']
        if extraction['model'] != 'RAM++' or extraction['candidates'] != tags:
            raise ValueError(f'Not unfiltered RAM++: {name}')
        records.append(dict(sample=name, source_run=sample['path'],
                            source_metadata_sha256=sha(folder / 'scene_metadata.json'),
                            source_candidates_sha256=sha(folder / 'object_candidates.json'),
                            input_sha256=meta['input_sha256'], raw_tags=tags))
    write(output, dict(model=MODEL, prompt_template=PROMPT, samples=records))
    print(f'Prepared {len(records)} saved tag lists', flush=True)


def infer(source, output):
    import torch
    import transformers
    from transformers import AutoTokenizer, AutoModelForCausalLM
    from huggingface_hub import HfApi
    batch = read(source)
    assert batch['model'] == MODEL
    prompt_template = batch['prompt_template']
    if output.exists():
        raise ValueError('Refusing to overwrite existing results')
    revision = batch.get('model_revision') or HfApi().model_info(MODEL).sha
    print(f'Loading {MODEL} {revision}', flush=True)
    torch.set_num_threads(4)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL, revision=revision, torch_dtype=torch.bfloat16).eval().to('cuda')
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=revision)
    result = dict(model=MODEL, revision=revision, prompt_template=prompt_template,
                  image_input=False, source_sha256=sha(source),
                  transformers=transformers.__version__, torch=torch.__version__,
                  gpu=torch.cuda.get_device_name(), dtype='bfloat16',
                  generation=dict(do_sample=False, max_new_tokens=2048, seed=42), samples=[])
    write(output, result)
    for item in batch['samples']:
        prompt = prompt_template.format(ram_tags=json.dumps(item['raw_tags'], ensure_ascii=False))
        text = tokenizer.apply_chat_template([{'role': 'user', 'content': prompt}],
                                            tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(text, return_tensors='pt').to('cuda')
        torch.manual_seed(42)
        started = time.monotonic()
        with torch.inference_mode():
            generated = model.generate(**inputs, do_sample=False, max_new_tokens=2048)
        tokens = generated[0, inputs.input_ids.shape[1]:]
        raw = tokenizer.decode(tokens, skip_special_tokens=True)
        record = dict(item, prompt=prompt, raw_response=raw,
                      elapsed_seconds=time.monotonic()-started, generated_tokens=len(tokens))
        try:
            if len(tokens) >= 2048:
                raise ValueError('Token limit reached')
            record['kept_tags'] = parse_response(raw, item['raw_tags'])
            from collections import Counter
            counts = Counter(record['kept_tags'])
            removed = []
            for tag in item['raw_tags']:
                if counts[tag]:
                    counts[tag] -= 1
                else:
                    removed.append(tag)
            record.update(removed_tags=removed, status='complete')
        except ValueError as exc:
            record.update(status='failed', error=str(exc))
        result['samples'].append(record)
        write(output, result)
        print(item['sample'], record['status'], raw, flush=True)


def report(source, output):
    result = read(source)
    inputs = source.with_name('inputs.json')
    batch = read(inputs)
    assert result['source_sha256'] == sha(inputs)
    assert result['model'] == MODEL and result['prompt_template'] == PROMPT
    assert len(result['samples']) == len(batch['samples']) == 10
    lines = ['# RAM++ + Qwen 텍스트 배경 필터 v1', '',
             '기존 1번 실행의 RAM++ 태그 목록만 Qwen에 입력했다. 이미지 입력과 RAM++·SAM3·SAM3D 재실행은 없다.', '',
             f"모델: `{result['model']}` / revision `{result['revision']}`.", '',
             'BF16, greedy decoding, seed 42, 최대 2048 새 토큰. 추가 시스템 메시지 없이 아래 사용자 프롬프트를 모델 기본 채팅 템플릿에 넣었다.', '',
             '응답의 JSON 코드블록 포장만 벗겨 읽었다. 원문 응답과 최초 파싱 오류는 보존했으며, 재추론이나 의미 수정은 하지 않았다.', '',
             '```text', PROMPT, '```', '',
             '| 입력 | 원본 태그 수 | 유지 수 | 제거된 태그 |',
             '|---|---:|---:|---|']
    for expected, record in zip(batch['samples'], result['samples']):
        assert all(record[k] == v for k, v in expected.items())
        folder = ROOT / record['source_run']
        assert sha(folder / 'object_candidates.json') == record['source_candidates_sha256']
        assert sha(folder / 'scene_metadata.json') == record['source_metadata_sha256']
        assert record['status'] == 'complete', record
        assert record['kept_tags'] == parse_response(record['raw_response'], record['raw_tags'])
        assert record['prompt'] == PROMPT.format(ram_tags=json.dumps(record['raw_tags'], ensure_ascii=False))
        removed = ', '.join(record['removed_tags']) or '없음'
        lines.append(f"| {record['sample']} | {len(record['raw_tags'])} | {len(record['kept_tags'])} | {removed} |")
    lines.extend(['', '## 샘플별 유지 태그', ''])
    for record in result['samples']:
        lines.extend([f"### {record['sample']}", '', ', '.join(record['kept_tags']) or '(없음)', ''])
    lines.extend(['## 원본 증거', '',
                  '[입력 목록](assets/ram-qwen-filter-v1/inputs.json) · [Qwen 원문 응답과 결과](assets/ram-qwen-filter-v1/results.json) · [최초 실행 기록](assets/ram-qwen-filter-v1/raw-results.json)', '',
                  '이 결과는 태그 필터 판정이며, 3D 장면을 수정하거나 품질 개선을 검증한 결과가 아니다.', ''])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('\n'.join(lines), encoding='utf-8')
    print(f'Verified and reported {len(result["samples"])} samples', flush=True)


def reparse(source, output):
    """Re-read preserved responses; no model calls or semantic changes."""
    from collections import Counter
    result = read(source)
    result['raw_results_sha256'] = sha(source)
    result['parsing_policy'] = 'read_single_json_code_fence_allow_plain_trailing_explanation_then_validate_subset'
    for record in result['samples']:
        record['original_parse_status'] = record['status']
        if 'error' in record:
            record['original_parse_error'] = record.pop('error')
        if record['generated_tokens'] >= 2048:
            raise ValueError('Token limit reached')
        record['kept_tags'] = parse_response(record['raw_response'], record['raw_tags'], allow_trailing_explanation=True)
        counts = Counter(record['kept_tags'])
        removed = []
        for tag in record['raw_tags']:
            if counts[tag]:
                counts[tag] -= 1
            else:
                removed.append(tag)
        record.update(status='complete', removed_tags=removed)
    write(output, result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'infer', 'report', 'reparse'])
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare(args.output)
    elif args.action == 'infer':
        infer(args.input, args.output)
    elif args.action == 'report':
        report(args.input, args.output)
    else:
        reparse(args.input, args.output)
