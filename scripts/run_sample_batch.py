"""Bounded sample validation using the unchanged production pipeline functions.

Keeps up to three production runs in flight so local download/render work does
not cause the single existing GPU worker to shut down between every sample.
Existing run IDs are observed, never resubmitted. Viewer audits follow inference.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import os
from pathlib import Path
import sys
import threading
import time

from compare_all_samples import ROOT, digest, read, save, run_all

sys.path.insert(0, str(ROOT))
from mapmaker.scene_pipeline import create_run, configured_pipeline


def run_batch(path):
    if os.environ.get('MAPMAKER_BACKEND') != 'runpod':
        raise ValueError('Use the existing RunPod production configuration')
    report = read(path)
    lock = threading.Lock()

    def update(row, **fields):
        with lock:
            row.update(fields)
            save(path, report)

    def generate(row):
        started = time.monotonic()
        try:
            source = ROOT/row['sample']
            assert digest(source) == row['sha256']
            if row.get('after'):
                run = ROOT/'runs'/row['after']
                # This run belongs to the still-running local HTTP server.
                while True:
                    state = read(run/'status.json')
                    if state['stage'] == 'failed':
                        raise RuntimeError(state['message'])
                    if state['stage'] == 'done':
                        break
                    if time.monotonic()-started > 22200:
                        raise TimeoutError('Existing run still active; not resubmitted')
                    time.sleep(5)
            else:
                run = create_run(source.read_bytes())
                update(row, after=run.name, status='RUNNING', attempted=True,
                       started_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                       execution_path='production create_run + configured_pipeline().run')
                print('SUBMITTED', row['sample_id'], run.name, flush=True)
                # One instance per run; the existing endpoint remains max=1.
                configured_pipeline().run(run)
            meta = read(run/'scene_metadata.json')
            assert meta.get('placement') and meta.get('background'), 'Production finalization missing'
            update(row, status='GENERATED', stage='done',
                   generation_seconds=round(time.monotonic()-started, 2))
            print('GENERATED', row['sample_id'], run.name, flush=True)
        except Exception as exc:
            update(row, status='FAIL', error=str(exc))
            print('FAILED', row['sample_id'], str(exc), flush=True)

    targets = [row for row in report['samples'] if row['status'] in {'PENDING','RUNNING'}]
    with ThreadPoolExecutor(max_workers=3) as executor:
        list(executor.map(generate, targets))
    for row in report['samples']:
        if row['status'] == 'GENERATED':
            # run_all observes existing IDs and only validates their artifacts.
            row['status'] = 'PENDING'
    save(path, report)
    run_all(path)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    run_batch(parser.parse_args().manifest)
