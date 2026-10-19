"""Summarize the immutable approved experiment without inferring visual quality."""
import json
from collections import Counter
from pathlib import Path

root = Path('.runtime/v7-gpu-comparison')
def read(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

rows = []
for job in read(root / 'jobs.json'):
    rid = job['run_id']
    result = read(root / (rid + '-result.json')) or {}
    integrity = read(root / (rid + '-verified.json')) or {}
    annotations = read(root / (rid + '-annotations.json')) or {}
    checks = read(root / 'live' / rid / 'comparison-checks.json')
    rows.append(dict(version=job['version'], sample=job['sample'], run_id=rid,
        status=result.get('status', job['status']), success=result.get('output', {}).get('success'),
        release=job['release'], execution_seconds=result.get('executionTime', 0)/1000,
        platform_retries=result.get('retries', 0),
        integrity=integrity.get('integrity'), generated=integrity.get('generated'),
        annotated=annotations.get('annotated'), matched=annotations.get('matched'),
        small_annotated=annotations.get('small_annotated'), small_matched=annotations.get('small_matched'),
        contact_changes=len((integrity.get('contacts') or {}).get('changes', [])),
        structure_surfaces=dict(Counter(s['kind'] for s in (integrity.get('structure') or {}).get('surfaces', []))),
        checks=checks))
report = dict(scope='Selected coarse mask-box correspondence is not full recall or 3D accuracy.',
    approved_jobs=9, submitted_jobs=len(rows), jobs=rows,
    rollback=read(root / 'rollback-result.json'), visual_review=read(root / 'visual-review.json'),
    deployment_decision=read(root / 'deployment-decision.json'))
(root / 'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
for row in rows:
    print({k: row[k] for k in ('version','sample','status','generated','matched','annotated','small_matched')})
