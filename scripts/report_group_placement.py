"""Render comparison evidence; named crops here are presentation only."""
import sys,json,html
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from scipy.spatial import cKDTree
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapmaker.staged_placement import geometry
from mapmaker.scene_run import sha,write
from scripts.report_depth_floor import binaries

def read(p):return json.loads(p.read_text(encoding='utf8'))

def build(root,previous):
 font=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf',22);small=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf',18)
 cases=[('monitor','new-office',3,(320,320,475,480),'모니터: 책상 이동에 함께 따라가 하단 묻힘 방지','이전: 책상만 올라가 모니터 하단을 가림','수정: 책상과 모니터 사이의 원래 간격 유지'),('vase','present-cabinet',0,(535,195,690,335),'화병: 상판과의 빈틈 제거 · 식물도 함께 이동','이전: 화병이 상판 위에 떠 있음','수정: 화병 바닥을 상판에 맞춤')]
 for key,name,angle,box,title,left,right in cases:
  canvas=Image.new('RGB',(1100,440),'#101826');d=ImageDraw.Draw(canvas);d.text((18,10),title,font=font,fill='white')
  for i,(phase,caption) in enumerate([('previous',left),('final',right)]):
   im=Image.open(root/name/'renders'/f'{phase}-{angle}.png').crop(box);ratio=min(530/im.width,300/im.height);im=im.resize((round(im.width*ratio),round(im.height*ratio)))
   canvas.paste(im,(i*550+(550-im.width)//2,72));d.text((i*550+18,390),caption,font=small,fill='white')
  canvas.save(root/f'{key}-comparison.png')
 audits=[];sections=[]
 for folder in sorted(root.iterdir()):
  if not (folder/'group-report.json').exists():continue
  s=read(folder/'state.json');r=read(folder/'group-report.json');old=read(previous/folder.name/'final-matrices.json');new=read(folder/'final-matrices.json');base=read(folder/'floor-matrices.json')
  assert sha(Path(s['source'])/'scene.glb')==s['source_scene_sha256']
  assert binaries(Path(s['source'])/'scene.glb')==binaries(folder/'final.glb')
  assert set(old)==set(new)==set(s['original_matrices'])
  geo=geometry(s['source'],s['objects'],{k:np.array(v) for k,v in base.items()});world=np.load(folder/'world-pointmap.npz')['points']
  changed=[];depth=[]
  for obj in s['objects']:
   k=obj['id'];a=np.array(old[k]);b=np.array(new[k]);c=np.array(base[k]);assert np.allclose(a[:3,:3],b[:3,:3])
   delta=b[:3,3]-c[:3,3];assert np.allclose(delta,r['decisions'][k]['translation'])
   if np.linalg.norm(b[:3,3]-a[:3,3])<1e-10:continue
   changed.append(k);mask=np.array(Image.open(Path(s['source'])/obj['mask']).convert('L').resize((world.shape[1],world.shape[0]),Image.Resampling.NEAREST))>0
   cloud=world[mask];cloud=cloud[np.isfinite(cloud).all(1)];cloud=cloud[np.linspace(0,len(cloud)-1,min(len(cloud),512)).astype(int)]
   tree=cKDTree(geo[k][0]);before=tree.query(cloud-(a[:3,3]-c[:3,3]))[0];after=tree.query(cloud-delta)[0]
   depth.append(dict(object_id=k,before_median=float(np.median(before)),after_median=float(np.median(after)),method='absolute_source_observation_to_mesh_vertex_distance_proxy'))
  gaps=[]
  for k,decision in r['decisions'].items():
   if 'evidence' not in decision:continue
   p=decision['parent'];rawgap=decision['evidence']['gap']
   oldgap=rawgap+(np.array(old[k])[1,3]-np.array(base[k])[1,3])-(np.array(old[p])[1,3]-np.array(base[p])[1,3])
   newgap=rawgap+(np.array(new[k])[1,3]-np.array(base[k])[1,3])-(np.array(new[p])[1,3]-np.array(base[p])[1,3])
   gaps.append(dict(child=k,parent=p,before=float(oldgap),after=float(newgap),original=float(rawgap)))
  audit=dict(scene=folder.name,objects=len(new),changed_from_previous=changed,source_unchanged=True,binary_preserved=True,rotations_scales_preserved=True,gaps=gaps,absolute_depth_proxy=depth,group_violations=r['violations'])
  audits.append(audit)
  labels={o['id']:f'O{i+1:03d} {o["name"]}' for i,o in enumerate(s['objects'])}
  rows=''.join(f'<tr><td>{html.escape(labels[k])}</td><td>{html.escape(labels.get(v["parent"],v["parent"] or "불확실"))}</td><td>{v["reason"]}</td></tr>' for k,v in r['decisions'].items())
  n=folder.name
  sections.append(f'<section><h2>{n}</h2><div class="grid"><figure><img class="view" data-base="{n}/renders/previous" src="{n}/renders/previous-0.png"><figcaption>이전 결과</figcaption></figure><figure><img class="view" data-base="{n}/renders/final" src="{n}/renders/final-0.png"><figcaption>그룹 관계 보정 후</figcaption></figure></div><p><a href="{n}/final.glb">결과 GLB</a> · <a href="{n}/group-report.json">판정 근거</a></p><details><summary>객체별 관계</summary><table>{rows}</table></details></section>')
 write(root/'audit.json',audits)
 doc='''<!doctype html><html lang="ko"><meta charset="utf-8"><title>가구와 위 물체를 함께 보정</title><style>body{font:16px/1.7 system-ui;background:#101826;color:#e9eff6;max-width:1300px;margin:auto;padding:28px}a{color:#8cd3ff}img{width:100%;object-fit:contain}figure{margin:0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}section{border-top:1px solid #435068;padding:20px 0}button{padding:10px 20px;margin:8px}td{border-bottom:1px solid #435068;padding:10px}summary{cursor:pointer}table{width:100%}header{padding:20px;background:#182333}@media(max-width:700px){.grid{grid-template-columns:1fr}}</style><h1>가구와 위 물체를 함께 보정한 결과</h1><header><b>모니터 하단 묻힘 방지 · 화병의 상판 빈틈 제거</b><p>왼쪽은 앞서 확인한 문제가 있던 결과, 오른쪽은 이번 수정 결과입니다. 카메라·조명·확대 영역은 같습니다. 4개 개발 장면에 같은 규칙을 적용했으며, 사람 검증 전 예비 결과입니다.</p></header><h2>모니터</h2><img src="monitor-comparison.png"><p>모니터와 책상을 지지 관계로 묶어 같은 만큼 이동시켰습니다. 모니터 하단을 상판이 가리던 부작용을 없애고, 보정 전 상대 높이를 유지합니다. 누락되거나 불완전한 스탠드 형상을 새로 생성한 것은 아닙니다.</p><h2>화병과 식물</h2><img src="vase-comparison.png"><p>화병 아래 넓은 받침면을 확인해 작은 간격을 닫았습니다. 화병 위 식물도 같은 만큼 이동하므로 둘 사이의 상대 배치가 유지됩니다.</p><h2>공통 규칙과 한계</h2><p>객체 이름·장면 ID로 분기하지 않습니다. 메시 바닥의 80% 이상을 받치는 가까운 수평면으로 이동 관계를 만들고, 깊이 기반 장면 크기에 비례하는 작은 간격만 닫습니다. 큰 간격은 빠진 받침일 수 있어 보존합니다. 깊이맵에 중간 받침면이 있으면 그 아래 메시로 내리지 않습니다. 새 관통 또는 받침 이탈을 감지하면 연결된 그룹의 이동을 되돌립니다.</p><p>검사는 받침면 기준의 관통 검사이며 모든 방향의 메시 충돌을 보장하지 않습니다. 작은 간격 보정은 원본 깊이와의 일치보다 접촉을 우선할 수 있고, 그 오차 변화도 <a href="audit.json">검증 기록</a>에 남겼습니다. 받침 자체가 없는 식물, 불완전한 형상, 불확실한 관계는 여전히 남습니다. 이 장면들을 독립 검증셋으로 간주하지 않습니다.</p><p>전체 장면 각도 <button onclick="angle(0)">0</button><button onclick="angle(1)">−45°</button><button onclick="angle(2)">+45°</button><button onclick="angle(3)">180°</button></p>'''
 doc+=''.join(sections)+'<script>function angle(i){document.querySelectorAll("img.view").forEach(e=>e.src=e.dataset.base+"-"+i+".png")}</script></html>'
 (root/'report.html').write_text(doc,encoding='utf8')
 print(json.dumps(audits,indent=2))

if __name__=='__main__':build(Path(sys.argv[1]),Path(sys.argv[2]))
