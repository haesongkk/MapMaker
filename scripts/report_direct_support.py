"""Render the saved pilot, including its failures; never relabel inference output."""
import html,json,sys,hashlib
from pathlib import Path

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def esc(v):return html.escape(str(v))

root=Path(sys.argv[1]).resolve()
evaluation=read(root/'preliminary-evaluation.json')
parts=['''<!doctype html><meta charset="utf-8"><title>Direct support placement pilot</title>
<style>body{margin:32px;background:#14202c;color:#eee;font:16px/1.6 sans-serif}h1{margin-bottom:8px}
.notice{background:#573625;padding:16px;border-radius:8px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}img{width:100%}table{border-collapse:collapse;width:100%;margin:20px 0}td,th{border:1px solid #52606b;padding:8px;text-align:left}a{color:#9bddff}.bad{background:#542b2b}summary{cursor:pointer}pre{white-space:pre-wrap}</style>
<h1>직접 받침 관계 → 배치 보정 실험</h1><p class="notice">사람 검증 전 에이전트 예비 평가 · 전체 성공 아님 · 서비스 미반영<br>
바닥 기준 6개 확인. 2차 이동 9개 중 직접 받침 관계가 타당한 사례 7개, 잘못된 관계 2개.
이는 42개 객체 전체의 정확도나 충돌 없는 배치를 보장하는 수치가 아닙니다.</p>
<p>각 장면에서 같은 카메라로 비교합니다. Y-up 정렬 → 바닥 정렬 → 2차 보정. 마지막 화면에는 실패도 그대로 포함했습니다.</p>''']
count=0
for scene in ['present-cabinet','present-office-c','new-office']:
 r=root/scene;floor=read(r/'floor-report.json');final=read(r/'final-report.json')
 parts.append('<h2>'+esc(scene)+'</h2><div class="grid">')
 for phase,title in [('upright','1. 전체 Y-up 정렬'),('floor','2. 바닥 정렬'),('final','3. 2차 보정 (실패 포함)')]:
  parts.append(f'<div><h3>{title}</h3><img src="{scene}/renders/{phase}-0.png"><a href="{scene}/{phase}.glb">GLB</a></div>')
 parts.append('</div><table><tr><th>객체</th><th>Qwen 받침</th><th>이동</th><th>처리 사유</th><th>예비 평가</th></tr>')
 notes=evaluation['scenes'][scene]
 for row in final['changes']:
  key=row['subject'];note=notes.get(key,{});cls=' class="bad"' if note.get('verdict')=='incorrect_relation' else ''
  parts.append(f'<tr{cls}><td><a href="{scene}/images/{key}.jpg">{key}</a></td><td>{esc(row.get("decision",{}).get("target","unresolved"))}</td><td>{row.get("dy",0):+.5f}' + (' (적용)' if row['applied'] else ' (미적용)') +f'</td><td>{esc(row.get("reason"))}</td><td>{esc(note.get("note","미이동; 성공으로 집계하지 않음"))}</td></tr>')
 parts.append('</table><details><summary>Qwen 원문과 입력</summary>')
 for p in sorted((r/'results').glob('*/*.json')):
  data=read(p);req=read(r/'jobs'/p.parent.name/p.name)['request']
  for path,digest in zip(req['images'],req['image_hashes']):
   if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest:raise ValueError('Submitted image changed: '+path)
  answer=data['output'][0]['choices'][0]['message']['content'];count+=1
  parts.append('<h4>'+esc(p.parent.name+'/'+p.stem)+'</h4><pre>'+esc(answer)+'</pre>')
 parts.append('</details>')
parts.append(f'<p>저장된 응답 {count}개. 전송 입력 이미지 SHA-256 재검증 완료. 실험 endpoint 삭제 후 404 확인.</p>')
(root/'report.html').write_text('\n'.join(parts),encoding='utf-8')
print(json.dumps({'report':str(root/'report.html'),'responses':count,'input_hashes_verified':True}))
