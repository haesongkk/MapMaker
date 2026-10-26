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



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['infer'])
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    infer(args.input, args.output)
