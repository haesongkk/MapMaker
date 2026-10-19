"""Read-only development comparison; visual quality remains a separate gate."""
from pathlib import Path
from mapmaker.scene_run import read, write


def optional(path):
    return read(path) if path.exists() else {}


def summarize(version=8, extra_root=None):
    roots = [Path('.runtime/v7-gpu-comparison'), Path('.runtime/v8-gpu-comparison/development')]
    if version != 8:
        roots.append(Path(f'.runtime/v{version}-gpu-comparison/development'))
    if extra_root is not None:
        roots.append(Path(extra_root))
    rows = []
    for root in roots:
        for job in optional(root/'jobs.json') or []:
            rid = job['run_id']
            result = optional(root/(rid+'-result.json'))
            annotations = optional(root/(rid+'-annotations.json'))
            integrity = optional(root/(rid+'-verified.json'))
            checks = optional(root/'live'/rid/'comparison-checks.json')
            rows.append(dict(sample=job['sample'], version=job['version'], run_id=rid,
                status=result.get('status', job['status']), success=result.get('output', {}).get('success'),
                generated=integrity.get('generated'), matched=annotations.get('matched'),
                annotated=annotations.get('annotated'), small_matched=annotations.get('small_matched'),
                small_annotated=annotations.get('small_annotated'),
                contacts=(len((integrity.get('contacts') or {}).get('changes', [])) if integrity else None),
                artifact_passed=checks.get('artifact', {}).get('passed'),
                browser_passed=checks.get('browser', {}).get('passed'),
                execution_seconds=result.get('executionTime', 0)/1000,
                platform_retries=result.get('retries', 0)))
    rows.sort(key=lambda row: (row['sample'], row['version']))
    report = dict(scope='Consumed development inputs; selected-box correspondence is not full recall or 3D quality',
        jobs=rows, quality_passed=None, visual_review_required=True,
        rollback=optional(roots[-1]/'rollback-result.json'))
    write(roots[-1]/'comparison-summary.json', report)
    for row in rows:
        print({k: row[k] for k in ('sample','version','status','matched','small_matched','contacts')})


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=int, default=8)
    parser.add_argument("--extra-root", type=Path)
    args = parser.parse_args()
    summarize(args.version, args.extra_root)
