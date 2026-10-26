"""Publish baseline / v1 / v2 comparison using verified saved scenes."""
from pathlib import Path
import html
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mapmaker.scene_run import read, sha
from mapmaker.qwen_background_filter import parse_response


def main():
    a1 = ROOT / 'docs/assets/ram-qwen-filter-v1'
    a2 = ROOT / 'docs/assets/ram-qwen-filter-v2'
    results = [read(p/'results.json') for p in (a1, a2)]
    manifests = [read(p/'scene-manifest.json') for p in (a1, a2)]
    captures = [{r['sample']:r for r in read(p/'captures.json')} for p in (a1,a2)]
    assert all(len(r['samples']) == 10 for r in results)
    for key in ('model','revision','generation','dtype','image_input','transformers','torch'):
        assert results[0][key] == results[1][key], key
    for path, result in zip((a1,a2),results):
        batch = read(path/'inputs.json')
        assert sha(path/'inputs.json') == result['source_sha256']
        for source, item in zip(batch['samples'], result['samples']):
            assert all(item[k] == v for k,v in source.items())
            assert item['status'] == 'complete'
            assert item['prompt'] == result['prompt_template'].format(ram_tags=json.dumps(item['raw_tags'],ensure_ascii=False))
            assert item['kept_tags'] == parse_response(item['raw_response'], item['raw_tags'])
    lines = ['# RAM++ 기본값 · Qwen 필터 v1 · Qwen 필터 v2', '',
             '기존 1번의 같은 태그 목록 10개에 텍스트 Qwen 필터를 적용했다. SAM3·SAM3D 재추론 없이, 기존 객체 중 제외 태그에 대응하는 객체만 제거해 장면을 재조립했다. 남은 메시·텍스처·배치 행렬은 보존했다.', '',
             f"모델: `{results[0]['model']}` / revision `{results[0]['revision']}`. BF16, greedy, seed 42, 최대 2048 새 토큰, 이미지 입력 없음.", '',
             f"추론 GPU: v1 `{results[0]['gpu']}`, v2 `{results[1]['gpu']}`. 모델·소프트웨어·디코딩 설정은 같고 GPU는 다르다.", '',
             '세 열의 카메라 위치와 시선은 동일하다. 원본·v1 캡처는 기존 검증 결과를 재사용했다. 격자는 뷰어 보조선이며 크기가 달라질 수 있다.', '',
             '[나란히 비교 화면](http://127.0.0.1:8135/docs/RAM_QWEN_FILTER_THREE_WAY.html)', '',
             '## v1 프롬프트', '', '```text', results[0]['prompt_template'], '```', '',
             '## v2 프롬프트', '', '```text', results[1]['prompt_template'], '```', '',
             '## 객체 수', '', '| 입력 | 기존 1번 | v1 | v2 |', '|---|---:|---:|---:|']
    sections = []
    total = [0,0,0]
    detail_lines = []
    for r1,r2 in zip(results[0]['samples'], results[1]['samples']):
        name=r1['sample']; assert name == r2['sample']
        assert r1['raw_tags'] == r2['raw_tags']
        m1,m2=[m[name] for m in manifests]
        assert m1['source_scene_sha256'] == m2['source_scene_sha256']
        for ledger,manifest in zip(captures,(m1,m2)):
            assert ledger[name]['scene_sha256'] == manifest['scene_sha256']
            assert not ledger[name]['errors']
        for key in ('camera','target'):
            assert captures[0][name][key] == captures[1][name][key], (name,key)
        counts=[m1['objects_before'],m1['objects_after'],m2['objects_after']]
        total=[a+b for a,b in zip(total,counts)]
        lines.append(f'| {name} | '+ ' | '.join(map(str,counts))+' |')
        images=[f'assets/ram-qwen-filter-v1/{name}-before.png',f'assets/ram-qwen-filter-v1/{name}-after.png',f'assets/ram-qwen-filter-v2/{name}-after.png']
        aliases=[f'ram-filter-{name}-before',f'ram-filter-{name}-after',f'ram-filter-v2-{name}-after']
        titles=['기존 1번 RAM++','직전 v1','이번 v2 · 배경 예시 추가']
        figures=[]; cells=[]
        for title,count,img,alias in zip(titles,counts,images,aliases):
            assert (ROOT/'docs'/img).is_file()
            url=f'http://127.0.0.1:8135/viewer?run={alias}'
            figures.append(f'<figure><figcaption>{title} · <b>{count}개</b><a href="{url}" target="_blank">3D ↗</a></figcaption><a href="{img}" target="_blank"><img loading="lazy" src="{img}" alt="{name} {title}"></a></figure>')
            cells.append(f'![{title}]({img})<br>[3D 뷰어]({url})')
        removed1=', '.join(r1['removed_tags']) or '없음'; removed2=', '.join(r2['removed_tags']) or '없음'
        sections.append(f'<section id="{name}"><h2>{name} <span>{counts[0]} → {counts[1]} → {counts[2]}개</span></h2><div class="triple">'+''.join(figures)+f'</div><p><strong>v1 제외:</strong> {html.escape(removed1)}<br><strong>v2 제외:</strong> {html.escape(removed2)}</p></section>')
        detail_lines += ['', f'## {name}', '', '| 기존 1번 | 직전 v1 | 이번 v2 |', '|---|---|---|', '| '+' | '.join(cells)+' |', '',f'v1 제외: {removed1}', '',f'v2 제외: {removed2}', '']
    lines.append('| 합계 | '+' | '.join(map(str,total))+' |')
    lines += detail_lines
    lines += ['', '[v1 원문 응답](assets/ram-qwen-filter-v1/results.json) · [v2 원문 응답](assets/ram-qwen-filter-v2/results.json) · [v2 적용 검증](assets/ram-qwen-filter-v2/scene-manifest.json)', '']
    (ROOT/'docs/RAM_QWEN_FILTER_THREE_WAY.md').write_text('\n'.join(lines),encoding='utf-8')
    document='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>기존 1번 · Qwen v1 · Qwen v2</title>
<style>body{margin:0;background:#101722;color:#e6edf5;font:16px/1.6 system-ui,sans-serif}main{max-width:1900px;margin:auto;padding:28px}h1{font-size:30px}h2 span{color:#82d7cb;font-size:20px;margin-left:16px}a{color:#91caff}nav{display:flex;gap:16px;flex-wrap:wrap}section{margin:36px 0;padding-top:10px;border-top:1px solid #354152}.triple{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}figure{margin:0;background:#182231;border-radius:10px;overflow:hidden}figcaption{padding:12px;font-size:15px}figcaption a{float:right}img{display:block;width:100%}p{color:#b5c2d4}pre{white-space:pre-wrap;background:#182231;padding:16px;border-radius:8px}details{margin:16px 0}summary{cursor:pointer}@media(max-width:800px){.triple{min-width:1050px}section{overflow:auto}main{padding:16px}}</style><main>'''
    document+=f'<h1>기존 1번 · Qwen 필터 v1 · Qwen 필터 v2</h1><p>기존 10장 결과 적용 · 전체 객체 {total[0]} → {total[1]} → {total[2]}개 · 3D 재생성 없음</p><p>같은 카메라 위치·시선입니다. 이미지를 누르면 크게 볼 수 있고, 각 열의 3D 링크에서 직접 돌려볼 수 있습니다.</p>'
    for index,result in enumerate(results,1):
        document+=f'<details><summary>v{index} 프롬프트 보기</summary><pre>{html.escape(result["prompt_template"])}</pre></details>'
    document+='<nav>'+''.join(f'<a href="#{n}">{n}</a>' for n in manifests[0])+'</nav>'+''.join(sections)+'</main></html>'
    (ROOT/'docs/RAM_QWEN_FILTER_THREE_WAY.html').write_text(document,encoding='utf-8')
    print('objects:',total)


if __name__=='__main__':
    main()
