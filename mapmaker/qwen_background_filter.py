"""Text-only RAM++ background filtering, prompt v1."""
import json
import re
from collections import Counter
from pathlib import Path

from .scene_run import read, write, sha

TAGGER = 'ram++-qwen-background-v1'
MODEL = 'Qwen/Qwen2.5-7B-Instruct'
PROMPT = '''Remove tags that refer to scene backgrounds from the following list.

Return the remaining tags as a JSON array.
Do not add or rename tags.

Tags: {ram_tags}'''


def parse_response(raw, tags, *, allow_trailing_explanation=False):
    suffix = r'\s*(?:[^\[\]`]*?)\s*' if allow_trailing_explanation else r'\s*'
    fenced = re.fullmatch(r'\s*```(?:json)?[ \t]*\r?\n(.*?)\r?\n```' + suffix,
                          raw, re.DOTALL | re.IGNORECASE)
    if fenced:
        raw = fenced.group(1)
    value = json.loads(raw)
    if not isinstance(value, list) or any(not isinstance(t, str) for t in value):
        raise ValueError('Filter must return a JSON array of strings')
    if Counter(value) - Counter(tags):
        raise ValueError('Filter added, renamed, or duplicated tags')
    # SAM3 sees the original RAM++ ordering, including retained repetitions.
    remaining = Counter(value)
    kept = []
    for tag in tags:
        if remaining[tag]:
            kept.append(tag)
            remaining[tag] -= 1
    return kept


def load_result(run):
    run = Path(run)
    meta = read(run / 'scene_metadata.json')
    candidates = read(run / 'logs/ram_filter_input.json')
    evidence = read(run / 'logs/qwen_filter_response.json')
    expected = PROMPT.format(ram_tags=json.dumps(candidates['tags'], ensure_ascii=False))
    if (candidates['input_sha256'] != sha(run / meta['input_image']) or
            evidence['input_sha256'] != candidates['input_sha256'] or
            evidence['raw_tags'] != candidates['tags'] or
            evidence['model'] != MODEL or evidence['prompt'] != expected):
        raise ValueError('Background filter provenance mismatch')
    tags = parse_response(evidence['raw_response'], candidates['tags'])
    if evidence['tags'] != tags:
        raise ValueError('Background filter result differs from raw response')
    return tags, evidence


def extract(run):
    from .initial_vision import ram_tags
    from .runtime_paths import RAM_CHECKPOINT
    run = Path(run)
    meta = read(run / 'scene_metadata.json')
    image = run / meta['input_image']
    tags = ram_tags([image], RAM_CHECKPOINT)[str(image)]
    write(run / 'logs/ram_filter_input.json', dict(
        tags=tags, input_sha256=sha(image), threshold_policy='model_default'))


def filter_tags(run):
    import torch
    import transformers
    from transformers import AutoTokenizer, AutoModelForCausalLM
    run = Path(run)
    source = read(run / 'logs/ram_filter_input.json')
    prompt = PROMPT.format(ram_tags=json.dumps(source['tags'], ensure_ascii=False))
    model = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.bfloat16).eval().to('cuda')
    revision = model.config._commit_hash
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=revision)
    text = tokenizer.apply_chat_template(
        [{'role': 'user', 'content': prompt}], tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors='pt').to('cuda')
    torch.manual_seed(42)
    with torch.inference_mode():
        output = model.generate(**inputs, do_sample=False, max_new_tokens=2048)
    tokens = output[0, inputs.input_ids.shape[1]:]
    raw = tokenizer.decode(tokens, skip_special_tokens=True)
    evidence = dict(model=MODEL, revision=revision, prompt_version='v1', prompt=prompt,
                    raw_tags=source['tags'], input_sha256=source['input_sha256'],
                    raw_response=raw, image_input=False, transformers=transformers.__version__,
                    generation=dict(do_sample=False, max_new_tokens=2048, seed=42))
    path = run / 'logs/qwen_filter_response.json'
    write(path, evidence)
    if len(tokens) >= 2048:
        raise ValueError('Background filter response reached token limit')
    evidence['tags'] = parse_response(raw, source['tags'])
    write(path, evidence)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['extract', 'filter'])
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    (extract if args.stage == 'extract' else filter_tags)(args.run)
