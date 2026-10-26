"""Five-image vision movable experiment, with resumable submission and collection."""
import sys, uuid, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mapmaker.scene_run import ROOT, read, write, sha
from mapmaker.qwen_tags import MOVABLE_PROMPT, MODEL, REVISION, parse_tags
from mapmaker.scene_transfer import ArtifactStore, pack_run, materialize
from mapmaker.remote_settings import load_settings
from mapmaker.scene_remote import RunPodClient

WORK = ROOT / '.runtime/qwen-vision-movable'
NAMES = ('house', 'office', 'sample-01', 'sample-02', 'sample-04')
PROMPT_POLICY = 'movable_v1'
FILTER_BATCH = None

def prepare():
    from mapmaker.scene_pipeline import create_run
    WORK.mkdir(exist_ok=True)
    if (WORK/'comparison.json').exists():
        raise ValueError('Experiment already prepared')
    old = read(ROOT/'.runtime/minimal-baseline/comparison.json')['samples']
    state = dict(prompt=MOVABLE_PROMPT, samples={})
    for name in NAMES:
        source = ROOT/old[name]['path']; meta = read(source/'scene_metadata.json')
        run = create_run((source/meta['input_image']).read_bytes(), WORK/'runs'/uuid.uuid4().hex, mode=1)
        m = read(run/'scene_metadata.json')
        assert m['input_sha256'] == meta['input_sha256']
        m['execution'].update(tagger='qwen2.5-vl-7b', qwen_prompt_policy=PROMPT_POLICY)
        if name == 'house' and FILTER_BATCH is not None:
            m['execution']['saved_tag_filter_batch'] = FILTER_BATCH
        write(run/'scene_metadata.json', m)
        archive = WORK/f'{name}-input.zip'; pack_run(run, archive, input_only=True)
        state['samples'][name] = dict(path=run.as_posix(), status='prepared',
            source_input_sha256=meta['input_sha256'], payload=dict(protocol=2,
            tagger='qwen2.5-vl-7b', run_id=run.name, input_sha256=sha(archive)))
    write(WORK/'comparison.json', state)
    with zipfile.ZipFile(WORK/'application.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for dirname in ('mapmaker', 'scripts', 'configs'):
            for p in sorted((ROOT/dirname).rglob('*')):
                if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.whl'):
                    z.write(p, p.relative_to(ROOT).as_posix())
    p = WORK/'application.zip'; digest = sha(p)
    write(WORK/'release.json', dict(sha256=digest, key=f'mapmaker-releases/{digest}/application.zip', size=p.stat().st_size))
    print(read(WORK/'release.json'))

def upload():
    load_settings(); s = ArtifactStore(); r = read(WORK/'release.json')
    s.client.upload_file(str(WORK/'application.zip'), s.bucket, r['key'])
    assert s.client.head_object(Bucket=s.bucket, Key=r['key'])['ContentLength'] == r['size']
    for name, record in read(WORK/'comparison.json')['samples'].items():
        s.upload(record['payload']['run_id'], WORK/f'{name}-input.zip')
        print('uploaded', name, flush=True)

def submit(names):
    state = read(WORK/'comparison.json'); client = RunPodClient(state['endpoint_id'])
    for name in names:
        r = state['samples'][name]
        if r['status'] != 'prepared':
            print(name, r['status'], 'not resubmitted'); continue
        r['status'] = 'submitting'; write(WORK/'comparison.json', state)
        result = client.submit(r['payload'], 21600)
        r.update(status='submitted', job_id=result['id'])
        write(WORK/'comparison.json', state); print(name, result, flush=True)

def collect():
    load_settings(); s = ArtifactStore(); state = read(WORK/'comparison.json')
    release = read(WORK/'release.json')['sha256']
    for name, r in state['samples'].items():
        if r['status'] != 'submitted':
            print(name, r['status'], flush=True); continue
        rid = r['payload']['run_id']; out = s.get_json(rid, 'result-manifest.json')
        if not out:
            print(name, s.progress(rid), flush=True); continue
        size = out['archive_bytes']; assert out['run_id'] == rid and 0 < size <= 32*1024**3
        archive = WORK/f'{name}-result.zip'
        if not archive.exists() or archive.stat().st_size != size or sha(archive) != out['archive_sha256']:
            s.download_object(s.bucket, s.key(rid, 'result.zip'), archive, limit=size)
        import mapmaker.scene_transfer as transfer
        transfer.MAX_ARCHIVE_BYTES = max(transfer.MAX_ARCHIVE_BYTES, size)
        def verify(staged):
            m = read(staged/'scene_metadata.json'); e = read(staged/'logs/qwen_response.json')
            assert m['input_sha256'] == r['source_input_sha256'] == e['input_sha256']
            assert m['deployment']['application_sha256'] == release
            assert e['model'] == MODEL and e['revision'] == REVISION and e['prompt'] == MOVABLE_PROMPT
            assert m['object_extraction']['candidates'] == parse_tags(e['raw_response'])
            if out['success']:
                assert m['execution']['completed_mode'] == 1
                assert m['execution']['baseline_policy'] == 'default_model_outputs_unfiltered_v1'
                assert all(o['status'] in ('generated', 'failed') for o in m['objects'])
        folder = Path(r['path']); materialize(archive, folder, out, finalize=verify)
        r['status'] = 'complete' if out['success'] else 'failed'
        if out['success']: r['scene_sha256'] = sha(folder/'scene.glb')
        write(WORK/'comparison.json', state)
        print(name, r['status'], flush=True)

if __name__ == '__main__':
    command = sys.argv[1]
    if command == 'prepare': prepare()
    elif command == 'upload': upload()
    elif command == 'submit': submit(sys.argv[2:])
    elif command == 'collect': collect()
    else: raise ValueError(command)
