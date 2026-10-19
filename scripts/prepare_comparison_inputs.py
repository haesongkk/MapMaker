"""Prepare 20 fixed inputs; optional upload never submits inference."""
import argparse
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapmaker.scene_pipeline import create_run
from mapmaker.scene_transfer import pack_run,ArtifactStore
from mapmaker.scene_run import sha,write,read

p=argparse.ArgumentParser();p.add_argument('--upload',action='store_true');args=p.parse_args()
root=Path('.runtime/four-way-comparison')
if not (root/'jobs.json').exists():
    inventory=read(root/'inventory.json');jobs=[]
    for mode in ('initial','expanded'):
        for source in inventory['inputs']:
            rid=uuid.uuid4().hex
            run=create_run(Path(source['input']).read_bytes(),root/'inputs'/rid)
            meta=read(run/'scene_metadata.json')
            meta['comparison_request']=dict(sample=source['id'],profile=mode)
            write(run/'scene_metadata.json',meta)
            archive=root/'inputs'/f'{rid}.zip';pack_run(run,archive,input_only=True)
            jobs.append(dict(sample=source['id'],profile=mode,run_id=rid,archive=str(archive),
                submitted=False,input=dict(protocol=1,run_id=rid,input_sha256=sha(archive),publish_web=False)))
    write(root/'jobs.json',jobs)
if args.upload:
    store=ArtifactStore();verified=[]
    for mode in ('initial','expanded'):
        folder=root/'profiles'/mode;meta=read(folder/'manifest.json');path=folder/'application.zip'
        assert sha(path)==meta['sha256']
        store.client.upload_file(str(path),store.bucket,meta['key'])
        import hashlib
        response=store.client.get_object(Bucket=store.bucket,Key=meta['key'])
        with response['Body'] as stream:assert hashlib.sha256(stream.read()).hexdigest()==meta['sha256']
        verified.append(dict(profile=mode,sha256=meta['sha256']))
    for job in read(root/'jobs.json'):
        path=Path(job['archive']);assert sha(path)==job['input']['input_sha256']
        key=store.key(job['run_id'],'input.zip');store.client.upload_file(str(path),store.bucket,key)
        response=store.client.get_object(Bucket=store.bucket,Key=key)
        with response['Body'] as stream:assert hashlib.sha256(stream.read()).hexdigest()==job['input']['input_sha256']
        verified.append(dict(run_id=job['run_id'],sha256=job['input']['input_sha256']))
    write(root/'upload-verification.json',verified)
print('20 comparison inputs prepared; uploads',args.upload,'; no inference submitted')
