"""Publish the comparison specification and honest per-input readiness."""
import html
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
inventory=json.loads((ROOT/'.runtime/four-way-comparison/inventory.json').read_text(encoding='utf-8'))
assets=ROOT/'docs/assets/four-way-comparison';assets.mkdir(exist_ok=True)
spec='''# 사진별 4단계 비교 — 실행 명세와 준비 상태

현재 상태: 입력 사진 10장에 대한 4가지 방식의 GLB 40개 생성 완료. 각 결과의 실제 웹뷰어 화면을 해당 번호에 첨부한다. 운영 endpoint는 v4로 복원되었으며 환경·워커 설정 재확인을 완료했다.

## 1. 전체 사진만 사용하는 초기 방식

기준 커밋 `51edb4f`의 RAM++ 탐지·SAM3 분할·SAM3D 생성 코드를 사용하되, 영역 확대 탐색을 제거한다. 전체 이미지 1개에서 RAM++ 후보를 얻고, 후보 상위 40개를 SAM3 텍스트 프롬프트로 분할한다. 마스크 신뢰도 0.6 이상, 면적 0.3% 이상, 최대 12개를 선택한다. 기존의 IoU/포함 중복 제외 규칙을 유지한다. SAM3D seed 42로 생성하고 공식 pose로 조립한다. 장면 정렬·개별 접지·자세·관통 보정·배경 생성을 적용하지 않는다.

주의: 기준 커밋 자체에는 영역 탐색이 이미 있었다. 따라서 이 프로필은 커밋 그대로가 아니라 사용자가 요청한 '전체 사진만' 조건으로 탐색을 제거한 초기 방식이다. 새로운 모델이나 재학습은 없다.

## 2. 확장 탐색 + 보정 전 객체

현재 작업 트리의 생성 코드를 동결했다. 전체 이미지와 최대 14개 부분 영역에서 RAM++를 실행하고, 지역 후보를 추가 분할한다. SAM3의 점 기반 탐색, 여러 관측의 마스크 일치, 작은 객체 최소 면적 0.05%·64픽셀, 작은 객체 우선 슬롯 3개, 기본 32개·조건부 최대 48개 선택을 사용한다. 작은 영역이 큰 영역 안에 있다는 이유만으로 삭제하지 않는다.

현재 생성 단계의 공유 pointmap, 깊이에 따른 마스크 검토, 생성 대안 검토도 포함한다. 좌표 변환은 SAM3D pose를 GLB로 옮기는 데 필요한 변환뿐이며, 장면 보정·배경은 적용하지 않는다. 따라서 1→2는 탐색 변경 하나만의 효과를 분리한 실험이 아니라 초기 생성 방식과 현재 생성 방식의 비교다. 실행 환경의 선택적 기능 설정은 제출 시 별도 기록해야 한다.

## 3. 같은 객체 자산 + 현재 보정

2번의 마스크·메시·pose·pointmap을 해시로 고정하고 CPU에서 현재 보정 코드를 적용한다. 전체 방향 추정, 원본·깊이 기반 자세 후보, 유한 지지면 접촉, 기존 접촉 보존, 실제 메시 관통 검사를 포함한다. 객체 이름은 보정 판단에 사용하지 않는다. 공간 표면은 접촉 판단에 내부적으로 필요하므로 계산하지만 결과 GLB에는 표시용 공간을 포함하지 않는다. 중복·배경 후보를 제외하면 객체 개수가 달라질 수 있고, 변경 이유를 기록한다. 새 객체 생성은 하지 않는다.

## 4. 3번과 동일한 객체 배치 + 공간 배경

3번에서 사용한 공간 표면을 별도 그룹으로 내보낸다. 객체 메시·변환은 3번과 정확히 같아야 한다. 깊이·법선·소실점 기반 평면, 관측된 배경 메시, 제한된 가림 영역 보완과 충돌 검사를 포함한다. 아직 논의만 한 '깔끔한 다각형으로 경계 정리'는 추가하지 않는다. 현재 규칙의 효과를 비교하기 위한 실험이다.

## 비교·검증 규칙

- 네 장면 모두 같은 입력 사진을 사용한다. 원래 pose의 GLB 좌표 변환과 보정 이동은 구분한다.
- 1·2의 메시 차이는 재추론을 포함하므로 보정 효과로 해석하지 않는다.
- 2→3은 원본 메시 해시와 객체별 변환/제외 기록을 비교한다.
- 3→4는 객체별 메시와 월드 변환이 동일한지 확인한다.
- 첨부 이미지는 각 웹뷰어의 기본 시점이다. 장면 크기에 따른 자동 화면 맞춤이 적용되므로 이미지상의 크기 차이를 실제 이동·크기 변화로 해석하지 않는다. 정밀한 같은 카메라 비교용 촬영은 아니다.
- 결과에는 객체 수, 실행 코드 해시, 실패 객체, 보정 내역, GLB와 이미지 링크를 기록한다.
- 이 10장은 사용자가 열람하는 비교 자료로 취급한다. 향후 미사용 평가 세트라고 부르지 않는다.

## 사진별 결과
'''
comparison_root=ROOT/'.runtime/four-way-comparison'
captures_path=comparison_root/'viewer-captures.json'
captures={r['alias']:r for r in json.loads(captures_path.read_text(encoding='utf-8'))} if captures_path.exists() else {}
parts=[spec]
viewers={}
body='<h1>사진별 4단계 비교</h1><p>10장 × 4방식 · GLB 40개 · 결과 이미지 '+str(len(captures))+'/40개</p>'
body+='<p><a href="/docs/FOUR_WAY_COMPARISON.md">전체 구현 명세 및 문서 원본</a></p>'
body+='<p>각 이미지를 누르면 크게 볼 수 있습니다. 웹뷰어 링크는 바로 아래에 있습니다. 이미지는 각 웹뷰어의 기본 시점이며 자동 화면 맞춤이 적용됩니다.</p>'
body+='<details><summary>구현 상세와 비교 규칙</summary><pre>'+html.escape(spec)+'</pre></details>'
labels={1:'초기 방식 · 보정 없음',2:'확장 탐색 · 보정 없음',3:'현재 보정 적용',4:'현재 보정 + 공간 배경'}
for item in inventory['inputs']:
    ident=item['id'];source=ROOT/item['input'];copied=assets/(ident+source.suffix.lower())
    shutil.copy2(source,copied)
    rel=copied.relative_to(ROOT/'docs').as_posix()
    title=f"{ident} — {item['label']}"
    parts.append(f"\n## {title}\n\n![입력 사진]({rel})\n")
    body+='<section><h2>'+html.escape(title)+'</h2><details><summary>입력 사진</summary><img src="/docs/'+rel+'" alt="입력 사진"></details><div class="grid">'
    for i in range(1,5):
        folder=comparison_root/'results'/ident/str(i)
        complete=(folder/('comparison-collected.json' if i<3 else 'comparison-complete.json')).is_file()
        key=f'four-way-{ident}-{i}'
        if not complete:raise RuntimeError('Missing result '+key)
        viewers[key]=folder.relative_to(ROOT).as_posix()
        url=f'http://127.0.0.1:8118/viewer?run={key}'
        parts.append(f"\n### {i}번 — {labels[i]}\n")
        body+=f'<article><h3>{i}번 · {labels[i]}</h3>'
        if key in captures:
            capture=captures[key]
            if capture['folder']!=viewers[key]:raise RuntimeError('Capture mismatch '+key)
            img=Path(capture['asset']).relative_to('docs').as_posix()
            if not (ROOT/'docs'/img).is_file():raise RuntimeError('Missing image '+key)
            parts.append(f'\n![{ident} {i}번 결과]({img})\n')
            body+=f'<a href="/docs/{img}" target="_blank"><img loading="lazy" src="/docs/{img}" alt="{ident} {i}번 결과"></a>'
        else:body+='<p>이미지 촬영 중</p>'
        parts.append(f'\n[웹뷰어]({url})\n')
        body+=f'<p><a href="{url}" target="_blank">{i}번 웹뷰어 열기</a></p></article>'
    body+='</div></section>'
(ROOT/'docs/FOUR_WAY_COMPARISON.md').write_text('\n'.join(parts),encoding='utf-8')
style='body{font-family:system-ui;max-width:1600px;margin:32px auto;padding:20px;background:#111827;color:#e5e7eb}a{color:#7dd3fc}img{max-width:100%;max-height:480px}section{border-top:1px solid #475569;margin-top:36px;padding-top:20px}pre{white-space:pre-wrap;line-height:1.6}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}article{background:#1e293b;padding:12px}article img{width:100%;height:auto}h2{overflow-wrap:anywhere}h3{font-size:16px}@media(max-width:1100px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){.grid{grid-template-columns:1fr}}'
(ROOT/'docs/FOUR_WAY_COMPARISON.html').write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>사진별 4단계 비교</title><style>'+style+'</style>'+body,encoding='utf-8')
temporary=comparison_root/'viewers.tmp.json'
temporary.write_text(json.dumps(viewers,indent=2),encoding='utf-8')
temporary.replace(comparison_root/'viewers.json')
print(f'Wrote {len(viewers)} viewers and {len(captures)} result images; no historical references.')
