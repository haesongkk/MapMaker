"""Verify the restored distributions against the last successful runtime record."""
from importlib import metadata
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
expected = ROOT / 'configs/sam3d/successful-runtime-freeze.txt'
rows = []
for line in expected.read_text().splitlines():
    if not line or line.startswith('-e '):
        continue
    if line.startswith('nvidia-pyindex=='):
        rows.append({'requirement': line, 'status': 'intentionally_excluded',
                     'reason': 'Index configuration installer edits global/user pip files; explicit index URLs used instead.'})
        continue
    name = re.split(r'==| @ ', line)[0]
    try:
        dist = metadata.distribution(name)
        row = {'requirement': line, 'installed_version': dist.version}
        if '==' in line:
            row['match'] = dist.version == line.split('==', 1)[1]
        else:
            origin = json.loads(dist.read_text('direct_url.json') or '{}')
            commit = line.rsplit('@', 1)[1]
            row['origin'] = origin
            row['match'] = origin.get('vcs_info', {}).get('commit_id') == commit
        rows.append(row)
    except metadata.PackageNotFoundError:
        rows.append({'requirement': line, 'match': False, 'error': 'not installed'})
report = {'python': sys.version, 'executable': sys.executable,
          'all_expected_versions_match': all(r.get('match', True) for r in rows),
          'packages': rows}
path = ROOT / '.runtime/sam3d-recovery/version-audit.json'
path.write_text(json.dumps(report, indent=2))
print('Version audit:', report['all_expected_versions_match'], 'records:', len(rows))
for row in rows:
    if not row.get('match', True):
        print(row)
if not report['all_expected_versions_match']:
    raise SystemExit(1)
