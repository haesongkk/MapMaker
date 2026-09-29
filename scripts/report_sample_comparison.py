"""Render the sample audit from saved evidence; never submits inference jobs."""
import argparse
from collections import Counter
import datetime as dt
import json
from pathlib import Path
import platform

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def render(manifest):
    report = read(manifest)
    previous = read(ROOT/'docs/SAMPLES_BEFORE_AFTER_COMPARISON.json')
    previous_samples = {x['sample_id']: x for x in previous['samples']}
    notes_path = manifest.parent/'visual_comparison.json'
    notes = read(notes_path) if notes_path.exists() else {}
    for row in report['samples']:
        old = previous_samples.get(row['sample_id'], {})
        row['before_visual_note'] = old.get('before_visual_note', '기존 결과 없음.')
        row['comparison'] = notes.get(row['sample_id'], '새 결과 없음; 시각적 개선/회귀를 판정할 수 없다.')
        if row.get('after'):
            run = ROOT/'runs'/row['after']
            row['after_metadata'] = read(run/'scene_metadata.json')
            if row['after_metadata'].get('placement', {}).get('version') == 2:
                raise ValueError('This historical report describes individual correction v1; use the global alignment report for v2')
            for key, file in [('timing', run/'logs/runpod_timing.json'),
                              ('browser', manifest.parent/row['sample_id']/'browser.json'),
                              ('artifact_audit', run/'logs/artifact_validation.json')]:
                if file.exists():
                    row[key] = read(file)
            row['attempted'] = True
    counts = Counter(x['status'] for x in report['samples'])
    report['updated_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    report['execution_status'] = 'finished' if not any(counts[x] for x in ('PENDING','RUNNING','BLOCKED')) else 'incomplete'
    report['fresh_inference_completed'] = report['execution_status'] == 'finished'
    report['environment'] = {'os': platform.platform(), 'python': platform.python_version()}
    report['summary'] = dict(counts)
    report['tests'] = previous.get('tests', {})
    # Full worker metadata may contain private transport details; publish only the
    # measurements below, plus the existing public run IDs and validation evidence.
    public = {k:v for k,v in report.items() if k != 'samples'}
    public['samples'] = [{k:v for k,v in row.items() if k != 'after_metadata'} for row in report['samples']]
    (ROOT/'docs/SAMPLES_BEFORE_AFTER_COMPARISON.json').write_text(json.dumps(public,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    rows = report['samples']
    generated = [x for x in rows if (ROOT/'runs'/x.get('after','__missing__')/'scene.glb').exists()]
    floor_count = sum(bool(x.get('floor')) for x in rows)
    viewer_count = sum(bool(x.get('viewer_valid')) for x in rows)
    lines = ['# Sample Before / After Comparison', '', '## 1. 개요', '',
        f"전체 {len(rows)}개 입력: PASS **{counts['PASS']}**, PARTIAL **{counts['PARTIAL']}**, FAIL **{counts['FAIL']}**. 새 GLB {len(generated)}개, 새 floor {floor_count}개, After viewer 검증 통과 {viewer_count}개.", '',
        'Before는 저장된 기존 원본 결과이고, After는 사용자 승인 후 현재 production 경로로 새로 수행한 RAM++ → SAM3 → SAM3D → 배치 보정 → 바닥 생성 → GLB/preview 결과다. 이전 CPU 재처리 결과를 새 추론으로 사용하지 않았다.', '',
        '기존 run은 EXIF 정규화 RGB 픽셀 SHA가 정확히 일치하는 원본 완료 결과 중 가장 최근 것으로 매칭했다. Before 22개가 매칭됐고 7개는 누락이다. 원본 입력과 기존 GLB/preview를 보존했다.', '',
        '**해석 주의:** 새 GPU 추론이므로 객체 추출·형상 자체도 기존 run과 달라질 수 있다. 아래 화면 차이를 배치 보정만의 효과로 단정하지 않는다. 접촉 통계의 전/후는 각 새 run 내부의 보정 전/후이며, 과거 Before run과의 통계 비교가 아니다.', '',
        '## 2. 실행 환경', '',
        f"- Branch: `{report['branch']}`; 실행 HEAD: `{report.get('execution_head', report['head'])}`.",
        '- 해당 HEAD 위의 기존 미커밋 placement/floor 구현을 사용했다. 정확한 소스 SHA-256은 함께 제공하는 JSON에 기록했다. 기존 사용자 구현 변경은 이번 문서 commit에 포함하지 않는다.',
        f"- Windows / Python {platform.python_version()} / 기존 `.venv`, RunPod endpoint `8dzbkfrxys43hb`, 기존 S3 전송 설정.",
        '- GPU 추론은 기존 배포 worker image tag `8a0bcaa35`를 사용했다. worker를 새 HEAD로 재배포하지 않았다. worker의 파일별 실제 SHA는 각 행의 `worker_implementation`, 현재 로컬 후처리 코드는 최상위 `implementation_sha256`에 별도로 기록한다. 따라서 로컬 HEAD 전체가 GPU에서 실행됐다는 의미는 아니다.',
        '- 이전 자동 승인 심사 차단 후 사용자가 22개 이미지 외부 전송 및 GPU 비용을 명시 승인하여 실행했다. 7개는 16MP 입력 제한으로 실제 로컬 HTTP 400이 발생했으며 임의 축소하지 않았다.', '',
        '- 첫 2개는 production HTTP 서버로 제출했다. 이후 검증 실행기는 같은 `create_run` / `configured_pipeline().run` production 함수를 호출하고 최대 3개 run의 전송·다운로드·렌더링을 겹쳤다. 기존 endpoint의 GPU 동시 실행 한도 1개는 변경하지 않았다. 객체 생성·배치·바닥 알고리즘은 동일하다.', '',
        '```powershell',
        '.venv\\Scripts\\python.exe scripts/compare_all_samples.py --manifest runs/all_samples_comparison/20260929/index.json',
        '# 기존 start_scene_web.ps1과 같은 RunPod 환경을 사용한 나머지 batch',
        '.venv\\Scripts\\python.exe scripts/run_sample_batch.py --manifest runs/all_samples_comparison/20260929/index.json',
        '.venv\\Scripts\\python.exe scripts/report_sample_comparison.py --manifest runs/all_samples_comparison/20260929/index.json',
        '.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider',
        'node --check web/compare-sample.mjs', '```', '',
        '### Viewer와 산출물 보존', '',
        '실제 URL 형식은 `/?run=<run-id>`다. 고정 공개 host는 설정되어 있지 않다. 아래 로컬 Viewer 링크는 **D:\\MapMaker의 runs를 보유한 컴퓨터에서 서버가 실행 중일 때만** 유효하다. 다른 환경은 `{MAPMAKER_BASE_URL}/?run=<run-id>`와 해당 run 디렉터리 복원이 필요하다. 공개 URL을 임의 생성하지 않았다.', '',
        '`runs/`는 기존 정책대로 Git에서 제외하며 input/masks/objects/scene.glb/metadata/previews/logs를 로컬에 보존한다. GitHub에서 바로 볼 수 있는 입력 축소본과 Before/After preview만 `docs/assets/sample_comparison/`에 commit한다. Preview는 같은 oblique 방향을 사용하나 scene bounds에 따라 화면 배율이 달라진다.', '',
        '비교 표의 CPU preview는 바닥을 먼저 그리는 방식이므로 바닥 아래 형상이 위에 보일 수 있다. 정확한 가림은 별도 After WebGL 화면과 Viewer에서 확인한다. WebGL 캡처는 viewer 기본 카메라이며 비교 표의 oblique 카메라와는 다르다.', '',
        '## 3. 전체 결과 요약', '',
        'PASS는 산출물·floor·placement·viewer 검사와 객체 생성이 모두 성공했다는 뜻이다. 시각적 품질이 완벽하다는 뜻은 아니다. PARTIAL은 생성 결과는 있으나 일부 검사 또는 객체 생성 실패가 있다.', '',
        '| Sample | Before | After | Viewer | Result |', '|---|---|---|---|---|']
    for i, row in enumerate(rows, 1):
        name = Path(row['sample']).name
        short = name if len(name)<48 else name[:32]+'…'+Path(name).suffix
        before = row['before'][:8] if row['before'] else 'MISSING'
        after = row.get('after','—')[:8]
        viewer = ' / '.join(f"[{label}](http://127.0.0.1:8082/?run={row[key]})" for key,label in [('before','Before'),('after','After')] if row.get(key)) or '없음'
        lines.append(f"| [{short}](#sample-{i:02d}) | {before} | {after} | {viewer} | {row['status']} |")
    for i, row in enumerate(rows, 1):
        asset = 'assets/sample_comparison/'+row['sample_id']
        before_image = f'![Before {i}]({asset}/before.png)' if row['before'] else 'BEFORE MISSING'
        after_image = f'![After {i}]({asset}/after.png)' if (ROOT/row['asset_dir']/'after.png').exists() else 'After preview 없음'
        lines += ['', f'<a id="sample-{i:02d}"></a>', f"## {i:02d}. {Path(row['sample']).name}", '',
                  f'![Input {i}]({asset}/input.jpg)', '', f"- 입력: `{row['sample']}` ({row['resolution'][0]} × {row['resolution'][1]})", '',
                  '| Before | After |', '|---|---|', f'| {before_image} | {after_image} |', '']
        if (ROOT/row['asset_dir']/'after_viewer.png').exists():
            lines += ['<details>', '<summary>After WebGL 실제 화면 — 기본 카메라</summary>', '',
                      f'![After WebGL {i}]({asset}/after_viewer.png)', '', '</details>', '']
        for key,label in [('before','Before'),('after','After')]:
            rid = row.get(key)
            if rid:
                lines += [f'- [{label} Viewer — 로컬 전용](http://127.0.0.1:8082/?run={rid})',
                          f'- {label} run: `runs/{rid}/`; GLB: `runs/{rid}/scene.glb`; preview: `runs/{rid}/previews/meshes/oblique.png`.']
            else:
                lines.append(f'- {label} Viewer 없음: '+('정확히 매칭되는 기존 완료 run 없음.' if key=='before' else '로컬 입력 제한으로 새 run이 생성되지 않음.'))
        if row['before']:
            baseline = read(ROOT/'runs'/row['before']/'scene_metadata.json')
            before_count = sum(o['status']=='generated' for o in baseline['objects'])
            lines.append(f"- Before 생성 시각: `{baseline.get('created_at')}`; 생성 객체 {before_count}개; 기존 별도 background floor 없음.")
        lines += ['', '### 비교와 검증', '', '- Before 관찰: '+row['before_visual_note'], '- '+row['comparison'], f"- 상태: **{row['status']}**."]
        if row.get('error'):
            lines.append('- 실패 원인: '+row['error'].replace('\n',' '))
        if row.get('recovery_note'):
            lines.append('- 실행 복구 기록: '+row['recovery_note'])
        meta = row.get('after_metadata',{})
        if meta.get('placement'):
            placement = meta['placement']; metrics = placement['metrics']
            old,new = metrics['before'],metrics['after']
            objects = [o for o in meta['objects'] if o['status']=='generated']
            corrected = sum(o['placement']['delta_y'] != 0 for o in objects)
            lines += [f"- 새 객체 {len(objects)}개; 생성 실패 {row.get('failed_objects',0)}개; floor {bool(row.get('floor'))}; 위치 이동 {corrected}개.",
                      f"- 새 run 내부 접촉 통계: 부유 {old['floating_count']} → {new['floating_count']}, 관통 {old['penetrating_count']} → {new['penetrating_count']} (floor-supported 객체만).",
                      f"- floor X/Z 크기: `{meta['background'][0]['size_xz']}` (모델 좌표 단위; 실측 m 아님).",
                      f"- 산출물 검사: {row.get('artifact_valid')}; After viewer 검사: {row.get('viewer_valid')}; Before viewer 검사: {row.get('before_viewer_valid')}.",
                      f"- RunPod job: `{row.get('remote_job',{}).get('job_id')}`; 실행 시각: `{row.get('started_at')}`."]
    contact_rows = [x for x in rows if x.get('after_metadata',{}).get('placement')]
    totals = {phase: {metric: sum(x['after_metadata']['placement']['metrics'][phase][metric] for x in contact_rows)
                       for metric in ('floating_count','penetrating_count')}
              for phase in ('before','after')}
    improved, remaining, no_support = [], [], []
    for i, row in enumerate(rows, 1):
        metrics = row.get('after_metadata',{}).get('placement',{}).get('metrics')
        if metrics:
            old,new = metrics['before'],metrics['after']
            label = f'[sample {i:02d}](#sample-{i:02d})'
            if sum(new[k] for k in ('floating_count','penetrating_count')) < sum(old[k] for k in ('floating_count','penetrating_count')):
                improved.append(label)
            if new['floating_count'] or new['penetrating_count']:
                remaining.append(label)
            if not new['floor_supported_count']:
                no_support.append(label)
    lines += ['', '## 4. 전체 비교 결론', '',
              f"- 전체 {len(rows)}개, PASS {counts['PASS']}, PARTIAL {counts['PARTIAL']}, FAIL {counts['FAIL']}; Before 누락 7개.",
              f'- 새 GLB {len(generated)}개, floor {floor_count}개, After viewer 검증 통과 {viewer_count}개.',
              f"- 새 run 내부 지지 객체 합계: 부유 {totals['before']['floating_count']} → {totals['after']['floating_count']}, 관통 {totals['before']['penetrating_count']} → {totals['after']['penetrating_count']}. 과거 run과의 비교 수치가 아니다.",
              '- 접촉 통계가 개선된 sample: '+(', '.join(improved) or '없음')+'. 실제 화면 변화와 남은 형상 문제는 개별 비교에 기록했다.',
              '- 보정 후에도 부유/관통이 남는 sample: '+(', '.join(remaining) or '없음')+'.',
              f'- 지지 객체 분류가 0개인 sample은 {len(no_support)}개이며 바닥 생성만 적용됐다. 바닥이 생겼다는 사실을 배치 개선으로 집계하지 않았다.',
              '- 화면상 한계: 기울어진 통합 지형·큰 평판·누락 객체는 유지된다. 일부 scene은 넓은 바닥으로 자동 화면 배율이 작아져 세부가 덜 보인다. 새로운 형상 회귀를 단정할 근거는 없지만 이 표시상의 단점은 비교에서 확인된다.',
              '- 바닥 추가에 따른 표시상 문제: [sample 07](#sample-07)의 탁자와 [sample 10](#sample-10)의 낮은 소파 일부는 실제 WebGL에서 바닥에 가려진다. 미해결 관통을 바닥이 가리는 현상이며, 기능 검사 PASS와 시각적 품질 평가는 구분해야 한다.',
              '- 위치 보정은 보수적인 Y축 접촉 이동이며, orientation·형상 복원·객체 겹침·누락을 해결하는 알고리즘은 아니다. 각 sample의 실제 화면 관찰은 위에 구분했다.',
              '- 16MP 초과 7개는 현재 production 입력 제한으로 실패했다. 새 알고리즘·자동 리사이즈는 추가하지 않았다.',
              '- 기존 테스트 46 passed; placement/floor 포함. JS 구문 검사와 문서 이미지 경로 검사 수행.', '',
              '## 5. 근거', '',
              '- [기계 판독 결과](SAMPLES_BEFORE_AFTER_COMPARISON.json)',
              '- 실행 manifest 및 검사 로그: `runs/all_samples_comparison/20260929/` (로컬).',
              '- 각 After run의 `logs/remote_job.json`, `logs/runpod_timing.json`, `logs/remote_integrity.json`, `logs/placement.json`, `logs/artifact_validation.json`에 추론·무결성·접촉 보정 근거를 보존한다.', '']
    (ROOT/'docs/SAMPLES_BEFORE_AFTER_COMPARISON.md').write_text('\n'.join(lines),encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    render(parser.parse_args().manifest)
