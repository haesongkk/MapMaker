"""Build local evidence report and verify raw-pose/binary preservation."""
import json,sys,struct,html
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapmaker.staged_placement import geometry
from mapmaker.scene_run import sha

def read(p):return json.loads(p.read_text(encoding='utf8'))
def binaries(p):
 data=p.read_bytes();offset=12;result=[]
 while offset<len(data):
  length,kind=struct.unpack_from('<II',data,offset);offset+=8
  if kind==0x004e4942:result.append(data[offset:offset+length])
  offset+=length
 return result

def build(root):
 sections=[];audit=[]
 reasons={'observed_floor_contact':'바닥 접촉 보정','vertical_first_contact':'메시 받침면 접촉 보정',
 'preserve_observed_interlock':'끼워진 관계 유지·받침 이동에 동반',
 'follow_observed_support_without_contact_snap':'받침 이동에 동반 (접촉 미확정)',
 'unresolved_observed_support':'받침 불확실·보류','would_degrade_observed_depth':'깊이 불일치·보류',
 'motion_exceeds_depth_budget':'이동 한도 초과·보류','no_nearby_stable_support':'안정적인 받침면 없음·보류'}
 for folder in sorted(root.iterdir()):
  if not (folder/'final-report.json').exists():continue
  state=read(folder/'state.json');floor=read(folder/'floor-report.json');final=read(folder/'final-report.json')
  before={k:np.array(v) for k,v in read(folder/'floor-matrices.json').items()}
  after={k:np.array(v) for k,v in read(folder/'final-matrices.json').items()}
  common=np.array(floor['common_transform']);source=Path(state['source'])
  assert sha(source/'scene.glb')==state['source_scene_sha256']
  assert sha(source/'scene_metadata.json')==state['source_metadata_sha256']
  assert binaries(source/'scene.glb')==binaries(folder/'final.glb')
  assert set(before)==set(after)==set(state['original_matrices'])
  for k in before:
   assert np.allclose(before[k],common@state['original_matrices'][k])
   assert np.allclose(before[k][:3,:3],after[k][:3,:3])
  geo=geometry(source,state['objects'],after);floor_errors=[]
  for change in final['changes']:
   k=change['object_id'];delta=after[k][:3,3]-before[k][:3,3]
   assert np.allclose(delta,change.get('translation',[0,0,0]))
   if change['applied'] and change['target']=='floor':
    error=abs(float(geo[k][0][:,1].min()));assert error<1e-7;floor_errors.append(error)
  counts={key:sum(c['applied'] and c['reason']==key for c in final['changes']) for key in reasons}
  moved=sum(c['applied'] for c in final['changes'])
  item=dict(scene=folder.name,objects=len(after),moved=moved,unchanged=len(after)-moved,
    floor_contacts=len(floor_errors),surface_contacts=counts['vertical_first_contact'],
    carried_without_contact_certification=counts['preserve_observed_interlock']+counts['follow_observed_support_without_contact_snap'],
    max_floor_contact_error=max(floor_errors,default=0),raw_source_unchanged=True,binary_preserved=True,
    rotation_scale_only_common_floor_transform=True,object_up_averaging=False,qwen_relations=False)
  audit.append(item)
  points=np.load(folder/'pointmap.npz')['points'];valid=np.isfinite(points).all(-1)
  z=points[...,2];lo,hi=np.quantile(z[valid],[.02,.98]);g=np.clip((np.nan_to_num(z,nan=lo)-lo)/max(hi-lo,1e-8),0,1)
  rgb=np.stack([g,1-abs(2*g-1),1-g],-1);rgb[~valid]=0
  Image.fromarray((rgb*255).astype('uint8')).save(folder/'depth-preview.png')
  original=Image.open(folder/'original.png').convert('RGB').resize((points.shape[1],points.shape[0]));overlay=np.array(original).astype(float)
  plane=floor['plane']['selected'];distance=abs((points-np.array(plane['point']))@np.array(plane['normal']))
  mask=valid&(distance<floor['plane']['tolerance'])
  for obj in state['objects']:
   mask&=~(np.array(Image.open(source/obj['mask']).convert('L').resize(original.size,Image.Resampling.NEAREST))>0)
  overlay[mask]=overlay[mask]*.35+np.array([20,255,140])*.65
  Image.fromarray(overlay.astype('uint8')).save(folder/'floor-evidence.png')
  labels={o['id']:f'O{i+1:03d}' for i,o in enumerate(state['objects'])}
  rows=''.join(f'<tr><td>{labels[c["object_id"]]}</td><td>{labels.get(c["target"],c["target"] or "미확정")}</td><td>{reasons.get(c["reason"],html.escape(c["reason"]))}</td><td>{c.get("dy",0):+.5f}</td></tr>' for c in final['changes'])
  name=folder.name
  sections.append(f'''<section><h2>{name}</h2><p>객체 {len(after)}개 · 바닥 접촉 {item['floor_contacts']} · 받침면 보정 {item['surface_contacts']} · 동반 이동 {item['carried_without_contact_certification']} · 개별 이동 보류 {item['unchanged']} / 바닥 회전 {floor['plane']['rotation_degrees']:.2f}°</p>
  <div class="grid"><figure><img src="{name}/original.png"><figcaption>원본 이미지</figcaption></figure><figure><img src="{name}/depth-preview.png"><figcaption>MoGe 상대 깊이 (가까움 파랑 → 멂 빨강)</figcaption></figure><figure><img src="{name}/floor-evidence.png"><figcaption>관측된 바닥 후보 · 초록</figcaption></figure></div>
  <div class="grid"><figure><img class="view" data-base="{name}/renders/raw" src="{name}/renders/raw-0.png"><figcaption>원래 SAM3D 좌표</figcaption></figure><figure><img class="view" data-base="{name}/renders/floor-aligned" src="{name}/renders/floor-aligned-0.png"><figcaption>깊이 기반 바닥 정렬만</figcaption></figure><figure><img class="view" data-base="{name}/renders/final" src="{name}/renders/final-0.png"><figcaption>접촉 보정 후</figcaption></figure></div>
  <p><a href="{name}/final.glb">결과 GLB</a> · <a href="{name}/final-report.json">판정 상세</a> · <a href="{name}/depth-provenance.json">깊이 추론 기록</a></p><details><summary>객체별 판정 (O 번호는 원래 객체 순서)</summary><table><tr><th>객체</th><th>받침</th><th>처리</th><th>실제 Y 이동 · 상대 단위</th></tr>{rows}</table></details></section>''')
 (root/'audit.json').write_text(json.dumps(audit,indent=2),encoding='utf8')
 total=sum(a['objects'] for a in audit);moved=sum(a['moved'] for a in audit)
 document='''<!doctype html><html lang="ko"><meta charset="utf-8"><title>깊이·바닥 기반 배치 보정</title><style>body{font:16px/1.65 system-ui;background:#101826;color:#e9eff6;max-width:1500px;margin:auto;padding:32px}h1,h2{line-height:1.3}section{padding:24px 0;border-top:1px solid #435068}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}figure{margin:0}img{width:100%;object-fit:contain;background:#182333;max-height:400px}figcaption{padding:8px}a{color:#8cd3ff}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #435068;padding:8px;text-align:left}button{padding:8px 20px;margin:8px;cursor:pointer}header{background:#182333;padding:20px}summary{cursor:pointer}@media(max-width:800px){.grid{grid-template-columns:1fr}}</style><h1>깊이·바닥 기반 배치 보정</h1><header><b>개발 장면 4개에 대한 예비 결과 · 사람 검증 전</b>'''
 document+=f'<p>{total}개 객체 유지, {moved}개 개별 이동. 원본 파일·메시 바이너리 보존 검증 완료.</p>'
 document+='''<p>원래 SAM3D → MoGe 전체 깊이 → 배경 바닥 평면 → 전체 좌표 정렬 → 깊이·메시로 접촉 보정. 평균 객체 업벡터와 Qwen 관계 추론은 사용하지 않습니다.</p><p>보정 수는 정확도 점수가 아닙니다. 전체 회전은 모든 객체에 적용되며, 개별 이동 보류는 이 회전 이후의 위치를 유지한다는 뜻입니다. 깊이 검증은 최근접 메시 정점 거리의 근사치입니다. 자식 객체는 부모 이동을 감안한 상대 깊이로 검사하며 절대 깊이 오차도 JSON에 기록합니다. 충돌 없는 배치나 무게중심 안정성을 보장하지 않습니다.</p><p>남은 문제: 형상이 불완전한 모니터와 받침이 없는 식물, 가려진 화병 바닥, 접촉면을 확인할 수 없는 모자. 장면 이름의 holdout은 과거 폴더명이며 이번 평가에서 독립 검증셋이 아닙니다.</p></header><p>동일 카메라 비교 각도 <button onclick="angle(0)">0</button><button onclick="angle(1)">−45°</button><button onclick="angle(2)">+45°</button><button onclick="angle(3)">180°</button></p>'''
 review='''<section id="visual-review"><h2>실제로 보기에도 좋아졌는가?</h2><p><b>일부 관통과 겹침은 줄었지만, 전체 배치가 자연스러워졌다고 평가하기에는 부족합니다. 모니터 주변에는 새 부작용도 보입니다.</b></p><p>아래는 같은 카메라·같은 영역의 확대입니다. 왼쪽은 원래 객체 간 배치를 유지한 채 전체 좌표만 바닥 기준으로 맞춘 상태, 오른쪽은 접촉 보정 후입니다. 전체 좌표 회전으로 달라진 구도를 개선으로 세지 않기 위한 비교입니다. 바닥 격자는 추정 평면이며 실제 정답 바닥을 검증한 것은 아닙니다.</p>'''
 for key,caption in [('desk-floor','개선: 책상 하단이 추정 바닥을 뚫고 들어가던 현상이 감소했습니다.'),('books','부분 개선: 상판에 묻혀 있던 아래 책이 드러납니다. 완벽하게 밀착했는지는 이 렌더만으로 확정하지 않습니다.'),('vase','미해결: 작은 화병과 상판 사이의 빈틈이 여전히 보입니다.'),('missing-support','미해결: 받침 형상이 없는 식물은 그대로 공중에 떠 있습니다.'),('regression-monitor','부작용: 책상은 올라갔지만 모니터는 보류되어 제자리에 남았습니다. 모니터 하단이 상판에 묻혀 보이고, 원래 상대 배치가 나빠졌습니다.')]:
  if (root/'visual-review'/f'{key}.png').exists():review+=f'<figure style="max-width:1100px;margin:28px auto"><img style="max-height:none" src="visual-review/{key}.png"><figcaption>{caption}</figcaption></figure>'
 review+='''<p><b>판정: 부분적인 개선을 보인 실험 버전입니다. 전체 품질 개선이 입증된 버전으로 취급하면 안 됩니다.</b> 다음 보완은 가구를 움직이기 전에 위 물체 전체와의 관계를 검증하고, 보류된 물체와 충돌을 만들면 가구 이동도 되돌리는 것입니다. 이는 아직 적용되지 않았습니다.</p></section>'''
 document=document.replace('<header>',review+'<header>',1)
 document+=''.join(sections)+'<script>function angle(i){document.querySelectorAll("img.view").forEach(e=>e.src=e.dataset.base+"-"+i+".png")}</script></html>'
 (root/'report.html').write_text(document,encoding='utf8');print(json.dumps(audit,indent=2))

if __name__=='__main__':build(Path(sys.argv[1]))
