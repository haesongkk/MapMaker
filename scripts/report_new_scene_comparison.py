"""Append six preselected scenes without disturbing the earlier five rows."""
import html,json,re,sys
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapmaker.scene_run import ROOT,read,write,sha
from scripts.run_new_scene_comparison import WORK,ASSETS,TEXT_VERSIONS
VERSIONS=[('baseline','RAM++ 기본값'),('v1','텍스트 · 배경 제거'),('v2','텍스트 · 배경 예시'),
          ('movable','텍스트 · movable'),('vision-movable','비전 · movable'),
          ('furniture','텍스트 · furniture'),('vision-furniture','비전 · furniture')]

def manifest():
    state=read(WORK/'comparison.json');records={};viewers={};responses={}
    for name,versions in state['samples'].items():
        records[name]={};responses[name]={}
        for version,_ in VERSIONS:
            if version in TEXT_VERSIONS:
                p=ROOT/f'docs/assets/ram-qwen-filter-new-{version}/scene-manifest.json'
                d=read(p).get(name) if p.exists() else None
                if not d:continue
                folder=ROOT/d['target_run'];tags=d['kept_tags']
                evidence=read(ROOT/f'docs/assets/ram-qwen-filter-new-{version}/results.json')
                responses[name][version]=dict(model=evidence['model'],revision=evidence['revision'],
                    generation=evidence['generation'],response=next(x for x in evidence['samples'] if x['sample']==name))
            else:
                r=versions.get(version,{})
                if r.get('status')!='complete':continue
                folder=Path(r['path']);e=read(folder/'object_candidates.json');tags=e['candidates']
                responses[name][version]=e if version=='baseline' else read(folder/'logs/qwen_response.json')
            m=read(folder/'scene_metadata.json');count=sum(o['status']=='generated' for o in m['objects'])
            alias=f'new-comparison-{name}-{version}'
            records[name][version]=dict(path=folder.as_posix(),scene_sha256=sha(folder/'scene.glb'),input_sha256=m['input_sha256'],
                tags=tags,masks=len(m['objects']),objects=count,failed=len(m['objects'])-count,alias=alias,
                mask_counts=dict(Counter(o['name'] for o in m['objects'])),
                unmatched_tags=[t for t in tags if t not in {o['name'] for o in m['objects']}])
            viewers[alias]=folder.relative_to(ROOT).as_posix()
    write(ASSETS/'scene-manifest.json',records);write(ASSETS/'viewers.json',viewers);write(ASSETS/'responses.json',responses)
    return records

def report():
    records=manifest();selection=read(ASSETS/'selection.json');state=read(WORK/'comparison.json')
    assert sha(ASSETS/'selection.json')==state['selection_sha256'],'Selection changed after inference started'
    caps=read(ASSETS/'captures.json') if (ASSETS/'captures.json').exists() else []
    caps={(c['sample'],c['version']):c for c in caps}
    quality=json.loads((ASSETS/'quality-review.json').read_text(encoding='utf-8')) if (ASSETS/'quality-review.json').exists() else {}
    out=['<!-- NEW_SCENES_START -->','<div id="new-scenes"><h1>새 선정 사진 6장 · 동일한 7개 버전</h1>',
         '<p>주요 가구의 누락·중복·형상·배치 중심으로 선정했습니다. 결과를 보고 사진을 바꾸지 않습니다. 기존 5장은 위에 유지합니다.</p>',
         '<p><a href="NEW_SCENE_SELECTION.md">실행 전 선정 기록</a> · <a href="assets/ram-qwen-filter-new-scenes/selection.json">입력·출처·해시</a> · <a href="assets/ram-qwen-filter-new-scenes/responses.json">새 6장의 원문 응답·실행 기록</a></p>',
         '<p>동일 이미지 · 동일 프롬프트/모델 · SAM3 기본값과 모든 마스크 · seed 42 · 공식 pose. 텍스트 4종은 RAM++ 원본의 객체와 배치를 재사용하며, 비전 2종은 각각 새로 생성합니다.</p>',
         '<p>스크린샷은 각 사진의 RAM++ 기준 카메라를 일곱 버전에 동일하게 적용합니다. 생성 객체 수는 품질 점수가 아닙니다.</p>',
         '<p>격자는 뷰어의 기준 평면이며 복원한 바닥이 아닙니다. 각 화면을 클릭하면 크게 볼 수 있고, 3D 링크에서 회전·확대할 수 있습니다.</p>',
         '<nav>'+ ' '.join(f'<a href="#{s["sample"]}">{html.escape(s["label"])}</a>' for s in selection['samples'])+'</nav>']
    md=['<!-- NEW_SCENES_START -->','\n# 새 선정 사진 6장 · 동일한 7개 버전','',
        '[실행 전 선정 기록](NEW_SCENE_SELECTION.md). 결과에 따른 사진 교체 없음. 텍스트는 원본 객체 재사용, 비전은 새 생성.','']
    if len(quality)==6 and sum(len(v) for v in records.values())==42:
        conclusion='전체 42개 결과 완료. 식사 공간의 비전 두 버전이 주요 가구 보존·배치에서 상대적으로 가장 좋았다. 독서 코너는 텍스트 배경 제거 v1, 야외 좌석은 비전에서 주요 가구를 읽기 좋지만 각각 형상·추가 객체 문제가 남는다. 거실·침실은 주요 가구 누락으로 좋은 결과라고 보기 어렵다. 가구 전체가 분리되어 보이는 사진을 우선하되, 태그 중복과 마스크 0개 여부까지 확인해야 한다. 이번 6장은 성공률 추정용 무작위 표본이 아니다.'
        out.append('<p><strong>실행 후 판단:</strong> '+html.escape(conclusion)+'</p>')
        md += [conclusion,'']
    for item in selection['samples']:
        name=item['sample'];out += [f'<section id="{name}"><h2>{html.escape(item["label"])} · {name}</h2>',
            f'<img style="max-width:600px;max-height:380px;object-fit:contain" src="assets/ram-qwen-filter-new-scenes/{name}-input.png" alt="{name} 원본">',
            f'<p><a href="{html.escape(item["source_url"],quote=True)}" target="_blank">원본 출처</a> · {html.escape(item["image_kind"])}</p>',
            '<p><strong>주요 가구:</strong> '+html.escape(', '.join(item['expected_major_objects']))+'</p>',
            '<p><strong>선정 이유:</strong> '+html.escape(item['selection_reason'])+'<br><strong>남은 위험:</strong> '+html.escape(item['remaining_risk'])+'</p>',
            '<div class="seven">']
        md += [f'## {item["label"]} · {name}','',f'![원본](assets/ram-qwen-filter-new-scenes/{name}-input.png)','']
        for version,title in VERSIONS:
            r=records[name].get(version);cap=caps.get((name,version));ready=bool(r and cap and cap['scene_sha256']==r['scene_sha256'] and not cap['errors'])
            out.append('<figure><figcaption>'+title)
            if r:
                out.append(f' · <b>{r["objects"]}개</b> <a href="http://127.0.0.1:8136/viewer?run={r["alias"]}" target="_blank">3D ↗</a>')
            out.append('</figcaption>')
            if ready:
                path=f'assets/ram-qwen-filter-new-scenes/{name}-{version}.png'
                out.append(f'<a href="{path}" target="_blank"><img loading="lazy" src="{path}" alt="{name} {title}"></a>')
                md += [f'### {title}',f'![{title}]({path})','',f'객체 {r["objects"]}개 · 태그: '+', '.join(r['tags']),'']
            else:
                status=state['samples'][name].get(version,{}).get('status','waiting')
                out.append(f'<p style="padding:65px 12px">'+('생성 완료 · 화면 준비 중' if r else '실행 상태: '+html.escape(status))+'</p>')
            if r:out.append('<p style="font-size:12px">'+html.escape(', '.join(r['tags']))+'</p>')
            if r and version.startswith('vision-') and r['unmatched_tags']:
                out.append('<p style="font-size:12px;color:#ffc78a">태그 반환 후 마스크 0개: '+html.escape(', '.join(r['unmatched_tags']))+'</p>')
            out.append('</figure>')
        out.append('</div>')
        if name in quality:
            out.append('<p><strong>결과 검토:</strong> '+html.escape(quality[name])+'</p>');md += ['결과 검토: '+quality[name],'']
        out.append('</section>')
    out += ['</div>','<!-- NEW_SCENES_END -->'];md += ['<!-- NEW_SCENES_END -->']
    path=ROOT/'docs/RAM_QWEN_FILTER_THREE_WAY.html';doc=path.read_text(encoding='utf-8')
    doc=re.sub(r'<!-- NEW_SCENES_START -->.*?<!-- NEW_SCENES_END -->','',doc,flags=re.S)
    block='\n'.join(out)
    doc=doc.replace('</body>',block+'\n</body>') if '</body>' in doc else doc+'\n'+block
    if 'href="#new-scenes"' not in doc:doc=doc.replace('<nav>','<p><a href="#new-scenes">새 사진 6장 비교로 이동 ↓</a></p><nav>',1)
    path.write_text(doc,encoding='utf-8')
    path=path.with_suffix('.md');old=path.read_text(encoding='utf-8')
    old=re.sub(r'<!-- NEW_SCENES_START -->.*?<!-- NEW_SCENES_END -->','',old,flags=re.S)
    path.write_text(old+'\n'+'\n'.join(md),encoding='utf-8')
    print('New scene rows updated',sum(len(v) for v in records.values()),'/42 generated scenes')

if __name__=='__main__':report()
