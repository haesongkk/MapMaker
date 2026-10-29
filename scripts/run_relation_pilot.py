"""Submit portable relation bundles to a dedicated Runpod vLLM endpoint.

Never changes infrastructure, resubmits an ambiguous request, or modifies source runs.
"""
import argparse
import base64
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
import requests
from mapmaker.remote_settings import load_settings
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_relations import verify_bundle
from mapmaker.relation_experiment import collect
import os
import re


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('endpoint')
    p.add_argument('bundle', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--limit', type=int, default=100)
    p.add_argument('--model', default='Qwen/Qwen3-VL-8B-Instruct')
    args = p.parse_args()
    if not re.fullmatch('[a-z0-9]+', args.endpoint):
        p.error('Invalid endpoint ID')
    bundle = verify_bundle(args.bundle)
    load_settings()
    session = requests.Session()
    session.headers['Authorization'] = 'Bearer ' + os.environ['RUNPOD_API_KEY']
    base = f'https://api.runpod.ai/v2/{args.endpoint}'
    args.output.mkdir(parents=True, exist_ok=True)
    binding = dict(endpoint=args.endpoint, model=args.model, inputs_sha256=sha(args.bundle/'inputs.json'),
                   transport='runpod-vllm', image_transport='JPEG max edge 1024 quality 95',
                   sampling=dict(temperature=0, seed=42, max_tokens=2048))
    binding_path = args.output/'execution.json'
    if binding_path.exists() and read(binding_path) != binding:
        raise ValueError('Existing output belongs to different inputs or execution')
    write(binding_path, binding)
    count = 0
    responses = {}
    for request in bundle['requests']:
        job_path = args.output / (request['id']+'.json')
        if job_path.exists():
            record = read(job_path)
            if not record.get('job_id'):
                raise RuntimeError('Submission outcome unknown; inspect before retrying')
        else:
            if count >= args.limit:
                break
            content = []
            image_hashes = []
            import hashlib
            for name in request['images']:
                image = Image.open(args.bundle/name).convert('RGB')
                image.thumbnail((1024,1024), Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                image.save(buffer, format='JPEG', quality=95)
                payload = buffer.getvalue()
                image_hashes.append(dict(source=name, sha256=hashlib.sha256(payload).hexdigest()))
                content.append(dict(type='image_url', image_url=dict(
                    url='data:image/jpeg;base64,'+base64.b64encode(payload).decode())))
            content.append(dict(type='text',text=request['prompt']))
            record = dict(request_id=request['id'], state='submitting', images=image_hashes,
                          inputs_sha256=binding['inputs_sha256'])
            write(job_path,record)
            answer = session.post(base+'/run', json=dict(input=dict(
                openai_route='/v1/chat/completions', openai_input=dict(
                    model=args.model, messages=[dict(role='user', content=content)],
                    **binding['sampling'])), policy=dict(executionTimeout=600000,ttl=1800000)),timeout=90)
            answer.raise_for_status()
            record.update(job_id=answer.json()['id'],state='submitted')
            write(job_path,record)
            count += 1
            print(request['id'],record['job_id'],flush=True)
        if 'result' not in record:
            deadline=time.monotonic()+1800
            while time.monotonic()<deadline:
                answer=session.get(base+'/status/'+record['job_id'],timeout=60)
                answer.raise_for_status()
                result=answer.json()
                if result['status'] in {'COMPLETED','FAILED','CANCELLED','TIMED_OUT'}:
                    record['result']=result
                    write(job_path,record)
                    break
                time.sleep(5)
            else:
                raise TimeoutError('Job remains pending; resume with same output to poll without resubmission')
        result=record['result']
        if result['status']!='COMPLETED':
            raise RuntimeError('Job failed; inspect saved result')
        output=result['output']
        output=output[0] if isinstance(output,list) and len(output)==1 else output
        if not isinstance(output,dict) or not output.get('choices'):
            raise RuntimeError('Worker returned no completion; inspect saved result')
        choice=output['choices'][0]
        if choice['finish_reason']!='stop':
            raise RuntimeError('Incomplete completion; inspect saved result')
        responses[request['id']]=choice['message']['content']
        write(args.output/'responses.json',responses)
        print(request['id'],'complete',flush=True)
    if len(responses)==len(bundle['requests']):
        result=collect(bundle,responses)
        result['inputs_sha256']=binding['inputs_sha256']
        write(args.output/'relations.json',result)


if __name__=='__main__':
    main()
