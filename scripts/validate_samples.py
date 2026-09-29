"""Sequential, real GPU + browser validation. Start the existing web backend first."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}  # web/index.html accept
EXCLUDED = {'previews', 'screenshots', 'thumbnails', 'results', 'output'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def scan(folder):
    records, excluded = [], []
    for p in sorted(folder.rglob('*'), key=lambda p: p.as_posix().lower()):
        if not p.is_file() or p.suffix.lower() not in EXTENSIONS:
            continue
        parts = p.relative_to(folder).parts
        hidden = any(part.startswith('.') for part in parts)
        hidden |= any(getattr(folder.joinpath(*parts[:i]).stat(), 'st_file_attributes', 0) & 6 for i in range(1, len(parts) + 1))
        generated = any(part.lower() in EXCLUDED for part in parts[:-1]) or bool(re.search(r'(^|[_-])(thumbnail|thumb|screenshot|full_page|viewer)([_-]|\.|$)', p.name, re.I))
        if hidden or generated:
            excluded.append({'file': p.relative_to(ROOT).as_posix(), 'reason': 'hidden/system or generated preview/screenshot'})
            continue
        rec = {'sample': p.relative_to(ROOT).as_posix(), 'sha256': digest(p), 'bytes': p.stat().st_size, 'status': 'pending', 'attempted': False}
        rec['sample_id'] = hashlib.sha256(rec['sample'].encode()).hexdigest()[:16]
        try:
            with Image.open(p) as image:
                rec['resolution'] = list(image.size)
                rec['format'] = image.format
                image.verify()
        except Exception as e:
            rec['input_error'] = str(e)
        records.append(rec)
    return records, excluded


def same_input(source, normalized):
    with Image.open(source) as im:
        expected = ImageOps.exif_transpose(im).convert('RGB')
    with Image.open(normalized) as im:
        actual = im.convert('RGB')
    return expected.size == actual.size and expected.tobytes() == actual.tobytes()


def save_report(folder, report):
    reviews = read(folder / 'visual_review.json', {})
    for rec in report['samples']:
        review = reviews.get(rec.get('run_id'))
        if review and rec['status'] in {'PASS', 'PARTIAL'}:
            rec.setdefault('automated_status', rec['status'])
            rec['visual_review'] = review
            if review['status'] == 'PARTIAL':
                rec['status'] = 'PARTIAL'
            for key in ('viewer_screenshot', 'full_page_screenshot'):
                if key in review:
                    rec[key] = review[key]
    content = json.dumps(report, indent=2, ensure_ascii=False)
    temp = folder / 'index.tmp'
    temp.write_text(content, encoding='utf-8')
    temp.replace(folder / 'index.json')
    lines = ['# Sample validation', '', f"State: {report['state']}", f"HEAD: {report['head']}", '', '| # | Sample | Status | Run ID | Objects | Duration (s) | Screenshot | Local URL |', '|---|---|---|---|---|---|---|---|']
    for i, r in enumerate(report['samples'], 1):
        lines.append(f"| {i} | {r['sample']} | {r['status']} | {r.get('run_id', '—')} | {r.get('scene_object_count', '—')} | {r.get('duration_seconds', '—')} | {r.get('viewer_screenshot', '—')} | {r.get('url', '—')} |")
    lines += ['', '## Failures / warnings', '']
    for r in report['samples']:
        if r.get('error') or r.get('warnings') or r.get('visual_review', {}).get('note'):
            lines += [f"- {r['sample']}: {r.get('error', r.get('warnings'))}; attempted={r['attempted']}; retry={bool(r.get('previous_attempts') or r.get('retry_note'))}"]
            if r.get('visual_review'):
                lines.append(f"  Visual review: {r['visual_review']['note']}")
    lines += ['', '## Screenshots', '']
    for r in report['samples']:
        lines.append(f"- {r['sample']}")
        for key in ('viewer_screenshot', 'full_page_screenshot', 'failure_screenshot'):
            if r.get(key):
                location = Path(r[key]).as_posix()
                lines.append(f"  - {key}: [{location}](<{location}>)")
    (folder / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def validate(rec, folder, resume=None):
    source = ROOT / rec['sample']
    dest = folder / rec['sample_id']
    if dest.exists():
        dest = dest / dt.datetime.now(dt.timezone.utc).strftime('retry-%Y%m%dT%H%M%S%fZ')
    dest.mkdir(parents=True)
    rec['attempted'] = True
    rec['stage'] = 'browser_submission'
    started = time.monotonic()
    if digest(source) != rec['sha256']:
        raise RuntimeError('Input changed after scan')
    if resume:
        if not re.fullmatch(r'[a-f0-9]{32}', resume):
            raise ValueError('Invalid preflight run ID')
        if not same_input(source, ROOT / 'runs' / resume / 'input/source_image.png'):
            raise ValueError('Preflight run input does not match current sample pixels')
    env = os.environ.copy()
    env.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.runtime/browsers'))
    with (dest / 'browser.log').open('w', encoding='utf-8') as log:
        result = subprocess.run(['node', str(ROOT / 'web/validate-sample.mjs'), str(source), str(dest), resume or ''], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    browser = read(dest / 'browser.json', {})
    rec['browser_report'] = str(dest / 'browser.json')
    for key in ('run_id', 'url', 'viewer_screenshot', 'full_page_screenshot', 'failure_screenshot'):
        if key in browser:
            rec[key] = browser[key]
    rec['duration_seconds'] = round(time.monotonic() - started, 2)
    if rec.get('run_id'):
        run = ROOT / 'runs' / rec['run_id']
        meta = read(run / 'scene_metadata.json', {})
        objects = meta.get('objects', [])
        rec.update(detected_candidate_count=len(meta.get('object_extraction', {}).get('candidates', [])), selected_instance_count=len(objects), successful_sam3d_object_count=sum(o['status'] == 'generated' for o in objects), failed_skipped_object_count=sum(o['status'] != 'generated' for o in objects), generation_seconds=meta.get('timing', {}).get('total_seconds'), runpod=read(run / 'logs/runpod_timing.json'), gpu=read(run / 'logs/gpu_measurement.json'), warnings=meta.get('errors', []))
        rec['stage'] = read(run / 'status.json', {}).get('stage')
    if result.returncode or not browser.get('passed'):
        rec['status'] = 'FAIL'
        rec['error'] = browser.get('error', 'Browser process failed; see browser.log')
        # A nonterminal job must never be followed by another submission.
        rec['infrastructure_failure'] = rec.get('stage') not in {'failed', 'done'} and bool(rec.get('run_id'))
        rec['infrastructure_failure'] |= any(s in rec['error'].lower() for s in ['runpod', 'remote generation', 'quota', 'infrastructure:', 'econnrefused', 'http 409'])
        rec['infrastructure_failure'] |= browser.get('submission_uncertain', False) or not browser
        return
    rec['stage'] = 'artifact_validation'
    if not same_input(source, run / 'input/source_image.png'):
        raise ValueError('Normalized input pixels differ from sample')
    assert digest(source) == rec['sha256'], 'Input changed during generation'
    rec['normalized_input_sha256'] = digest(run / 'input/source_image.png')
    integrity = read(run / 'logs/remote_integrity.json', {})
    assert integrity.get('verified') is True, 'Missing verified remote artifact transfer'
    rec['remote_job'] = read(run / 'logs/remote_job.json')
    rec['remote_round_trip_seconds'] = integrity.get('round_trip_seconds')
    rec['worker_implementation_sha256'] = meta.get('implementation_sha256')
    with (dest / 'artifacts.log').open('w', encoding='utf-8') as log:
        audit = subprocess.run([sys.executable, str(ROOT / 'scripts/validate_scene_run.py'), str(run)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    rec['scene_glb'] = str(run / 'scene.glb')
    rec['scene_object_count'] = browser['object_count']
    assert rec['scene_object_count'] == rec['successful_sam3d_object_count'], 'Browser/metadata object count mismatch'
    rec['status'] = 'PARTIAL' if audit.returncode or rec['warnings'] or rec['failed_skipped_object_count'] else 'PASS'
    if audit.returncode:
        rec['warnings'].append('Artifact validation failed; see artifacts.log')
    if rec['scene_object_count'] < 2:
        rec['status'] = 'PARTIAL'
        rec['warnings'].append('Only one reconstructed object; review coverage against input')
    rec['stage'] = 'verified'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scan-only', action='store_true')
    parser.add_argument('--preflight-sample', default=None, help='Relative sample path; default first decodable input within HTTP limits')
    parser.add_argument('--preflight-run', help='Explicit existing preflight ID; normalized pixels are verified before reuse')
    parser.add_argument('--resume-report', type=Path, help='Explicit interrupted index.json; input hashes must still match. Known runs are reopened, never resubmitted.')
    parser.add_argument('--retry-sample', help='With --resume-report, explicitly submit one failed sample again; preserve its previous attempt')
    args = parser.parse_args()
    if args.preflight_run and not args.preflight_sample:
        parser.error('--preflight-run requires --preflight-sample')
    if args.retry_sample and not args.resume_report:
        parser.error('--retry-sample requires --resume-report')
    records, excluded = scan(ROOT / 'samples')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = ROOT / 'runs/sample_validation' / stamp
    report = {'state': 'scanned', 'created_at': stamp, 'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(), 'os': platform.platform(), 'base_url': 'http://127.0.0.1:8082', 'flow': 'browser upload + Generate, status API polling, fresh-context browser restore', 'samples': records, 'excluded': excluded}
    if args.resume_report:
        report = read(args.resume_report.resolve())
        assert {r['sample']: r['sha256'] for r in records} == {r['sample']: r['sha256'] for r in report['samples']}, 'Sample list/content changed; start a new validation'
        records = report['samples']
        folder = args.resume_report.resolve().parent
    folder.mkdir(parents=True, exist_ok=bool(args.resume_report))
    print('Index | File | Resolution | File Size | Status', flush=True)
    for i, r in enumerate(records, 1):
        print(f"{i:02} | {r['sample']} | {'x'.join(map(str, r.get('resolution', [])))} | {r['bytes']/1024:.1f} KiB | {r['status']}", flush=True)
    save_report(folder, report)
    print(f'REPORT {folder}', flush=True)
    if args.scan_only:
        return 0
    eligible = [r for r in records if not r.get('input_error') and r['resolution'][0]*r['resolution'][1] <= 16_000_000 and r['bytes'] <= 25*1024*1024]
    first = next((r for r in records if r['sample'] == args.preflight_sample), None) if args.preflight_sample else next(iter(eligible), None)
    if first is None:
        parser.error('No valid preflight sample')
    report['state'] = 'running'
    save_report(folder, report)
    ordered = [first] + [r for r in records if r is not first]
    for index, rec in enumerate(ordered):
        if args.resume_report and rec['status'] in {'PASS', 'PARTIAL'}:
            assert same_input(ROOT / rec['sample'], ROOT / 'runs' / rec['run_id'] / 'input/source_image.png'), 'Saved input identity mismatch'
            assert Path(rec['viewer_screenshot']).is_file() and Path(rec['full_page_screenshot']).is_file(), 'Saved screenshot missing'
            continue
        retry = args.retry_sample == rec['sample']
        if args.resume_report and rec['status'] == 'FAIL' and rec['attempted'] and not retry:
            continue
        if retry:
            assert rec['status'] == 'FAIL', 'Only failed samples may be explicitly retried'
            rec.setdefault('previous_attempts', []).append({k: v for k, v in rec.items() if k != 'previous_attempts'})
            for key in ('run_id', 'url', 'browser_report', 'error', 'infrastructure_failure'):
                rec.pop(key, None)
        previous_run = rec.get('run_id') if args.resume_report else None
        if args.resume_report and not previous_run and not retry:
            evidence = sorted((folder / rec['sample_id']).rglob('browser.json'), key=lambda p: p.stat().st_mtime, reverse=True)
            if evidence:
                prior = read(evidence[0], {})
                previous_run = prior.get('run_id')
                if not previous_run and prior.get('submission_uncertain'):
                    raise RuntimeError(f"Submission identity uncertain for {rec['sample']}; inspect browser/run logs before resuming. No duplicate job submitted.")
        if args.resume_report:
            rec.pop('infrastructure_failure', None)
            rec.pop('error', None)
        print(f"VALIDATING {rec['sample']}", flush=True)
        try:
            validate(rec, folder, previous_run or (args.preflight_run if index == 0 else None))
        except Exception as exc:
            rec.update(status='FAIL', error=str(exc))
            # Unknown failure before a terminal job state: stop safely.
            rec['infrastructure_failure'] = rec.get('stage') not in {'artifact_validation', 'done', 'failed', 'verified'}
        print(f"{rec['status']} {rec['sample']}: {rec.get('error', '')}", flush=True)
        stop = rec.get('infrastructure_failure') or (index == 0 and rec['status'] == 'FAIL')
        if stop:
            report['state'] = 'blocked'
            for pending in ordered[index+1:]:
                if pending.get('attempted'):
                    continue  # Preserve completed results when a resumed batch stops.
                pending.update(status='FAIL', attempted=False, stage='blocked_before_submission', error='Not executed: preflight/infrastructure failure. No inference or viewer success claimed.')
        save_report(folder, report)
        if stop:
            break
    else:
        report['state'] = 'finished'
    save_report(folder, report)
    return 0 if report['state'] == 'finished' and all(r['status'] == 'PASS' for r in records) else 1


if __name__ == '__main__':
    raise SystemExit(main())
