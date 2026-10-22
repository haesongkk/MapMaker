"""Qwen tag generation in an isolated process; no semantic post-filtering."""
import json
import os
import re
from pathlib import Path
import subprocess
import shutil
import sys

from .scene_run import ROOT, read, write, sha, status
from .runtime_paths import VISION_PYTHON

MODEL = 'Qwen/Qwen2.5-VL-7B-Instruct'
REVISION = 'cc594898137f460bfe9f0759e9844b3ce807cfb5'
PROMPT = '''Identify the distinct categories of clearly visible, standalone physical
objects in this image for text-prompted instance segmentation and individual
3D reconstruction.

Include furniture and separate objects such as cushions, books, plants,
lamps, and decorative objects. Include doors and windows as well.

Exclude architectural background such as walls, floors, ceilings, and the room
itself. Exclude shadows, reflections, materials, colors, and abstract scene labels.

Name each object as a whole. Do not separately list attached components such as
handles, drawers, legs, frames, or keyholes when they belong to an object already
listed. Treat door handles and window frames as parts of doors and windows.

Use short, common English noun phrases with spaces, not underscores.
List each object category once, even when multiple instances are visible.
Avoid synonyms or overlapping names for the same category.
Do not infer objects that are not clearly visible.

Return only a JSON array of strings.'''


def parse_tags(text):
    # Models may wrap valid JSON in a single Markdown code block. Unwrap only
    # that presentation layer; never extract a substring from mixed prose.
    fenced = re.fullmatch(r'\s*```(?:json)?[ \t]*\r?\n(.*?)\r?\n```\s*', text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    value = json.loads(text)
    if not isinstance(value, list) or not value or any(
            not isinstance(tag, str) or not tag.strip() for tag in value):
        raise ValueError('Qwen must return a nonempty JSON array of nonempty strings')
    return value  # Preserve exact strings, order, and repeated labels.


def prepare_and_run(run, env, log):
    overlay = ROOT / '.runtime/qwen-deps-4.51.3'
    marker = overlay / '.ready'
    child_env = dict(env, HF_HUB_OFFLINE='0', TRANSFORMERS_OFFLINE='0')
    if not marker.exists():
        status(run, 'loading', 'Preparing isolated Qwen dependencies...')
        installer = (['uv', 'pip', 'install', '--python', str(VISION_PYTHON)]
                     if shutil.which('uv') else [str(VISION_PYTHON), '-m', 'pip', 'install'])
        subprocess.run(installer + ['--target', str(overlay), '--no-deps',
            'transformers==4.51.3', 'tokenizers==0.21.4'],
            env=child_env, stdout=log, stderr=subprocess.STDOUT, check=True)
        marker.touch()
    child_env['PYTHONPATH'] = str(overlay) + os.pathsep + env['PYTHONPATH']
    subprocess.run([str(VISION_PYTHON), '-m', 'mapmaker.qwen_tags', str(run)],
        cwd=ROOT, env=child_env, stdout=log, stderr=subprocess.STDOUT, check=True)


def run_tags(run):
    import torch
    import transformers
    from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
    from PIL import Image
    run = Path(run)
    meta = read(run / 'scene_metadata.json')
    status(run, 'analyzing', 'Loading Qwen2.5-VL-7B-Instruct...')
    processor = AutoProcessor.from_pretrained(MODEL, revision=REVISION)
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        MODEL, revision=REVISION, torch_dtype=torch.bfloat16).eval().to('cuda')
    messages = [{'role':'user', 'content':[
        {'type':'image'}, {'type':'text','text':PROMPT}]}]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    image = Image.open(run / meta['input_image']).convert('RGB')
    inputs = processor(text=[text], images=[image], padding=True, return_tensors='pt').to('cuda')
    torch.manual_seed(42)
    status(run, 'analyzing', 'Generating Qwen image tags...')
    with torch.inference_mode():
        result = model.generate(**inputs, max_new_tokens=2048, do_sample=False)
    generated = result[:, inputs.input_ids.shape[1]:]
    raw = processor.batch_decode(generated, skip_special_tokens=True,
                                clean_up_tokenization_spaces=False)[0]
    evidence = dict(model=MODEL, revision=REVISION, prompt=PROMPT, raw_response=raw,
        input_sha256=sha(run/meta['input_image']), transformers=transformers.__version__,
        generation=dict(max_new_tokens=2048, do_sample=False, seed=42),
        image_processor_policy='model_default', generated_tokens=generated.shape[1])
    write(run/'logs/qwen_response.json', evidence)
    if generated.shape[1] >= 2048:
        raise ValueError('Qwen hit the token limit; refusing a potentially incomplete tag list')
    evidence['tags'] = parse_tags(raw)
    write(run/'logs/qwen_response.json', evidence)


if __name__ == '__main__':
    run_tags(Path(sys.argv[1]))
