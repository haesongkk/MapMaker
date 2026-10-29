"""Audit the frozen input experiment; raw responses remain the source of truth."""
import html
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapmaker.scene_run import write,sha

def read(path):
 return json.loads(Path(path).read_text(encoding='utf-8'))

CONDITIONS=['C_marked_target','D_add_mask','E_json_prompt','F_json_schema']
# Explicit agent readings of the short natural-language answers; never used as placement inputs.
PLAIN={
 'present-cabinet':{'O001':['floor','floor'],'O005':['other','other'],'O007':['floor','floor']},
 'present-office-c':{'O001':['floor','floor'],'O005':['other','floor'],'O020':['other','other']},
 'new-office':{'O001':['floor','floor'],'O003':['other','other'],'O009':['other','other']}}
FLAGS={
 ('present-cabinet','O005','C_marked_target'):'Support called drawer, imprecise relative to dresser top.',
 ('present-cabinet','O007','D_add_mask'):'Describes plant supported by pot, rather than clearly isolating target pot.',
 ('present-office-c','O001','C_marked_target'):'Wrong direct supporter: rug; contradicts floor verdict.',
 ('present-office-c','O001','D_add_mask'):'Wrong target: office chair instead of desk; also says rug then floor.',
 ('present-office-c','O001','F_json_schema'):'Main floor conclusion correct, but incorrectly calls rug O001.',
 ('new-office','O009','E_json_prompt'):'Target/support confusion: describes stand/pot instead of shelf-supported plant.',
 ('new-office','O009','F_json_schema'):'Wrong plant instance: describes speckled floor planter instead of shelf plant.'}

def report(root):
 root=Path(root);m=read(root/'manifest.json');truth=read(root/'preliminary-labels.json')
 for p,info in m['files'].items():
  if sha(root/p)!=info['sha256']:raise ValueError('Input changed: '+p)
 scores={c:dict(correct=0,total=0) for c in CONDITIONS};rows=[];scene_answers=[];length=[];results=[]
 for req in m['requests']:
  data=read(root/'results'/(req['id']+'.json'));result=data['result'];results.append(result)
  if result['status']!='COMPLETED':raise ValueError('Nonterminal/failed job')
  choice=result['output'][0]['choices'][0];raw=choice['message']['content']
  if choice['finish_reason']!='stop':length.append(req['id'])
  if req['condition'] not in CONDITIONS:
   scene_answers.append(dict(request_id=req['id'],finish_reason=choice['finish_reason'],response=raw));continue
  s,oid,c=req['scene'],req['subject'],req['condition'];expected=truth['labels'][s][oid]['contact']
  fields=None
  if c in CONDITIONS[:2]:contact=PLAIN[s][oid][CONDITIONS.index(c)]
  else:
   obj=json.loads(raw);contact=obj['contact'];fields=list(obj)
  if choice['finish_reason']!='stop':raise ValueError('Incomplete targeted response')
  scores[c]['total']+=1;scores[c]['correct']+=int(contact==expected)
  rows.append(dict(request_id=req['id'],scene=s,subject=oid,condition=c,expected=expected,
                   contact=contact,correct=contact==expected,field_order=fields,response=raw,
                   semantic_note=FLAGS.get((s,oid,c),'')))
 evaluation=dict(review_kind='agent_preliminary_not_human_validated',scope='contact-only accuracy; not full identity/support or placement accuracy',
                 scores=scores,rows=rows,scene_answers=scene_answers,truncated_requests=length,
                 requests=len(results),execution_ms=sum(r['executionTime'] for r in results),
                 source_manifest_sha256=sha(root/'manifest.json'))
 write(root/'evaluation.json',evaluation)
 esc=html.escape
 parts=['<!doctype html><meta charset="utf-8"><title>Qwen input control</title><style>body{font:16px system-ui;margin:30px;max-width:1400px;background:#f5f7fa;color:#152337}table{border-collapse:collapse;width:100%}td,th{border:1px solid #bdc8d7;padding:10px;vertical-align:top}pre{white-space:pre-wrap;max-width:100%;font:14px monospace}.images{display:flex;gap:12px}.images img{width:48%}.bad{background:#ffe4dd}details{margin:12px 0}</style><h1>Qwen 입력 조건 대조 실험</h1><p>사람 검증 전 예비 평가 · 42회 · 동일 모델/seed/temperature · 바닥 여부 점수는 객체 인식·받침 정확도를 보장하지 않음</p><table><tr><th>조건</th><th>바닥 여부</th></tr>']
 for c,v in scores.items():parts.append(f'<tr><td>{c}</td><td>{v["correct"]}/{v["total"]}</td></tr>')
 parts.append('</table>')
 for s,ids in m['targets'].items():
  parts.append(f'<h2>{s}</h2><div class="images"><img src="{s}/original.jpg"><img src="{s}/marked.jpg"></div>')
  for a in scene_answers:
   if a['request_id'].startswith(s+'__'):parts.append(f'<details><summary>{esc(a["request_id"])} — {a["finish_reason"]}</summary><pre>{esc(a["response"])}</pre></details>')
  for oid in ids:
   parts.append(f'<h3>{oid} — 예비 정답 {truth["labels"][s][oid]["contact"]}</h3><table><tr><th>조건</th><th>모델 원문</th><th>별도 의미 검토</th></tr>')
   for r in rows:
    if r['scene']==s and r['subject']==oid:
     parts.append('<tr class="'+('bad' if not r['correct'] or r['semantic_note'] else '')+'"><td>'+r['condition']+'</td><td><pre>'+esc(r['response'])+'</pre></td><td>'+esc(r['semantic_note'])+'</td></tr>')
   parts.append('</table>')
 (root/'report.html').write_text(''.join(parts),encoding='utf-8')
 print(json.dumps(dict(scores=scores,truncated=length,requests=len(results)),ensure_ascii=False))

if __name__=='__main__':report(sys.argv[1])
