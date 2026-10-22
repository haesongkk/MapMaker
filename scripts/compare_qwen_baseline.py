"""Report the two-image Qwen/RAM++ baseline comparison from saved evidence."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.compare_baseline import ROOT, read, POLICY
from mapmaker.scene_run import write, sha
from mapmaker.qwen_tags import MODEL, REVISION, PROMPT


def report(v2=False):
    work=ROOT/('.runtime/qwen-baseline-v2' if v2 else '.runtime/qwen-baseline')
    state=read(work/'comparison.json')
    previous=read(ROOT/'.runtime/minimal-baseline/comparison.json')['samples']
    asset_name='qwen-baseline-v2-comparison' if v2 else 'qwen-baseline-comparison'
    assets=ROOT/'docs/assets'/asset_name;assets.mkdir(parents=True,exist_ok=True)
    if v2:
        previous=read(ROOT/'.runtime/qwen-baseline/comparison.json')['samples']
    prompt=state.get('prompt',PROMPT)
    for record in state['samples'].values():
        if record['status']=='complete':
            prompt=read(Path(record['path'])/'scene_metadata.json')['object_extraction']['prompt'];break
    captures=read(assets/'captures.json') if (assets/'captures.json').exists() else []
    captures={c['alias']:c for c in captures};viewers={}
    text=['# '+('Qwen 프롬프트 비교: 기존과 문·창문 포함 객체 중심 버전' if v2 else '현재 1번 비교: RAM++와 Qwen2.5-VL'), '',
        f'모델: `{MODEL}` / revision `{REVISION}`.', '',
        ('Qwen에 입력하는 지시문만 변경한다.' if v2 else '현재 1번의 태그 생성기만 교체한다.')+' SAM3 기본 임계값, 모든 반환 마스크의 SAM3D 입력, seed 42, 공식 pose 배치를 유지한다. 태그 치환·중복 제거·마스크 선별·개수 제한은 없다.', '',
        'Qwen은 고정 어휘 분류기가 아니라 지시문에 따라 태그를 생성한다. 아래 공통 지시문과 greedy decoding(seed 42, 최대 2048 새 토큰)을 사용한다. 이미지 전처리는 모델 기본값이다. JSON 전체를 감싼 Markdown 코드블록만 벗기며 태그 문자열은 수정하지 않는다. 출력이 잘리거나 JSON 형식이 잘못되면 실패로 기록한다.', '',
        '```text',prompt,'```','',
        'Qwen Transformers 4.51.3 / tokenizers 0.21.4는 별도 경로에 설치한다. Qwen 프로세스가 종료된 뒤 기존 SAM3와 SAM3D 환경을 그대로 사용한다.', '',
        ('집·사무실의 프롬프트 비교와 같은 개선 프롬프트로 실행한 나머지 테스트 이미지 8장을 함께 기록한다.' if v2 else '기존 RAM++ 실행의 입력 PNG와 SHA-256이 같은 집·사무실을 비교한다.')+' 웹뷰어는 로컬 검토 서버가 필요하다.', '']
    for name in ('house','office'):
        old=previous[name];oldmeta=read(ROOT/old['path']/'scene_metadata.json')
        record=state['samples'][name];alias=f'{"qwen-v2" if v2 else "qwen"}-{name}-new'
        cell='실행 대기';detail=f"실행 상태: {record['status']}"
        if record['status']=='complete':
            folder=ROOT/record['path'];meta=read(folder/'scene_metadata.json')
            assert meta['input_sha256']==oldmeta['input_sha256']
            assert meta['object_extraction']['model']==MODEL
            assert meta['execution']['baseline_policy']==POLICY
            viewers[alias]=record['path']
            cell=f'[웹뷰어](http://127.0.0.1:8118/viewer?run={alias})'
            if captures.get(alias,{}).get('scene_sha256')==sha(folder/'scene.glb'):
                cell=f'![Qwen](assets/{asset_name}/{alias}.png)<br>'+cell
            n=len(meta['objects']);ok=sum(o['status']=='generated' for o in meta['objects'])
            detail=f"Qwen 태그 {len(meta['object_extraction']['candidates'])}개 / 마스크 {n}개 / 생성 성공 {ok}개 / 실패 {n-ok}개."
            detail+=f" 이전 결과: 태그 {len(oldmeta['object_extraction']['candidates'])}개 / 마스크 {len(oldmeta['objects'])}개 / 생성 성공 {sum(o['status']=='generated' for o in oldmeta['objects'])}개."
            detail+='\n\n반환 태그: '+', '.join(meta['object_extraction']['candidates'])
            if v2:
                detail+='\n\n벽·바닥·천장 태그 포함 여부: '+str([t for t in meta['object_extraction']['candidates'] if t in ('wall','walls','floor','flooring','ceiling')])
                if any('_' in t for t in meta['object_extraction']['candidates']):
                    detail+='. 공백 사용 지시와 달리 밑줄이 포함된 태그도 반환됐으며, 후처리 치환 없이 그대로 SAM3에 전달했다.'
            detail+=f"\n\n실행 코드: `{meta.get('deployment',{}).get('application_sha256','unknown')}`. 장면 SHA-256: `{sha(folder/'scene.glb')}`."
        elif record['status']=='failed':cell='실행 실패 — 로그 확인 필요'
        elif record['status']=='submitted':cell='원격 제출 완료 — 결과 미수집'
        old_alias=f'qwen-{name}-new' if v2 else f'baseline-{name}-new'
        old_assets='qwen-baseline-comparison' if v2 else 'baseline-comparison'
        text += [f'## {name}', '', '| '+('Qwen 기존 프롬프트 | Qwen 개선 프롬프트' if v2 else 'RAM++ 현재 1번 | Qwen 현재 1번')+' |','|---|---|',
            f'| ![이전](assets/{old_assets}/{old_alias}.png)<br>[웹뷰어](http://127.0.0.1:8118/viewer?run={old_alias}) | {cell} |','',detail,'']
    if v2:
        if recovery := state.get('recovery'):
            text += ['## 저장 실패 진단과 복구', '',
                f"재실행에서 확인한 오류: `{recovery['confirmed_error']}`. 추론 뒤 중간 결과와 최종 ZIP을 원격 저장소에 업로드할 때 용량 한도에 걸렸다.", '',
                f"사용자 승인 후 완료 실행의 중간 체크포인트 {recovery['backed_up_checkpoints']}개를 로컬에 백업하고 SHA-256을 검증한 다음 원격 중복 사본을 정리하여 {recovery['freed_bytes']:,}바이트를 확보했다. 최종 결과 ZIP과 모델 파일은 유지했다.", '',
                '저장 재시도·업로드 크기 검증·독립 오류 기록을 추가했다. Qwen 프롬프트, SAM3 마스크 처리, SAM3D 생성 및 배치 설정은 유지했다. 아래 완료 표시는 결과 ZIP과 GLB 해시, 모델 및 프롬프트를 검증한 실행만 뜻한다.', '',
                'sample-02의 대형 GLB를 브라우저에서 열 때 발생한 Blob 읽기 오류도 수정했다. 조각 다운로드를 단일 ArrayBuffer에 합쳐 직접 파싱하며, 원본 GLB 데이터는 변경하지 않는다.', '']
            if resize := recovery.get('storage_resize'):
                text += [f"restaurant의 3.40GB ZIP은 멀티파트 업로드를 합치는 단계에서도 용량 제한에 걸렸다. 사용자 승인 후 저장소 `{resize['volume_id']}`를 {resize['before_gb']}GB에서 {resize['after_gb']}GB로 증설했고, 진행 중이던 업로드 재시도에서 중간 저장에 성공했다. 저장소 추가 비용은 월 ${resize['additional_monthly_usd']:.2f} 상당이다.", '']
        text += ['## 추가 테스트 이미지 8장', '', '집·사무실과 동일한 개선 프롬프트 및 모델 설정으로 실행한다.', '']
        for name,record in state['samples'].items():
            if name in ('house','office'):continue
            text += [f'### {name}', '']
            if record['status']!='complete':
                text += [f"실행 상태: {record['status']} — 검증된 최종 결과 미수집.", ''];continue
            folder=Path(record['path']);meta=read(folder/'scene_metadata.json')
            alias=f'qwen-v2-{name}-new';viewers[alias]=record['path']
            n=len(meta['objects']);ok=sum(o['status']=='generated' for o in meta['objects'])
            text += [f"태그 {len(meta['object_extraction']['candidates'])}개 / 마스크 {n}개 / 생성 성공 {ok}개 / 실패 {n-ok}개.",'']
            if captures.get(alias,{}).get('scene_sha256')==sha(folder/'scene.glb'):
                text += [f'![결과](assets/{asset_name}/{alias}.png)','']
            text += [f'[웹뷰어](http://127.0.0.1:8118/viewer?run={alias})','',
                '반환 태그: '+', '.join(meta['object_extraction']['candidates']),'',
                f"실행 코드: `{meta['deployment']['application_sha256']}`.",'']
    write(assets/'viewers.json',viewers)
    (ROOT/'docs'/('QWEN_PROMPT_COMPARISON.md' if v2 else 'QWEN_BASELINE_COMPARISON.md')).write_text('\n'.join(text),encoding='utf-8')


if __name__=='__main__':report(v2='--v2' in sys.argv)
