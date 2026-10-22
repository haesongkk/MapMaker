"""Build the new comparison numbering from verified RAM++ and Qwen results."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mapmaker.scene_run import read, write, sha
from scripts.compare_baseline import POLICY


def report():
    baseline = read(ROOT / '.runtime/minimal-baseline/comparison.json')['samples']
    qwen = read(ROOT / '.runtime/qwen-baseline-v2/comparison.json')['samples']
    inventory = read(ROOT / 'docs/assets/four-way-comparison/inventory.json')['inputs']
    captures = {}
    for directory in ('baseline-comparison', 'qwen-baseline-v2-comparison'):
        for c in read(ROOT / 'docs/assets' / directory / 'captures.json'):
            captures[c['alias']] = c
    evidence = dict(numbering='four_way_v2', stages={
        '1': dict(name='RAM++ minimal baseline', status='implemented'),
        '2': dict(name='Qwen improved prompt baseline', status='implemented'),
        '3': dict(name='Stage 2 plus placement correction', status='not_implemented'),
        '4': dict(name='Stage 3 plus generated background', status='not_implemented')}, samples={})
    viewers = {}
    sections = []
    summary = ['| 입력 | 1번 RAM++ — 마스크 / 성공 / 실패 | 2번 Qwen — 마스크 / 성공 / 실패 |', '|---|---|---|']
    for item in inventory:
        name = item['id']
        label = item['label'] if not name.startswith('sample-') else name
        cells, counts, details, sample = [], [], [], {}
        for stage, source, prefix, directory in (
            (1, baseline, 'baseline', 'baseline-comparison'),
            (2, qwen, 'qwen-v2', 'qwen-baseline-v2-comparison')):
            record = source[name]
            if record['status'] != 'complete':
                cells.append('결과 검증·수집 중'); counts.append('미완료'); continue
            folder = ROOT / record['path']
            meta = read(folder / 'scene_metadata.json')
            assert meta['execution']['baseline_policy'] == POLICY
            assert meta['execution']['completed_mode'] == 1
            digest = sha(folder / 'scene.glb')
            assert digest == record['scene_sha256']
            alias = f'{prefix}-{name}-new'
            if stage == 1:
                viewers[alias] = record['path']
            capture = captures.get(alias)
            link = f'[웹뷰어](http://127.0.0.1:8118/viewer?run={alias})'
            if capture and capture['scene_sha256'] == digest and not capture['errors']:
                link = f'![{stage}번 {name}](assets/{directory}/{alias}.png)<br>' + link
            else:
                link = '캡처 준비 중<br>' + link
            cells.append(link)
            objects = meta['objects']
            ok = sum(o['status'] == 'generated' for o in objects)
            failed = sum(o['status'] == 'failed' for o in objects)
            assert ok + failed == len(objects)
            tags = meta['object_extraction']['candidates']
            counts.append(f'{len(objects)} / {ok} / {failed}')
            details.append(f'**{stage}번:** 태그 {len(tags)}개 · 마스크 {len(objects)}개 · 생성 성공 {ok}개 · 실패 {failed}개.')
            sample[str(stage)] = dict(run_id=meta['run_id'], path=record['path'],
                input_sha256=meta['input_sha256'], scene_sha256=digest,
                deployment=meta.get('deployment'), tags=tags, masks=len(objects), generated=ok, failed=failed,
                recovery=meta.get('recovery'), viewer=alias, capture=capture)
        if len(sample) == 2:
            assert sample['1']['input_sha256'] == sample['2']['input_sha256']
        evidence['samples'][name] = sample
        summary.append(f'| [{label}](#{name}) | {counts[0]} | {counts[1]} |')
        sections += [f'## {name}', '', f'![입력 — {label}]({item["input"].removeprefix("docs/")})', '',
            '| 1번 · RAM++ 기본값 베이스라인 | 2번 · Qwen 개선 프롬프트 | 3번 · 배치 개선 예정 | 4번 · 배경 생성 예정 |',
            '|---|---|---|---|', f'| {cells[0]} | {cells[1]} | 미구현 — 2번에 배치 개선 추가 | 미구현 — 3번에 배경 생성 추가 |', '',
            *details, '']
    text = ['# Four Way Comparison V2 — RAM++·Qwen·배치 개선·배경 생성', '',
        '작성 기준: 2026-10-23. 이 문서는 새 번호 체계를 사용한다. 기존 [FOUR_WAY_COMPARISON.md](FOUR_WAY_COMPARISON.md)는 과거 비교 자료로 보존하며, 그 문서의 2·3·4번 결과를 새 단계의 구현 결과로 사용하지 않는다.', '',
        '## 단계 정의', '',
        '| 번호 | 처리 방식 | 구현 상태 |', '|---|---|---|',
        '| **1번** | [BASELINE_COMPARISON.md](BASELINE_COMPARISON.md)의 수정 1번: RAM++ 기본 임계값 → 모든 반환 태그를 SAM3에 전달 → SAM3 기본 processor의 모든 반환 마스크를 SAM3D Objects로 생성 → 공식 pose 배치 | 구현됨 |',
        '| **2번** | [QWEN_PROMPT_COMPARISON.md](QWEN_PROMPT_COMPARISON.md)의 개선 버전: 1번의 태그 생성기를 Qwen2.5-VL-7B-Instruct와 개선 프롬프트로 교체. 이후 마스크·3D 생성·공식 pose 배치는 동일 | 구현됨 |',
        '| **3번** | 2번에 물체 배치 문제 개선을 추가 | **미구현 · 계획** |',
        '| **4번** | 3번에 배경 생성을 추가 | **미구현 · 계획** |', '',
        '3번의 배치 보정 알고리즘과 4번의 배경 생성 방법은 아직 정해지지 않았다. 3·4번의 성능·결과 이미지·웹뷰어는 아직 없다.', '',
        '문서의 단계 번호와 코드의 실행 모드 번호는 구분한다. 새 1·2번은 모두 기존 코드의 mode=1 경로를 사용하며 태그 생성기만 다르다. 새 3·4번은 기존 코드의 같은 번호 모드를 재사용했다고 간주하지 않는다.', '',
        '## 공통 조건과 1·2번의 차이', '',
        '- 같은 샘플끼리 정규화된 입력 PNG의 SHA-256이 일치한다.',
        '- SAM3의 모델 기본 임계값을 유지하며, 반환된 마스크에 별도의 점수·면적·중복 필터나 개수 제한을 적용하지 않는다.',
        '- 모든 반환 마스크를 SAM3D Objects에 seed 42로 전달하고 공식 pose로 배치한다. 추가 배치 보정이나 배경 생성은 없다.',
        '- 1번은 RAM++가 기본 임계값으로 반환한 태그를 그대로 사용한다.',
        '- 2번은 Qwen 개선 프롬프트로 벽·바닥·천장 같은 배경을 제외하고 문·창문을 포함한 물체 종류를 요청한다. 같은 종류는 한 번만 나열하고 부착 부품·동의어 중복을 피하도록 지시한다. 이는 프롬프트 지시이며 반환 뒤 별도 의미 필터나 이름 치환은 없다.',
        '- Qwen 모델·revision·원문 프롬프트는 [프롬프트 비교 문서](QWEN_PROMPT_COMPARISON.md)에 기록돼 있다.', '',
        '## 결과 수집과 검증', '',
        '1번의 집·사무실은 기존 완료 결과를 사용한다. 나머지 8장은 원격에 보존된 추론 체크포인트를 수집해 ZIP SHA-256, 입력, 모든 마스크·객체 파일의 SHA-256, 장면 내 객체 배치 행렬을 검증한 뒤 1번 최종화를 수행했다. 이 과정에서 원본 GLB·객체·배치 행렬을 바꾸지 않았으며 추가 GPU 추론을 하지 않았다. 2번은 직전에 완료한 10장 결과를 재사용한다.', '',
        '실제 배포 코드와 복구 여부, 입력·장면 해시, 태그·객체 수, 캡처 카메라는 [검증 기록](assets/four-way-v2-comparison/manifest.json)에 샘플별로 남긴다. 생성 성공은 파일 생성과 검증 성공을 뜻하며 형태·배치의 정확도를 뜻하지 않는다.', '',
        '웹뷰어는 `uv run mapmaker review`로 로컬 검토 서버를 실행한 뒤 연다. 원본 GLB는 로컬 `.runtime/`에 보관하며 Git에 포함되지 않는다. 각 샘플의 1·2번 캡처는 과거 비교에서 사용한 동일 카메라 위치와 시선을 적용한다. 물체가 화면 밖에 있을 수 있으므로 전체 결과는 웹뷰어에서도 확인한다.', '',
        '## 10장 요약', '', *summary, '', *sections]
    assets = ROOT / 'docs/assets/four-way-v2-comparison'
    assets.mkdir(parents=True, exist_ok=True)
    write(assets / 'manifest.json', evidence)
    write(ROOT / 'docs/assets/baseline-comparison/viewers.json', viewers)
    (ROOT / 'docs/FOUR_WAY_COMPARISON_V2.md').write_text('\n'.join(text), encoding='utf-8')


if __name__ == '__main__':
    report()
