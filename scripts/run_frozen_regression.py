"""Run local regression from a private source snapshot, with absolute input paths."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    sources = [p.resolve(strict=True) for p in args.sources]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source_root = Path(__file__).resolve().parents[1]
    frozen = output/'source'
    for package in ('mapmaker', 'scripts'):
        shutil.copytree(source_root/package, frozen/package,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    hashes = {str(p.relative_to(frozen)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in frozen.rglob('*.py')}
    command = [sys.executable, '-m', 'scripts.replay_inference_regression',
               *map(str, sources), '--output', str(output/'results')]
    manifest = dict(command=command, cwd=str(frozen), source_sha256=hashes,
                    fresh_gpu_inference=False)
    (output/'snapshot.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    with (output/'process.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=frozen, stdout=log, stderr=subprocess.STDOUT)
        (output/'process.json').write_text(json.dumps(dict(pid=process.pid,
            status='running', command=command), indent=2), encoding='utf-8')
        code = process.wait()
    (output/'process.json').write_text(json.dumps(dict(pid=process.pid,
        status='completed' if code == 0 else 'failed', exit_code=code), indent=2), encoding='utf-8')
    raise SystemExit(code)


if __name__ == '__main__':
    main()
