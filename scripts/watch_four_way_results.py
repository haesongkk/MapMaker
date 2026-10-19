"""Process each collected expanded scene once; refresh the local report."""
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapmaker.scene_run import read,write,now

ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'.runtime/four-way-comparison'
python=ROOT/'.venv/Scripts/python.exe'
ledger=folder/'postprocess.json'
state=read(ledger) if ledger.exists() else {}
previous=None
while not (folder/'STOP').exists():
    jobs=read(folder/'jobs.json')
    for job in jobs:
        if job['profile']!='expanded' or not job.get('collected') or job['sample'] in state:continue
        sample=job['sample'];state[sample]=dict(status='running',started_at=now());write(ledger,state)
        env=dict(os.environ,PYTHONUTF8='1',PYTHONPATH=str(ROOT/'.runtime/manifold-diagnostic-lib')+os.pathsep+str(ROOT))
        log=folder/(sample+'-postprocess.log')
        with log.open('w',encoding='utf-8') as output:
            completed=subprocess.run([str(python),'scripts/derive_comparison_stages.py',sample],cwd=ROOT,env=env,stdout=output,stderr=subprocess.STDOUT)
        state[sample].update(status='complete' if completed.returncode==0 else 'failed',returncode=completed.returncode,finished_at=now())
        write(ledger,state)
        print(sample,state[sample]['status'],flush=True)
    current=(sum(bool(j.get('collected')) for j in jobs),len(state),sum(x['status']=='complete' for x in state.values()))
    if current!=previous:
        subprocess.run([str(python),'scripts/build_four_way_report.py'],cwd=ROOT,check=True)
        previous=current
    rollback=folder/'rollback-result.json'
    if rollback.exists():
        result=read(rollback)
        if result.get('failure') or (all(j.get('collected') for j in jobs) and len(state)==10):break
    time.sleep(20)
print('Postprocessing watcher ended; inspect per-photo results. Screenshots still require visual verification.',flush=True)
