"""Detect incomplete wheel installations by checking recorded files without importing models."""
from pathlib import Path
import csv
import json
import os

ROOT = Path(__file__).resolve().parents[1]
venv = ROOT / '.venv-sam3d'
site = venv / 'lib/python3.11/site-packages'
print('Indexing installed files', flush=True)
existing = set()
for directory, dirs, files in os.walk(venv):
    existing.update(os.path.join(directory, name) for name in files)
print('Indexed', len(existing), 'files', flush=True)
rows = []
for dist in site.glob('*.dist-info'):
    record = dist / 'RECORD'
    if not record.exists():
        rows.append({'distribution': dist.name, 'missing_record': True, 'missing': []})
        continue
    with record.open(newline='') as f:
        expected = [row[0] for row in csv.reader(f) if row]
    missing = [rel for rel in expected if os.path.normpath(os.path.join(site, rel)) not in existing]
    if missing:
        metadata = (dist / 'METADATA').read_text()
        name = next(line[6:] for line in metadata.splitlines() if line.startswith('Name: '))
        version = next(line[9:] for line in metadata.splitlines() if line.startswith('Version: '))
        rows.append({'distribution': dist.name, 'name': name, 'version': version, 'missing': missing})
report = {'files_indexed': len(existing), 'incomplete_distributions': rows, 'passed': not rows}
(ROOT / '.runtime/sam3d-recovery/file-audit.json').write_text(json.dumps(report, indent=2))
print(json.dumps({'passed': not rows, 'incomplete': [{'name': r.get('name', r['distribution']), 'missing_count': len(r['missing'])} for r in rows]}, indent=2), flush=True)

if rows:
    raise SystemExit(1)
