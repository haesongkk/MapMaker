"""Collect committed Qwen results once, without polling or resubmitting jobs."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_transfer import ArtifactStore, materialize
from mapmaker.remote_settings import load_settings
from mapmaker.qwen_tags import MODEL, REVISION, parse_tags
from scripts.compare_qwen_baseline import report, ROOT, POLICY


def collect(v2=False):
    load_settings();store=ArtifactStore();work=ROOT/('.runtime/qwen-baseline-v2' if v2 else '.runtime/qwen-baseline')
    state=read(work/'comparison.json');release=read(work/'release.json')['sha256']
    for name,record in state['samples'].items():
        if record['status']=='complete':continue
        folder=Path(record['path']);rid=record['payload']['run_id']
        output=store.get_json(rid,'result-manifest.json')
        if not output:
            print(name,store.progress(rid),flush=True);continue
        size=output['archive_bytes']
        if output.get('run_id')!=rid or not isinstance(size,int) or not 0<size<=32*1024**3:
            raise ValueError('Invalid result manifest')
        archive=work/f'{name}-result.zip'
        if not archive.exists() or archive.stat().st_size!=size or sha(archive)!=output['archive_sha256']:
            store.download_object(store.bucket,store.key(rid,'result.zip'),archive,limit=size)
        if archive.stat().st_size!=size:raise ValueError('Truncated result archive')
        import mapmaker.scene_transfer as transfer
        transfer.MAX_ARCHIVE_BYTES=max(transfer.MAX_ARCHIVE_BYTES,size)
        def verify(staged):
            meta=read(staged/'scene_metadata.json');evidence=read(staged/'logs/qwen_response.json')
            assert meta['execution']['completed_mode']==1
            assert meta['execution']['baseline_policy']==POLICY
            assert meta['deployment']['application_sha256']==release
            assert evidence['model']==MODEL and evidence['revision']==REVISION
            if state.get('prompt'):
                assert evidence['prompt']==state['prompt'], 'Worker ran the wrong prompt version'
            assert meta['object_extraction']['candidates']==parse_tags(evidence['raw_response'])
            assert all(o['status'] in ('generated','failed') for o in meta['objects'])
        materialize(archive,folder,output,finalize=verify)
        record['status']='complete' if output['success'] else 'failed'
        if output['success']:record['scene_sha256']=sha(folder/'scene.glb')
        write(work/'comparison.json',state);print(name,record['status'],flush=True)
    report(v2=v2)


if __name__=='__main__':collect(v2='--v2' in sys.argv)
