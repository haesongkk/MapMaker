import sys,html,json
from pathlib import Path
from collections import Counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapmaker.scene_run import ROOT,read,write,sha
from scripts.run_complex_candidates import WORK,ASSETS
def main():
 state=read(WORK/'comparison.json');selection=read(ASSETS/'selection.json');records={};viewers={};responses={}
 assert sha(ASSETS/'selection.json')==state['selection_sha256']
 for name,vs in state['samples'].items():
  records[name]={};responses[name]={}
  for version,r in vs.items():
   if r['status']!='complete':continue
   path=Path(r['path']);m=read(path/'scene_metadata.json');e=read(path/'object_candidates.json')
   responses[name][version]=read(path/'logs/qwen_response.json') if version=='vision-furniture' else e
   alias=f'presentation-{name}-{version}'
   records[name][version]=dict(path=path.as_posix(),scene_sha256=sha(path/'scene.glb'),input_sha256=m['input_sha256'],tags=e['candidates'],objects=sum(o['status']=='generated' for o in m['objects']),mask_counts=dict(Counter(o['name'] for o in m['objects'])),alias=alias)
   viewers[alias]=path.relative_to(ROOT).as_posix()
 write(ASSETS/'scene-manifest.json',records);write(ASSETS/'viewers.json',viewers);write(ASSETS/'responses.json',responses)
 out=['<!doctype html><html lang="ko"><meta charset="utf-8"><title>추가 발표 후보 검토</title><style>body{background:#101722;color:#e6edf5;font:16px/1.6 system-ui;margin:32px}a{color:#9ddfd5}.row{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}img{width:100%;height:380px;object-fit:contain}section{border-top:1px solid #526;padding:24px 0}figure{margin:0}p{max-width:1200px}</style><h1>추가 발표 후보 · 베이스라인 / 비전 furniture</h1><p>형상 검토 후 채택 여부 결정. 미채택 결과도 보존. 모델·프롬프트·배치 수정 없음.</p>']
 for item in selection['samples']:
  name=item['sample'];original=Path(item['input_path']).name
  out += [f'<section id="{name}"><h2>{html.escape(item["label"])}</h2><p>{html.escape(item["selection_reason"])}</p><div class="row"><figure><figcaption>원본</figcaption><img src="assets/ram-qwen-filter-complex/{original}"></figure>']
  for v in ('baseline','vision-furniture'):
   r=records[name].get(v);out.append(f'<figure><figcaption>{v}</figcaption>')
   if r:
    filename=f'{name}-{v}-clean.png' if (ASSETS/f'{name}-{v}-clean.png').exists() else f'{name}-{v}.png'
    if (ASSETS/filename).exists():out.append(f'<img src="assets/ram-qwen-filter-complex/{filename}">')
    out.append(f'<a href="http://127.0.0.1:8136/viewer?run={r["alias"]}">3D 열기</a><p>{html.escape(str(r["mask_counts"]))}</p>')
   else:out.append('<p>생성 중</p>')
   out.append('</figure>')
  out.append('</div>')
  quality_file=ASSETS/'quality-review.json'
  quality=json.loads(quality_file.read_text(encoding='utf-8')) if quality_file.exists() else {}
  if name in quality:
   q=quality[name];out.append('<p><strong>'+html.escape(q['decision'])+'</strong> · '+html.escape(q['evidence'])+'</p><p>'+html.escape(q['limitations'])+'</p>')
  if (ASSETS/f'{name}-geometry-0.png').exists():
   out.append('<details><summary>형상 점검 · 세 각도</summary><div class="row">'+''.join(f'<img src="assets/ram-qwen-filter-complex/{name}-geometry-{i}.png">' for i in range(3))+'</div></details>')
  out.append('</section>')
 out.append('</html>');(ROOT/'docs/COMPLEX_CANDIDATES.html').write_text('\n'.join(out),encoding='utf-8')
 print('Candidate scenes collected:',sum(map(len,records.values())),'/4')
if __name__=='__main__':main()
