"""Compare original RAM++ scenes and positive/negative prompt experiments."""
import html
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from mapmaker.scene_run import read,sha
from mapmaker.qwen_background_filter import parse_response


def main(movable=False):
    selected=('house','office','sample-01','sample-02','sample-04') if movable else None
    last='movable' if movable else 'v3'
    last_label='movable · 움직이는 물건' if movable else 'v3 · 객체 유지'
    basename='RAM_QWEN_FILTER_THREE_WAY' if movable else 'RAM_QWEN_FILTER_VERSIONS'
    versions=['v1','v2',last]
    folders=[ROOT/f'docs/assets/ram-qwen-filter-{v}' for v in versions]
    results=[read(p/'results.json') for p in folders]
    manifests=[read(p/'scene-manifest.json') for p in folders]
    captures=[{c['sample']:c for c in read(p/'captures.json')} for p in folders]
    for folder,result in zip(folders,results):
        inputs=read(folder/'inputs.json')
        assert result['source_sha256']==sha(folder/'inputs.json')
        assert len(result['samples'])==10
        for key in ('model','revision','generation','dtype','image_input','transformers','torch'):
            assert result[key]==results[0][key],key
        for original,item in zip(inputs['samples'],result['samples']):
            assert all(item[k]==v for k,v in original.items())
            assert item['status']=='complete'
            assert item['kept_tags']==parse_response(item['raw_response'],item['raw_tags'],allow_trailing_explanation=True)
            assert item['prompt']==result['prompt_template'].format(ram_tags=json.dumps(item['raw_tags'],ensure_ascii=False))
    definition='v3는 개별 물체로 분할하고 별도 3D 객체로 만들 수 있는 구체적인 물건·설비를 남긴다. 가구·가전·전자기기·조명·팬·러그·커튼·장식품·문·창문을 예시로 제시한다.'
    if movable:
        definition='이번 프롬프트는 “움직일 수 있는 물건의 태그만 남겨라”이며, 예시나 추가 분류 기준을 넣지 않았다.'
    caveat='태그 이름만으로 판단한다. 실제 이미지에서의 존재나 마스크 품질을 검증하는 단계는 아니다. 기존 객체 파일과 배치 행렬을 재사용하며, SAM3·SAM3D 재추론은 하지 않았다.'
    url=f'http://127.0.0.1:8135/docs/{basename}.html' if movable else f'http://127.0.0.1:8136/docs/{basename}.html'
    heading=f'RAM++ 기본값 · Qwen v1 · v2 · {last_label}'
    lines=['# '+heading,'',definition,'',caveat,'',
           f'[네 버전 나란히 보기]({url})','',
           f"모델 `{results[0]['model']}`, revision `{results[0]['revision']}`. BF16·greedy·seed 42. 소프트웨어와 모델 설정은 동일하다. GPU: "+', '.join(f"{v}: {r['gpu']}" for v,r in zip(versions,results)), '',
           '카메라 위치와 시선은 네 열에서 동일하다. 격자는 뷰어 보조선으로 장면 크기에 따라 범위·간격이 달라질 수 있다.','']
    prompts=''
    for version,result in zip(versions,results):
        lines += [f'## {version} 프롬프트','','```text',result['prompt_template'],'```','']
        prompts+=f'<details><summary>{version} 프롬프트</summary><pre>{html.escape(result["prompt_template"])}</pre></details>'
    lines+=['## 객체 수','',f'| 샘플 | 기존 1번 | v1 배경 제거 | v2 배경 예시 | {last_label} |','|---|---:|---:|---:|---:|']
    totals=[0]*4;sections=[];details=[]
    for items in zip(*(r['samples'] for r in results)):
        name=items[0]['sample']
        if selected is not None and name not in selected:
            continue
        assert all(x['sample']==name and x['raw_tags']==items[0]['raw_tags'] for x in items)
        scenes=[m[name] for m in manifests];caps=[c[name] for c in captures]
        for scene,cap in zip(scenes,caps):
            assert scene['source_scene_sha256']==scenes[0]['source_scene_sha256']
            assert cap['scene_sha256']==scene['scene_sha256'] and not cap['errors']
            assert cap['camera']==caps[0]['camera'] and cap['target']==caps[0]['target']
        counts=[scenes[0]['objects_before']]+[s['objects_after'] for s in scenes]
        totals=[a+b for a,b in zip(totals,counts)]
        lines.append('| '+name+' | '+' | '.join(map(str,counts))+' |')
        images=[f'assets/ram-qwen-filter-v1/{name}-before.png']+[f'assets/ram-qwen-filter-{v}/{name}-after.png' for v in versions]
        aliases=[f'ram-filter-{name}-before',f'ram-filter-{name}-after',f'ram-filter-v2-{name}-after',f'ram-filter-{last}-{name}-after']
        titles=['기존 1번 RAM++','v1 · 배경 제거','v2 · 배경 예시',last_label]
        figures=[];cells=[]
        for title,count,image,alias in zip(titles,counts,images,aliases):
            assert (ROOT/'docs'/image).is_file()
            link=f'http://127.0.0.1:8136/viewer?run={alias}'
            figures.append(f'<figure><figcaption>{title} · <b>{count}개</b><a href="{link}" target="_blank">3D ↗</a></figcaption><a href="{image}" target="_blank"><img loading="lazy" src="{image}" alt="{name} {title}"></a></figure>')
            cells.append(f'![{title}]({image})<br>[3D]({link})')
        kept=', '.join(items[2]['kept_tags']);removed=', '.join(items[2]['removed_tags']) or '없음'
        sections.append(f'<section id="{name}"><h2>{name} <span>'+ ' → '.join(map(str,counts))+'개</span></h2><div class="four">'+''.join(figures)+f'</div><p><strong>{last} 유지:</strong> {html.escape(kept)}<br><strong>{last} 제외:</strong> {html.escape(removed)}</p></section>')
        details += ['',f'## {name}','',f'| 기존 1번 | v1 | v2 | {last} |','|---|---|---|---|','| '+' | '.join(cells)+' |','',f'{last} 유지: {kept}','',f'{last} 제외: {removed}','']
    lines.append('| 합계 | '+' | '.join(map(str,totals))+' |')
    lines+=details+['',f'[{last} 원문 응답](assets/ram-qwen-filter-{last}/results.json) · [객체 적용 기록](assets/ram-qwen-filter-{last}/scene-manifest.json)','']
    if movable:
        lines+=['남은 태그에 기존 생성 객체가 없으면 0개 장면이 된다. [최초 실행 기록](assets/ram-qwen-filter-movable/raw-results.json)','']
    (ROOT/f'docs/{basename}.md').write_text('\n'.join(lines),encoding='utf-8')
    document='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RAM++ · Qwen v1 · v2 · v3</title><style>body{margin:0;background:#101722;color:#e6edf5;font:16px/1.6 system-ui,sans-serif}main{max-width:2200px;margin:auto;padding:28px}h1{font-size:28px}h2 span{color:#82d7cb;font-size:20px;margin-left:16px}a{color:#91caff}nav{display:flex;gap:16px;flex-wrap:wrap}section{margin:36px 0;padding-top:10px;border-top:1px solid #354152}.four{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}figure{margin:0;background:#182231;border-radius:10px;overflow:hidden}figcaption{padding:10px;font-size:14px}figcaption a{float:right}img{display:block;width:100%}p{color:#b5c2d4}pre{white-space:pre-wrap;background:#182231;padding:16px;border-radius:8px}details{margin:12px 0}summary{cursor:pointer}@media(max-width:1000px){.four{min-width:1400px}section{overflow:auto}main{padding:16px}}</style><main>'''
    document=document.replace('RAM++ · Qwen v1 · v2 · v3',heading)
    document+='<h1>'+heading+'</h1><p>전체 객체 '+' → '.join(map(str,totals))+'개 · 동일 카메라 · 3D 재생성 없음</p><p>'+definition+'</p><p>'+caveat+'</p>'+prompts
    document+='<nav>'+''.join(f'<a href="#{n}">{n}</a>' for n in (selected or manifests[0]))+'</nav>'+''.join(sections)+'</main></html>'
    (ROOT/f'docs/{basename}.html').write_text(document,encoding='utf-8')
    print('objects:',totals)


if __name__=='__main__':main(movable='--movable' in sys.argv)
