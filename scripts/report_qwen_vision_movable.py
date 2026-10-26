"""Add freshly reconstructed Qwen vision results to the four saved comparisons."""
import html, re, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapmaker.scene_run import ROOT, read, write, sha
from mapmaker.qwen_tags import MODEL, REVISION, MOVABLE_PROMPT, parse_tags
from scripts.run_qwen_movable import WORK, NAMES

ASSETS = ROOT/'docs/assets/ram-qwen-filter-vision-movable'

def manifest(partial=False):
    state=read(WORK/'comparison.json'); baseline=read(ROOT/'docs/assets/ram-qwen-filter-v1/scene-manifest.json')
    ASSETS.mkdir(exist_ok=True); records={}; viewers={}; evidence={}
    for name in NAMES:
        r=state['samples'][name]
        if partial and r['status']!='complete': continue
        assert r['status']=='complete', name
        run=Path(r['path']); m=read(run/'scene_metadata.json'); e=read(run/'logs/qwen_response.json')
        assert e['prompt']==MOVABLE_PROMPT and e['model']==MODEL and e['revision']==REVISION
        assert e['input_sha256']==r['source_input_sha256']==m['input_sha256']
        assert e['tags']==parse_tags(e['raw_response'])==m['object_extraction']['candidates']
        assert sha(run/'scene.glb')==r['scene_sha256']
        generated=sum(o['status']=='generated' for o in m['objects'])
        records[name]=dict(source_scene_sha256=baseline[name]['source_scene_sha256'],
            scene_sha256=r['scene_sha256'],objects_before=baseline[name]['objects_before'],
            objects_after=generated,masks=len(m['objects']),failed=len(m['objects'])-generated,
            tags=e['tags'],input_sha256=e['input_sha256'],path=r['path'])
        viewers[f'ram-filter-vision-movable-{name}-after']=r['path']
        evidence[name]=e
    write(ASSETS/'scene-manifest.json',records);write(ASSETS/'viewers.json',viewers)
    write(ASSETS/'results.json',evidence)

def report():
    from scripts.report_ram_filter_versions import main
    records=read(ASSETS/'scene-manifest.json')
    captures={c['sample']:c for c in read(ASSETS/'captures.json')}
    basecaps={c['sample']:c for c in read(ROOT/'docs/assets/ram-qwen-filter-v1/captures.json')}
    main(movable=True)
    path=ROOT/'docs/RAM_QWEN_FILTER_THREE_WAY.html'; doc=path.read_text(encoding='utf-8')
    mdpath=path.with_suffix('.md'); md=mdpath.read_text(encoding='utf-8')
    explanation=f'Qwen 비전 movable 추가 실험: {len(records)}/5장 완료. 원본 이미지에서 태그를 받고 SAM3·SAM3D를 새로 실행했다. 앞의 네 열은 기존 결과다. 모든 열의 카메라와 시선은 동일하다.'
    pending=[n for n in NAMES if n not in records]
    if pending: explanation+=' 실행 중 또는 대기: '+', '.join(pending)+'.'
    intro='<p>'+explanation+'</p><details><summary>Qwen 비전 movable 프롬프트</summary><pre>'+html.escape(MOVABLE_PROMPT)+'</pre></details>'
    doc=doc.replace('<nav>',intro+'<nav>',1)
    doc=re.sub(r'(<h1>.*?)(</h1>)',r'\1 · Qwen 비전 movable\2',doc,count=1)
    doc=re.sub(r'(<title>.*?)(</title>)',r'\1 · Qwen 비전 movable\2',doc,count=1)
    doc=doc.replace('동일 카메라 · 3D 재생성 없음','기존 네 열 합계 · 동일 카메라')
    doc=doc.replace('</style>','.five{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}@media(max-width:1400px){.five{min-width:1750px}}section{overflow-x:auto}</style>')
    md+='\n## Qwen 비전 movable · 5장 새 생성\n\n'+explanation+'\n\n```text\n'+MOVABLE_PROMPT+'\n```\n'
    for name,r in records.items():
        cap=captures[name]; ref=basecaps[name]
        assert cap['scene_sha256']==r['scene_sha256'] and not cap['errors']
        assert cap['camera']==ref['camera'] and cap['target']==ref['target']
        image=f'assets/ram-qwen-filter-vision-movable/{name}-after.png'
        assert (ROOT/'docs'/image).exists()
        link=f'http://127.0.0.1:8136/viewer?run=ram-filter-vision-movable-{name}-after'
        fig=f'<figure><figcaption>Qwen 비전 · movable · <b>{r["objects_after"]}개</b><a href="{link}" target="_blank">3D ↗</a></figcaption><a href="{image}" target="_blank"><img loading="lazy" src="{image}" alt="{name} Qwen vision movable"></a></figure>'
        pattern=rf'(<section id="{re.escape(name)}">)(.*?)(</section>)'
        match=re.search(pattern,doc,re.S); assert match
        body=match[2].replace('class="four"','class="five"',1)
        body=body.replace('개</span>',f' → {r["objects_after"]}개</span>',1)
        body=body.replace('</div>',fig+'</div>',1)
        body+=f'<p><strong>Qwen 비전 반환 태그:</strong> {html.escape(", ".join(r["tags"]))}<br>마스크 {r["masks"]}개 / 생성 성공 {r["objects_after"]}개 / 실패 {r["failed"]}개</p>'
        doc=doc[:match.start()]+match[1]+body+match[3]+doc[match.end():]
        images=[f'assets/ram-qwen-filter-v1/{name}-before.png']+[f'assets/ram-qwen-filter-{v}/{name}-after.png' for v in ('v1','v2','movable')]+[image]
        md+=f'\n### {name}\n\n| RAM++ | v1 | v2 | movable 텍스트 | movable 비전 |\n|---|---|---|---|---|\n| '+' | '.join(f'![{name}]({i})' for i in images)+' |\n\n'
        md+=f'[비전 3D]({link}) · 태그: '+', '.join(r['tags'])+f' · 마스크 {r["masks"]}, 성공 {r["objects_after"]}, 실패 {r["failed"]}\n'
    md+='\n[비전 원문 응답](assets/ram-qwen-filter-vision-movable/results.json) · [생성 기록](assets/ram-qwen-filter-vision-movable/scene-manifest.json)\n'
    path.write_text(doc,encoding='utf-8');mdpath.write_text(md,encoding='utf-8')
    print(f'Added {len(records)} verified vision results to existing comparison')

if __name__=='__main__':
    manifest(partial='--partial' in sys.argv) if '--manifest' in sys.argv else report()
