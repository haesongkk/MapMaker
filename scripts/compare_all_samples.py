"""Fresh production HTTP runs for every sample; immutable before mapping and evidence."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pixels(path):
    with Image.open(path) as image:
        im = ImageOps.exif_transpose(image).convert('RGB')
        return hashlib.sha256(str(im.size).encode() + im.tobytes()).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def prepare(path):
    if path.exists():
        raise FileExistsError(path)
    report = {'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'branch': subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip(),
              'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              'base_url': 'http://127.0.0.1:8082', 'fresh_inference_requested': True,
              'implementation_sha256': {p.relative_to(ROOT).as_posix(): digest(p) for p in (ROOT/'mapmaker').glob('*.py')},
              'samples': []}
    candidates = {}
    for meta_path in (ROOT/'runs').glob('*/scene_metadata.json'):
        meta = read(meta_path)
        run = meta_path.parent
        if meta.get('placement') or meta.get('validation_replay') or not (run/'scene.glb').is_file():
            continue
        if read(run/'status.json')['stage'] != 'done':
            continue
        key = pixels(run/meta['input_image'])
        candidates.setdefault(key, []).append((meta.get('created_at', ''), run.name))
    for i, source in enumerate(sorted((ROOT/'samples').rglob('*'), key=lambda p:p.as_posix().lower()), 1):
        if not source.is_file() or source.suffix.lower() not in EXTENSIONS:
            continue
        sample = source.relative_to(ROOT).as_posix()
        sid = hashlib.sha256(sample.encode()).hexdigest()[:12]
        asset = ROOT/'docs/assets/sample_comparison'/sid
        asset.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as im:
            im = ImageOps.exif_transpose(im).convert('RGB')
            size = list(im.size)
            im.thumbnail((640, 480))
            im.save(asset/'input.jpg', quality=88)
        matches = sorted(candidates.get(pixels(source), []), reverse=True)
        before = matches[0][1] if matches else None
        record = {'sample':sample, 'sample_id':sid, 'sha256':digest(source), 'resolution':size,
                  'before':before, 'before_candidates':[m[1] for m in matches],
                  'mapping':'exact EXIF-normalized RGB pixel hash; latest original completed run',
                  'status':'PENDING', 'asset_dir':asset.relative_to(ROOT).as_posix()}
        if before:
            preview = ROOT/'runs'/before/'previews/meshes/oblique.png'
            if preview.exists():
                shutil.copy2(preview, asset/'before.png')
                record['before_preview_source'] = preview.relative_to(ROOT).as_posix()
            record['before_scene_sha256'] = digest(ROOT/'runs'/before/'scene.glb')
        report['samples'].append(record)
    save(path,report)
    return report


def request(url, data=None):
    req = urllib.request.Request(url, data=data, headers={'Content-Type':'application/octet-stream'})
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.load(response)


def run_all(path):
    report = read(path)
    for record in report['samples']:
        if record['status'] != 'PENDING':
            continue
        source = ROOT/record['sample']
        assert digest(source) == record['sha256']
        record['started_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        record['status'] = 'RUNNING'
        save(path,report)
        started = time.monotonic()
        print('START',record['sample'],flush=True)
        try:
            # Save submission intent first; never blindly retry an ambiguous POST.
            result = request(report['base_url']+'/api/runs',source.read_bytes())
            record['after'] = result['run_id']
            save(path,report)
            last = None
            while True:
                state = request(report['base_url']+'/api/runs/'+record['after'])
                if state['stage'] != last:
                    last = state['stage']
                    record['stage'] = last
                    print(record['after'], last, state['message'], flush=True)
                    save(path,report)
                if last == 'failed':
                    raise RuntimeError(state['message'])
                if last == 'done':
                    break
                if time.monotonic()-started > 22200:
                    raise TimeoutError('Backend exceeded maximum job timeout; job identity preserved')
                time.sleep(5)
            run = ROOT/'runs'/record['after']
            meta = read(run/'scene_metadata.json')
            assert pixels(source) == pixels(run/meta['input_image'])
            objects = [o for o in meta['objects'] if o['status']=='generated']
            record.update(objects=len(objects), failed_objects=len(meta['objects'])-len(objects),
                          floor=bool(meta.get('background')), placement=meta.get('placement'),
                          errors=meta.get('errors',[]), worker_implementation=meta.get('implementation_sha256'),
                          remote_job=read(run/'logs/remote_job.json'))
            assert record['floor'] and record['placement'], 'Missing floor or placement correction'
            logdir = path.parent/record['sample_id']
            logdir.mkdir(exist_ok=True)
            with (logdir/'artifact.log').open('w',encoding='utf-8') as log:
                audit = subprocess.run([sys.executable,str(ROOT/'scripts/validate_scene_run.py'),str(run)],stdout=log,stderr=subprocess.STDOUT)
            record['artifact_valid'] = audit.returncode == 0
            shutil.copy2(run/'previews/meshes/oblique.png',ROOT/record['asset_dir']/'after.png')
            env=os.environ.copy();env['PLAYWRIGHT_BROWSERS_PATH']=str(ROOT/'.runtime/browsers')
            with (logdir/'browser.log').open('w',encoding='utf-8') as log:
                browser = subprocess.run(['node',str(ROOT/'web/compare-sample.mjs'),record['after'],str(logdir)],env=env,stdout=log,stderr=subprocess.STDOUT)
            record['viewer_valid'] = browser.returncode == 0
            if (logdir/'viewer.png').exists():
                shutil.copy2(logdir/'viewer.png',ROOT/record['asset_dir']/'after_viewer.png')
            record['status']='PASS' if record['artifact_valid'] and record['viewer_valid'] and not record['errors'] and not record['failed_objects'] else 'PARTIAL'
        except urllib.error.HTTPError as exc:
            record.update(status='FAIL',error=f'HTTP {exc.code}: '+exc.read().decode('utf-8'))
        except Exception as exc:
            record.update(status='FAIL',error=str(exc))
            if record.get('stage') not in {'failed','done'}:
                record['unresolved_submission']=True
                save(path,report)
                raise
        record['duration_seconds']=round(time.monotonic()-started,2)
        save(path,report)
        print('RESULT',record['status'],record.get('error',''),flush=True)
    return report


def verify_before(path):
    """Read-only browser checks; no submission or remote GPU calls."""
    report=read(path)
    env=os.environ.copy();env['PLAYWRIGHT_BROWSERS_PATH']=str(ROOT/'.runtime/browsers')
    for record in report['samples']:
        if not record['before']:
            continue
        output=path.parent/record['sample_id']/'before_browser'
        output.mkdir(parents=True,exist_ok=True)
        with (output/'browser.log').open('w',encoding='utf-8') as log:
            result=subprocess.run(['node',str(ROOT/'web/compare-sample.mjs'),record['before'],str(output),'before'],env=env,stdout=log,stderr=subprocess.STDOUT)
        record['before_viewer_valid']=result.returncode==0
        if (output/'browser.json').exists():record['before_browser']=read(output/'browser.json')
        save(path,report)
        print('BEFORE',record['sample_id'],result.returncode,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--verify-before',action='store_true')
    args=parser.parse_args()
    if not args.manifest.exists():prepare(args.manifest)
    if args.verify_before:verify_before(args.manifest)
    elif not args.prepare_only:run_all(args.manifest)
