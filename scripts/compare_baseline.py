"""Run and document the old/new mode-1 comparison without overwriting old runs.

python scripts/compare_baseline.py --run  # requires deployed matching application
python scripts/compare_baseline.py        # refresh report from saved state
"""
import argparse
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mapmaker.scene_run import write, sha


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

WORK = ROOT / '.runtime/minimal-baseline'
ASSETS = ROOT / 'docs/assets/baseline-comparison'
POLICY = 'default_model_outputs_unfiltered_v1'


def report():
    ASSETS.mkdir(parents=True, exist_ok=True)
    inventory = read(ROOT/'docs/assets/four-way-comparison/inventory.json')['inputs']
    previous = read(ROOT/'docs/assets/four-way-comparison/viewers.json')
    state = read(WORK/'comparison.json') if (WORK/'comparison.json').exists() else {'samples': {}}
    captures = read(ASSETS/'captures.json') if (ASSETS/'captures.json').exists() else []
    captures = {c['alias']: c for c in captures}
    viewers = {}
    text = ['# 1번 비교 — 이전 구현과 모델 기본값 베이스라인', '',
        '이전 1번은 [4방식 비교 문서](FOUR_WAY_COMPARISON.md)의 기존 이미지와 웹뷰어를 그대로 사용한다. 수정 1번은 RAM++와 SAM3의 기본 임계값을 유지하고, 반환된 모든 태그와 마스크를 자체 필터 없이 다음 모델에 전달한다. SAM3D Objects의 공식 pose로 조립한다.', '',
        '| 항목 | 이전 1번 | 수정 1번 |', '|---|---|---|',
        '| RAM++ | 임계값 배율 0.75, 후보 필터·이름 치환·최대 40개 | 기본 임계값, 모든 반환 태그 |',
        '| SAM3 | 기본 processor 이후 점수·면적·중복 필터, 최대 12개 | 기본 processor가 반환한 모든 마스크 |',
        '| SAM3D Objects | 선택된 마스크별 seed 42 | 모든 반환 마스크별 seed 42 |',
        '| 배치 | 공식 pose, 추가 보정 없음 | 공식 pose, 추가 보정 없음 |', '',
        '실행 기록: 초기 수정 버전으로 집·사무실을 완료했다. 식당의 149개 마스크 실행은 조립 중 컨테이너 메모리 한도(46.57 GiB)를 초과해 종료되어 자동 재시도를 취소했다. 이후 메시·pose를 유지하는 순차 조립 경로를 배포하고 식당을 동일 입력으로 다시 실행했다. 사진별 실제 배포 코드 해시를 기록한다.', '',
        '대용량 1번은 원본 GLB 버퍼를 순차 합성하며 Gaussian 통합 및 CPU 미리보기는 생략한다. 객체 메시·pose는 유지하고 실제 GLB 웹뷰어를 촬영한다.', '',
        '마스크 중복이나 작은 영역도 그대로 생성한다. 생성 수 증가는 정확도 개선을 뜻하지 않는다. 실패는 별도 기록한다. 기존 실행 파일의 정규화된 입력 PNG를 재사용하고 SHA-256 일치를 확인한다.', '',
        '웹뷰어: 저장소에서 `uv run mapmaker review` 실행 후 아래 링크를 연다. GLB는 로컬 `.runtime/` 자산이며 Git에 포함되지 않는다. 새 캡처는 기존 캡처의 카메라 위치와 바라보는 지점을 적용하고 촬영 기록에 남긴다. 전체 장면이 그 화면 밖으로 확장될 수 있으므로 웹뷰어에서도 확인한다.', '']
    for item in inventory:
        name = item['id']; alias = f'baseline-{name}-new'
        old_alias = f'four-way-{name}-1'; old_folder = ROOT/previous[old_alias]
        old = read(old_folder/'scene_metadata.json')
        record = state['samples'].get(name, {})
        old_count = sum(o.get('status')=='generated' for o in old['objects'])
        new_cell = '실행 대기 — 새 결과 없음'
        details = f'이전 생성 성공: {old_count}개.'
        if record.get('status') == 'complete':
            folder = ROOT/record['path']; m = read(folder/'scene_metadata.json')
            if (m.get('execution',{}).get('baseline_policy') != POLICY or
                    m['input_sha256'] != old['input_sha256']):
                raise ValueError(f'Invalid comparison provenance: {name}')
            viewers[alias] = record['path']
            success = sum(o.get('status')=='generated' for o in m['objects'])
            failed = sum(o.get('status')=='failed' for o in m['objects'])
            details += f" 수정: 태그 {len(m['object_extraction']['candidates'])}개 / 마스크 {len(m['objects'])}개 / 생성 성공 {success}개 / 실패 {failed}개."
            capture = captures.get(alias)
            if capture and capture['scene_sha256']==sha(folder/'scene.glb'):
                new_cell = f'![수정 1번](assets/baseline-comparison/{alias}.png)<br>[웹뷰어](http://127.0.0.1:8118/viewer?run={alias})'
            else:
                new_cell = f'캡처 대기<br>[웹뷰어](http://127.0.0.1:8118/viewer?run={alias})'
            seconds = m.get('timing',{}).get('total_seconds')
            duration = f'{seconds:.1f}초' if seconds is not None else '전체 시간 미기록'
            details += f" 파이프라인 시간: {duration}. 실행 코드: `{m.get('deployment',{}).get('application_sha256','unknown')}`."
            if m.get('recovery'):
                details += ' 검증된 추론 체크포인트에서 1번 최종화를 수행했다. 원본 장면과 모든 객체를 보존했으며 CPU 미리보기는 생략했다.'
        elif record:
            new_cell = {'running':'실행 중','failed':'실행 실패 — 새 결과 미완료'}.get(record.get('status'),'실행 대기')
        text += [f"## {name} — {item['label']}", '', f"![입력]({item['input'].removeprefix('docs/')})", '',
            '| 이전 1번 | 수정 1번 |','|---|---|',
            f'| ![이전 1번](assets/four-way-comparison/{old_alias}.png)<br>[웹뷰어](http://127.0.0.1:8118/viewer?run={old_alias}) | {new_cell} |', '', details, '']
    write(ASSETS/'viewers.json', viewers)
    (ROOT/'docs/BASELINE_COMPARISON.md').write_text('\n'.join(text),encoding='utf-8')


def run_batch():
    from mapmaker.scene_pipeline import create_run
    from mapmaker.scene_remote import RemotePipeline
    from mapmaker.remote_settings import load_settings
    load_settings(); WORK.mkdir(parents=True,exist_ok=True)
    state_file=WORK/'comparison.json'
    state=read(state_file) if state_file.exists() else {'samples':{}}
    release=read(WORK/'release.json')
    mapping=read(ROOT/'docs/assets/four-way-comparison/viewers.json')
    inventory=read(ROOT/'docs/assets/four-way-comparison/inventory.json')['inputs']
    pipeline=RemotePipeline(timeout=21600)
    try:
        for item in inventory:
            name=item['id']; existing=state['samples'].get(name)
            if existing:
                if existing['status']=='complete': continue
                raise RuntimeError(f'{name}: existing incomplete attempt; inspect it before any resubmission')
            old=ROOT/mapping[f'four-way-{name}-1']; old_meta=read(old/'scene_metadata.json')
            folder=create_run((old/old_meta['input_image']).read_bytes(),WORK/'runs'/uuid.uuid4().hex,mode=1)
            assert read(folder/'scene_metadata.json')['input_sha256']==old_meta['input_sha256']
            record=state['samples'][name]={'path':folder.relative_to(ROOT).as_posix(),'status':'running'}
            write(state_file,state);report(); print(f'Starting {name}',flush=True)
            try:
                pipeline.run(folder)
                m=read(folder/'scene_metadata.json')
                assert m['execution'].get('baseline_policy')==POLICY,'Wrong worker baseline policy'
                assert m['deployment']['application_sha256']==release['sha256'],'Wrong worker release'
                assert m['input_sha256']==old_meta['input_sha256'],'Input changed'
                assert all(o['status'] in ('generated','failed') for o in m['objects'])
                record.update(status='complete',scene_sha256=sha(folder/'scene.glb'))
            except Exception as exc:
                record.update(status='failed',error=str(exc));write(state_file,state);report();raise
            write(state_file,state);report();print(f'Completed {name}',flush=True)
    finally:
        pipeline.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');args=parser.parse_args()
    if args.run: run_batch()
    report()
