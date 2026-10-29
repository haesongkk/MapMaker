"""Build the three selected presentation cases from saved evidence."""
from pathlib import Path
import html
import json

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / 'artifacts'
ASSETS = ARTIFACTS / 'assets/ram-qwen-filter-new-scenes'
METHOD = 'vision-furniture'
PROMPT = '''List the furniture and other movable physical objects visible in this image.

Use specific, common object names, with one tag per object category.
Return only a JSON array of strings.'''
PICKS = [
    ('present-office-c', '01', '원목 서재', '대표 결과물 · 복합 가구 장면',
     '책상·의자·책장에 화분과 소품이 함께 있는 장면입니다. 정면과 양옆에서 주요 가구의 몸통과 지지 구조를 확인했고, 원목 색감과 책장 내부 표현도 남습니다.',
     '베이스라인에서는 책장·책상 동의어와 방 관련 태그로 거대한 중복 형상이 생깁니다. 최종 결과는 desk / chair / bookcase를 각각 1개씩 생성해 주요 가구 구성이 드러납니다. 전체 생성 객체는 44개에서 22개로 줄었습니다.',
     '책상 다리 일부가 판형으로 변하고 소품·화분의 높이 오차가 남습니다. 벽 없는 액자와 코르크보드가 떠 보이며, 소품 중복까지 모두 해결된 것은 아닙니다.'),
    ('present-cabinet', '02', '수납장과 식물', '주요 가구 중복 개선',
     '수납장의 몸통·서랍 면·다리가 이어지고 큰 식물과의 구성이 읽힙니다. 여러 각도에서 주요 가구 형상을 확인했습니다.',
     '베이스라인에서는 bureau / dresser / furniture와 개별 drawer가 겹칩니다. 최종 결과는 dresser 1개로 주요 수납장 중복을 줄였습니다.',
     '작은 화병이 상판 위에 떠 있고 소품 중복이 남습니다. 원본 나무색보다 밝게 표현됩니다.'),
    ('new-office', '03', '작업 공간', '배경 메시 제거 효과',
     '기본 RAM++ 결과에서는 방 메시가 가구를 가립니다. 최종 결과에서는 책상·의자·모니터의 구성이 드러나 변화가 분명합니다.',
     '장면 전체를 가리는 방·바닥·천장 관련 객체가 줄어, 개별 가구 중심의 장면을 확인할 수 있습니다.',
     '창·블라인드는 남고 서랍장 형상이 확장되어, 정밀한 형상·배치 복원을 주장하는 사례는 아닙니다.'),
]

def main():
    records = json.loads((ASSETS / 'scene-manifest.json').read_text(encoding='utf-8'))
    inputs = {s['sample']: s for s in json.loads((ASSETS / 'selection.json').read_text(encoding='utf-8'))['samples']}
    image_roots = {name:'assets/ram-qwen-filter-new-scenes' for name in inputs}
    for directory in ('ram-qwen-filter-presentation', 'ram-qwen-filter-complex'):
        extra = ARTIFACTS / 'assets' / directory
        if (extra/'scene-manifest.json').exists():
            records.update(json.loads((extra/'scene-manifest.json').read_text(encoding='utf-8')))
            for item in json.loads((extra/'selection.json').read_text(encoding='utf-8'))['samples']:
                inputs[item['sample']]=item
                image_roots[item['sample']]='assets/'+directory
    e = html.escape
    baseline = 'RAM++ 기본 태그 → SAM3 → SAM3D'
    final = 'Qwen 비전 furniture → SAM3 → SAM3D'
    intro = '발표 최종 버전은 Qwen 비전 furniture로 고정합니다. 원목 서재, 수납장·식물, 작업 공간의 세 장면을 선정했습니다. 모두 같은 프롬프트와 생성 설정을 사용하며, 장면별로 다른 버전을 섞지 않았습니다.'
    out = ['''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>발표 최종 선정 · 식사 공간과 작업 공간</title><style>
    *{box-sizing:border-box}body{margin:0;background:#101722;color:#edf3fa;font:16px/1.65 system-ui,sans-serif}main{max-width:1560px;margin:auto;padding:48px 32px}h1{font-size:38px;line-height:1.25;margin:10px 0 20px}h2{font-size:28px;margin:0}p{color:#b7c5d6}a{color:#8fded1}header{padding-bottom:24px}.eyebrow{color:#8fded1;letter-spacing:.1em;font-size:13px}.method{display:flex;gap:20px;flex-wrap:wrap;background:#192536;padding:20px;border-radius:12px}.method div{flex:1;min-width:280px}.method small{display:block;color:#a8b8cb}nav{display:flex;gap:24px;margin-top:24px}section{border-top:1px solid #334254;padding:32px 0}.badge{color:#8fded1;font-size:14px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:24px 0}figure{margin:0;background:#192536;border:1px solid #334254;border-radius:12px;overflow:hidden}figure.final{border-color:#69cbb8}figcaption{padding:14px;font-weight:600}figure img{width:100%;height:340px;object-fit:contain;display:block;background:#111b29}.links{padding:12px 14px;font-size:14px}.note{font-size:14px;color:#a8b8cb}details{background:#192536;border-radius:10px;padding:16px;margin:16px 0}summary{cursor:pointer}pre{white-space:pre-wrap;font:14px/1.6 ui-monospace,monospace}footer{border-top:1px solid #334254;padding-top:24px;font-size:14px}@media(max-width:900px){main{padding:24px 16px}h1{font-size:29px}.grid{grid-template-columns:1fr}figure img{height:auto;max-height:480px}}
    </style></head><body><main><header><div class="eyebrow">PRESENTATION / FINAL SELECTION</div><h1>가구 중심의 3D 장면 생성</h1>''',
    f'<p>{intro}</p><div class="method"><div><small>비교 베이스라인</small>{baseline}</div><div><small>최종 선정</small>{final}</div></div>',
    '<p>개선 포인트는 SAM3D 모델 자체의 형상 성능 향상이 아니라, 생성할 객체를 이미지에서 선택해 불필요한 배경·중복 생성을 줄이는 것입니다. 아래 결과는 수동 객체 삭제·배치 보정 없이 기존 실행 결과를 사용했습니다.</p>',
    '<nav>'+''.join(f'<a href="#{p[0]}">{p[1]} {p[2]}</a>' for p in PICKS)+'</nav></header>']
    for name, number, title, role, reason, improvement, limitation in PICKS:
        out += [f'<section id="{name}"><span class="badge">{number} / {role}</span><h2>{title}</h2><p>{reason}</p><div class="grid">']
        for version, label in [('input','원본 이미지'), ('baseline','베이스라인 · RAM++'), (METHOD,'최종 · Qwen 비전 furniture')]:
            filename = Path(inputs[name]['input_path']).name if version=='input' else f'{name}-{version}.png'
            if version!='input' and (ARTIFACTS/image_roots[name]/f'{name}-{version}-clean.png').exists():
                filename=f'{name}-{version}-clean.png'
            src = f'{image_roots[name]}/{filename}'
            assert (ARTIFACTS/src).exists()
            url = inputs[name]['source_url'] if version=='input' else f"/viewer?run={records[name][version]['alias']}"
            link_label = '원본 출처' if version=='input' else '3D 열기 ↗'
            cls = ' class="final"' if version==METHOD else ''
            kind = '<br><small>상품 연출 이미지 · AI 생성 추정(원본 파일명 기준)</small>' if version=='input' and name=='present-office-c' else ''
            out += [f'<figure{cls}><figcaption>{label}</figcaption><a href="{src}" target="_blank"><img src="{src}" alt="{title} {label}"></a><div class="links"><a href="{e(url,quote=True)}" target="_blank">{link_label}</a>{kind}</div></figure>']
        out += ['</div>', f'<p><strong>보여줄 개선:</strong> {improvement}</p>', f'<p class="note">남은 한계: {limitation}</p>']
        if (ARTIFACTS/image_roots[name]/f'{name}-geometry-0.png').exists():
            detail_src=f'{image_roots[name]}/{name}-geometry-0.png'
            out.append(f'<details open><summary>최종 결과 확대 · 형상 확인</summary><a href="{detail_src}" target="_blank"><img style="width:100%;max-height:560px;object-fit:contain" src="{detail_src}" alt="{title} 최종 결과 확대"></a><p class="note">비교 위의 두 결과는 동일 카메라입니다. 이 확대 화면은 최종 장면에 맞춘 카메라로, 격자만 숨겼습니다. 객체·형상·배치는 그대로입니다.</p><p>'+ ' · '.join(f'<a href="{image_roots[name]}/{name}-geometry-{i}.png" target="_blank">옆 각도 {i}</a>' for i in (1,2))+'</p></details>')
        out.append('</section>')
    out += [f'<details><summary>확정 프롬프트와 비교 조건</summary><pre>{e(PROMPT)}</pre><p>Qwen2.5-VL-7B-Instruct · SAM3 기본값 · SAM3D seed 42 · 공식 pose. 각 장면의 베이스라인과 최종 결과는 동일 입력 이미지, 동일 카메라·시선으로 캡처했습니다. 격자는 뷰어 기준 평면입니다.</p><p>선정 결과에 맞춰 프롬프트나 모델을 변경하거나 재생성하지 않았습니다. 발표 사례를 고른 것이며 전체 입력에 대한 성공률을 뜻하지 않습니다.</p></details>',
    '<footer><a href="assets/ram-qwen-filter-presentation/responses.json">추가 실행 응답 원문</a> · <a href="assets/ram-qwen-filter-new-scenes/presentation-selection.json">최종 선정 기록</a></footer></main></body></html>']
    document='\n'.join(out).replace('발표 최종 선정 · 식사 공간과 작업 공간','발표 최종 선정 · 대표 결과 3개').replace('비교 위의 두 결과는','위 비교의 두 결과는')
    (ARTIFACTS/'RAM_QWEN_FILTER_THREE_WAY.html').write_text(document,encoding='utf-8')
    selection = dict(version=METHOD,baseline=baseline,prompt=PROMPT,samples=[dict(sample=p[0],asset_root='artifacts/'+image_roots[p[0]],role=p[3],reason=p[4],limitation=p[6],result=records[p[0]][METHOD]) for p in PICKS],manual_geometry_edits=False)
    (ASSETS/'presentation-selection.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Final method: vision-furniture; scenes:', ', '.join(p[0] for p in PICKS))

if __name__ == '__main__':
    main()
