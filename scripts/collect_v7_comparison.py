"""Collect completed approved comparison jobs without submitting GPU work."""
import argparse
import time
from pathlib import Path
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_transfer import ArtifactStore, unpack_run
from evaluate_annotated_run import evaluate


def collect(root, only=None):
    store=ArtifactStore();manifest=read(root/'evaluation-manifest.json')
    for job in read(root/'jobs.json'):
        if only and job['run_id']!=only:continue
        rid=job['run_id'];report_path=root/(rid+'-verified.json')
        if report_path.exists():continue
        path=root/(rid+'-result.json')
        if not path.exists():continue
        result=read(path)
        if result['status']!='COMPLETED':continue
        out=result['output'];archive=root/(rid+'-result.zip')
        if not archive.exists() or sha(archive)!=out['archive_sha256']:
            store.download(rid,archive)
        assert sha(archive)==out['archive_sha256']
        run=root/'live'/rid;run.mkdir(parents=True,exist_ok=True);unpack_run(archive,run)
        meta=read(run/'scene_metadata.json')
        assert meta['run_id']==rid and out['run_id']==rid
        assert meta['deployment']['application_sha256']==job['release']
        assert sha(run/'input/source_image.png')==meta['input_sha256']
        assert sha(run/'input/source_image.png')==sha(root/'inputs'/rid/'input/source_image.png')
        if out['success']:
            assert meta['placement']['version']==job['version']
            assert sha(run/'scene.glb')==out['scene_sha256']
            if meta.get('pointmap'):assert sha(run/meta['pointmap']['asset'])==meta['pointmap']['sha256']
            write(root/(rid+'-annotations.json'),evaluate(manifest,job['sample'],run))
        report=dict(run_id=rid,sample=job['sample'],version=job['version'],success=out['success'],
            archive_sha256=out['archive_sha256'],scene_sha256=out.get('scene_sha256'),integrity=True,
            generated=sum(o['status']=='generated' for o in meta['objects']),
            structure=meta.get('structure'),contacts=meta.get('placement',{}).get('contacts'),errors=meta['errors'])
        write(report_path,report)
        print({k:report[k] for k in ('run_id','sample','version','success','generated','integrity')},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('.runtime/v7-gpu-comparison'))
    p.add_argument('--run-id');p.add_argument('--watch',action='store_true')
    a=p.parse_args()
    while True:
        collect(a.root,a.run_id)
        if not a.watch or (a.root/'rollback-result.json').exists():break
        time.sleep(20)
