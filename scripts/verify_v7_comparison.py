"""Verify collected comparison artifacts; never submit inference or alter outputs."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def verify(root):
    for record in root.glob('*-verified.json'):
        item = json.loads(record.read_text(encoding='utf-8'))
        if not item['success']:
            continue
        run = root / 'live' / item['run_id']
        report = run / 'comparison-checks.json'
        if report.exists():
            continue
        checks = {}
        commands = {
            'artifact': [sys.executable, 'scripts/validate_scene_run.py', str(run)],
            'browser': ['node', 'scripts/verify_room_viewer.mjs', str(run)],
        }
        for name, command in commands.items():
            try:
                result = subprocess.run(command, capture_output=True, timeout=600)
                (run / f'{name}-check.log').write_bytes(result.stdout + result.stderr)
                checks[name] = {'passed': result.returncode == 0, 'returncode': result.returncode}
            except subprocess.TimeoutExpired:
                checks[name] = {'passed': False, 'reason': 'verification_timeout'}
        report.write_text(json.dumps(checks, indent=2), encoding='utf-8')
        print(json.dumps({'run_id': item['run_id'], 'sample': item['sample'],
                          'version': item['version'], 'checks': checks}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.runtime/v7-gpu-comparison'))
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    while True:
        verify(args.root)
        if not args.watch:
            break
        # Collection may lag behind restoration, so wait for all successful archives.
        if (args.root / 'rollback-result.json').exists():
            jobs = json.loads((args.root / 'jobs.json').read_text())
            successful = []
            for job in jobs:
                path = args.root / (job['run_id'] + '-result.json')
                result = json.loads(path.read_text()) if path.exists() else {}
                if result.get('output', {}).get('success'):
                    successful.append(job['run_id'])
            if all((args.root / 'live' / rid / 'comparison-checks.json').exists() for rid in successful):
                break
        time.sleep(20)
