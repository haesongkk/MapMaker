"""Audit and present saved pair-support results without replacing model answers."""
import html
import json
import hashlib
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapmaker.staged_placement import geometry
from mapmaker.scene_geometry import contact_footprint,HorizontalSurface
from mapmaker.scene_run import sha

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def esc(s):return html.escape(str(s))

root=Path(sys.argv[1]).resolve()
audit={'status':'agent_preliminary_not_human_verified','scenes':{},'responses_by_round':{},'verified_image_references':0}
parts=['''<!doctype html><html lang="ko"><meta charset="utf-8"><title>객체 배치 보정 결과</title>
<style>body{margin:0;background:#121c29;color:#e6edf6;font:16px/1.6 system-ui}main{max-width:1500px;margin:auto;padding:32px}h1{margin:0}h2{margin-top:48px}.note{padding:18px;background:#26364b;border-left:4px solid #85c8ff}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}img{width:100%;background:#182333}a{color:#8dd8ff}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:9px;border-bottom:1px solid #435064;text-align:left}select{padding:7px;margin:8px;background:#26364b;color:white}details{margin:16px 0}pre{white-space:pre-wrap}.source{max-width:420px}small{color:#b5c5d9}</style><main>
<h1>Qwen 관계 추론 + 실제 메시 접촉 보정</h1>
<p class="note">사람 검증 전 에이전트 예비 평가 · 실험 결과이며 서비스에는 아직 반영하지 않음.<br>
전체 객체 평균 업벡터로 Y-up 정렬 → 바닥 객체 정렬 → 받침 방향·삽입 관계·직접 받침 이름 확인 → 메시 접촉 보정.<br>
특정 장면이나 객체 이름별 위치 규칙 없이 같은 알고리즘을 4개 장면에 적용했습니다.</p>
<p>왼쪽은 Y-up만 맞춘 원래 배치, 오른쪽은 보정 결과입니다. 생성되지 않은 선반·받침·벽은 이번 보정으로 복원되지 않으므로, 해당 물체는 여전히 떠 보일 수 있습니다. 접촉 검사는 완전한 충돌 검사나 물리 안정성 보장이 아닙니다.</p>''']
scene_order=['present-cabinet','holdout-bench','new-office','present-office-c']
for scene in sorted((p for p in root.iterdir() if (p/'final-report.json').exists()),key=lambda p:scene_order.index(p.name) if p.name in scene_order else len(scene_order)):
 state=read(scene/'state.json');floor=read(scene/'floor-report.json');final=read(scene/'final-report.json');bundle=read(scene/'image-inputs/inputs.json')
 assert sha(Path(state['source'])/'scene.glb')==state['source_scene_sha256']
 assert sha(Path(state['source'])/'scene_metadata.json')==state['source_metadata_sha256']
 matrices={k:np.array(v) for k,v in read(scene/'final-matrices.json').items()}
 for k,m in matrices.items():assert np.allclose(m[:3,:3],np.array(state['upright'][k])[:3,:3])
 geo=geometry(state['source'],state['objects'],matrices);ids={o['id']:o['object_id'] for o in bundle['objects']}
 floor_errors={k:float(abs(geo[k][0][:,1].min())) for k in floor['anchor_ids']}
 assert max(floor_errors.values())<1e-7
 checks={}
 for row in final['changes']:
  if not row['applied']:continue
  v=geo[ids[row['subject']]][0];pv,pf=geo[ids[row['target']]]
  if row['relation']=='ON':
   feet=contact_footprint(v);surf=HorizontalSurface(pv[pf])
   # A post-placement contact query must stop at the foot itself. Reusing the
   # proposal's upward search window can incorrectly select the NEXT shelf.
   offsets=[h-p[1] for p in feet if (h:=surf.height(p[[0,2]],maximum=p[1]+final['tolerance'])) is not None]
   residual=float(max(offsets)) if offsets else None
   checks[row['subject']]={'kind':'finite_surface_contact_proxy','residual':residual,'within_tolerance':residual is not None and abs(residual)<=final['tolerance']}
  else:
   checks[row['subject']]={'kind':'container_vertical_bounds_proxy','bottom':float(v[:,1].min()),'container_bottom':float(pv[:,1].min()),'within_tolerance':float(v[:,1].min())>=float(pv[:,1].min())-final['tolerance']}
 for p in (scene/'jobs').glob('*/*.json'):
  job=read(p);request=job['request'];result=scene/'results'/p.parent.name/p.name
  assert result.exists(),f'Missing response: {result}'
  data=read(result);assert data['status']=='COMPLETED',result
  audit['responses_by_round'][p.parent.name]=audit['responses_by_round'].get(p.parent.name,0)+1
  for path,digest in zip(request['images'],request['image_hashes']):
   assert sha(Path(path))==digest,f'Changed inference image: {path}'
   audit['verified_image_references']+=1
 summary={'objects':len(state['objects']),'aliases':len(read(scene/'aliases.json')),'floor_anchors':len(floor['anchor_ids']),'support_moves':sum(r['applied'] for r in final['changes']),'unchanged_nonfloor':sum(not r['applied'] for r in final['changes']),'source_hashes_unchanged':True,'rotations_scales_preserved_after_y_up':True,'floor_errors':floor_errors,'placement_checks':checks,'binary_preserved':final['binary_preserved']}
 audit['scenes'][scene.name]=summary
 angle=0 if scene.name=='present-cabinet' else 3
 angles=[i for i in range(4) if (scene/f'renders/upright-{i}.png').exists() and (scene/f'renders/final-{i}.png').exists()]
 parts.append(f'<section id="{scene.name}"><h2>{esc(scene.name)}</h2><p>바닥 정렬 {summary["floor_anchors"]}개 · 추가 배치 이동 {summary["support_moves"]}개 · 미이동 {summary["unchanged_nonfloor"]}개</p>')
 parts.append('<label>비교 각도 <select onchange="this.closest(\'section\').querySelectorAll(\'[data-phase]\').forEach(im=>im.src=im.dataset.scene+\'/renders/\'+im.dataset.phase+\'-\'+this.value+\'.png\')">'+''.join(f'<option value="{i}" {"selected" if i==angle else ""}>{i+1}</option>' for i in angles)+'</select></label><div class="grid">')
 for phase,label in [('upright','보정 전 · 공통 Y-up'),('final','보정 후')]:
  parts.append(f'<div><h3>{label}</h3><img data-scene="{scene.name}" data-phase="{phase}" src="{scene.name}/renders/{phase}-{angle}.png"><a href="{scene.name}/{phase}.glb">{label} GLB</a></div>')
 parts.append(f'</div><details><summary>원본 사진과 바닥 정렬 중간 결과</summary><img class="source" src="{scene.name}/image-inputs/original.png"><img src="{scene.name}/renders/floor-0.png"></details>')
 parts.append('<table><tr><th>객체</th><th>받침</th><th>관계</th><th>적용</th><th>처리 결과</th></tr>')
 for r in final['changes']:
  parts.append(f'<tr><td><a href="{scene.name}/images/{r["subject"]}.jpg">{r["subject"]}</a></td><td>{esc(r.get("target","—"))}</td><td>{esc(r.get("relation","—"))}</td><td>{"이동" if r["applied"] else "미이동"}</td><td>{esc(r["reason"])}</td></tr>')
 parts.append('</table><details><summary>검증 수치와 적용하지 않은 받침 후보</summary><pre>'+esc(json.dumps({'geometry':checks,'rejected_identity':final.get('rejected_identity',[])},ensure_ascii=False,indent=2))+'</pre></details></section>')
audit['total_floor_anchors']=sum(s['floor_anchors'] for s in audit['scenes'].values())
audit['total_support_moves']=sum(s['support_moves'] for s in audit['scenes'].values())
parts[0]=parts[0].replace('<h1>Qwen 관계 추론 + 실제 메시 접촉 보정</h1>',f'<h1>Qwen 관계 추론 + 실제 메시 접촉 보정</h1><p><strong>{len(audit["scenes"])}개 장면 · 바닥 정렬 {audit["total_floor_anchors"]}개 · 추가 배치 이동 {audit["total_support_moves"]}개</strong></p>')
(root/'validation.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
parts.append('<p>원본 파일·전송 이미지 해시 재검증 완료. 상세 기록: <a href="validation.json">validation.json</a>. 실행 중 잘못된 응답과 이전 보정 결과도 별도로 보존했습니다.</p></main></html>')
(root/'report.html').write_text('\n'.join(parts),encoding='utf-8')
print(json.dumps({'floor_anchors':audit['total_floor_anchors'],'support_moves':audit['total_support_moves'],'responses':sum(audit['responses_by_round'].values()),'image_references':audit['verified_image_references']}))
