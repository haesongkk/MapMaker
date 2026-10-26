"""Append the two furniture experiments while retaining all earlier comparisons."""
import html,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapmaker.scene_run import ROOT,read,write,sha
from mapmaker.qwen_tags import FURNITURE_PROMPT,MODEL,REVISION,parse_tags
from mapmaker.qwen_background_filter import parse_response
from scripts.run_qwen_furniture import WORK,TEXT_PROMPT,ASSETS as TEXT_ASSETS
NAMES=('house','office','sample-01','sample-02','sample-04')
ASSETS=ROOT/'docs/assets/ram-qwen-filter-vision-furniture'

def manifest(partial=False):
    state=read(WORK/'comparison.json'); baseline=read(ROOT/'docs/assets/ram-qwen-filter-v1/scene-manifest.json')
    ASSETS.mkdir(exist_ok=True); records={}; viewers={}; evidence={}
    for name in NAMES:
        r=state['samples'][name]
        if partial and r['status']!='complete':continue
        assert r['status']=='complete',name
        run=Path(r['path']);m=read(run/'scene_metadata.json');e=read(run/'logs/qwen_response.json')
        assert e['prompt']==FURNITURE_PROMPT and e['model']==MODEL and e['revision']==REVISION
        assert e['input_sha256']==r['source_input_sha256']==m['input_sha256']
        assert e['tags']==parse_tags(e['raw_response'])==m['object_extraction']['candidates']
        assert sha(run/'scene.glb')==r['scene_sha256']
        count=sum(o['status']=='generated' for o in m['objects'])
        records[name]=dict(source_scene_sha256=baseline[name]['source_scene_sha256'],scene_sha256=r['scene_sha256'],
            objects_before=baseline[name]['objects_before'],objects_after=count,masks=len(m['objects']),
            failed=len(m['objects'])-count,tags=e['tags'],input_sha256=e['input_sha256'],path=r['path'])
        viewers[f'ram-filter-vision-furniture-{name}-after']=r['path']; evidence[name]=e
    write(ASSETS/'scene-manifest.json',records);write(ASSETS/'viewers.json',viewers);write(ASSETS/'results.json',evidence)

def report():
    import scripts.report_qwen_vision_movable as previous
    # Its imported runner may already be configured for this new experiment.
    previous.WORK=ROOT/'.runtime/qwen-vision-movable'
    previous.report()
    path=ROOT/'docs/RAM_QWEN_FILTER_THREE_WAY.html';doc=path.read_text(encoding='utf-8')
    mdpath=path.with_suffix('.md');md=mdpath.read_text(encoding='utf-8')
    versions=[('furniture',TEXT_ASSETS,TEXT_PROMPT,'Qwen 텍스트 · furniture'),('vision-furniture',ASSETS,FURNITURE_PROMPT,'Qwen 비전 · furniture')]
    baseline={c['sample']:c for c in read(ROOT/'docs/assets/ram-qwen-filter-v1/captures.json')}
    summary=[]
    for version,folder,prompt,title in versions:
        records=read(folder/'scene-manifest.json') if (folder/'scene-manifest.json').exists() else {}
        caps={c['sample']:c for c in read(folder/'captures.json')} if (folder/'captures.json').exists() else {}
        ready={n:r for n,r in records.items() if n in caps and caps[n]['scene_sha256']==r['scene_sha256']}
        summary.append(f'{title}: {len(ready)}/5장 반영')
        evidence_link=f'assets/ram-qwen-filter-{version}/results.json'
        doc=doc.replace('<nav>',f'<details><summary>{title} 프롬프트</summary><pre>{html.escape(prompt)}</pre><a href="{evidence_link}">원문 응답과 실행 기록</a></details><nav>',1)
        md+=f'\n## {title}\n\n```text\n{prompt}\n```\n\n[원문 응답과 실행 기록]({evidence_link})\n'
        text_results={r['sample']:r for r in read(folder/'results.json')['samples']} if version=='furniture' and ready else {}
        for name,r in ready.items():
            cap=caps[name];ref=baseline[name]
            assert not cap['errors'] and cap['camera']==ref['camera'] and cap['target']==ref['target']
            assert cap['source_scene_sha256']==r['source_scene_sha256']
            tags=r['tags'] if version=='vision-furniture' else text_results[name]['kept_tags']
            if version=='furniture':
                t=text_results[name]; assert tags==parse_response(t['raw_response'],t['raw_tags'],allow_trailing_explanation=True)
            image=f'assets/ram-qwen-filter-{version}/{name}-after.png'
            link=f'http://127.0.0.1:8136/viewer?run=ram-filter-{version}-{name}-after'
            fig=f'<figure><figcaption>{title} · <b>{r["objects_after"]}개</b><a href="{link}" target="_blank">3D ↗</a></figcaption><a href="{image}" target="_blank"><img loading="lazy" src="{image}" alt="{name} {title}"></a></figure>'
            match=re.search(rf'(<section id="{re.escape(name)}">)(.*?)(</section>)',doc,re.S);assert match
            body=match[2].replace('</div>',fig+'</div>',1).replace('개</span>',f' → {r["objects_after"]}개</span>',1)
            count=body.count('<figure>');body=re.sub(r'class="(?:five|six|seven)"',f'class="{"seven" if count==7 else "six"}"',body,count=1)
            body+=f'<p><strong>{title} 태그:</strong> {html.escape(", ".join(tags))}</p>'
            doc=doc[:match.start()]+match[1]+body+match[3]+doc[match.end():]
            md+=f'\n### {name}\n\n![{title}]({image})\n\n[3D]({link}) · 생성 객체 {r["objects_after"]}개\n\n태그: '+', '.join(tags)+'\n'
    info=' / '.join(summary)+' · 텍스트 필터는 기존 객체·배치 재사용, 비전은 SAM3·SAM3D 새 생성.'
    doc=doc.replace('<nav>','<p>'+info+'</p><nav>',1)
    doc=doc.replace('</style>','.six,.seven{display:grid;gap:10px}.six{grid-template-columns:repeat(6,minmax(0,1fr));min-width:1800px}.seven{grid-template-columns:repeat(7,minmax(0,1fr));min-width:2100px}</style>')
    doc=re.sub(r'(<h1>.*?)(</h1>)',r'\1 · furniture 비교\2',doc,count=1)
    path.write_text(doc,encoding='utf-8');mdpath.write_text(md+'\n'+info+'\n',encoding='utf-8')
    print(info)

if __name__=='__main__':
    manifest(partial='--partial' in sys.argv) if '--manifest' in sys.argv else report()
