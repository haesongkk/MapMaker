"""Visual evidence and preservation audit for observed support completion."""
import sys,json,shutil
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapmaker.baseline_assembly import read_header
from mapmaker.scene_run import sha,write

def read(p):return json.loads(p.read_text(encoding='utf8'))
def build(root,baseline):
 sections=[];audit=[]
 for folder in sorted(root.iterdir()):
  if not (folder/'completion-report.json').exists():continue
  source=baseline/folder.name;r=read(folder/'completion-report.json');state=read(folder/'state.json')
  before=read(source/'final-matrices.json');after=read(folder/'final-matrices.json');changed=[k for k in before if not np.allclose(before[k],after[k])]
  assert set(before)==set(after)==set(state['original_matrices'])
  assert sha(Path(state['source'])/'scene.glb')==state['source_scene_sha256']
  original=Path(state['source'])/'scene.glb';_,a,size=read_header(original);doc,b,_=read_header(folder/'final.glb')
  with original.open('rb') as inp,(folder/'final.glb').open('rb') as out:
   inp.seek(a);out.seek(b);assert inp.read(size)==out.read(size)
  audit.append(dict(scene=folder.name,original_objects=len(before),changed_objects=changed,source_unchanged=True,original_binary_prefix_preserved=True,added_parts=sum(v['applied'] for v in r['objects'].values())))
  (folder/'renders').mkdir(exist_ok=True)
  for angle in range(4):
   shutil.copy2(source/'renders'/f'final-{angle}.png',folder/'renders'/f'previous-{angle}.png')
   if not changed:shutil.copy2(source/'renders'/f'final-{angle}.png',folder/'renders'/f'final-{angle}.png')
  n=folder.name
  sections.append(f'<section><h2>{n}</h2><div class="grid"><figure><img class="view" data-base="{n}/renders/previous" src="{n}/renders/previous-3.png"><figcaption>이전 결과</figcaption></figure><figure><img class="view" data-base="{n}/renders/final" src="{n}/renders/final-3.png"><figcaption>수정 결과</figcaption></figure></div><a href="{n}/final.glb">결과 GLB</a> · <a href="{n}/completion-report.json">판정·접촉 검증</a></section>')
 write(root/'audit.json',audit)
 # Presentation crop only: never used by the geometry solver.
 font=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf',22);small=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf',18)
 canvas=Image.new('RGB',(1100,470),'#101826');d=ImageDraw.Draw(canvas)
 d.text((18,10),'모니터: 관측된 스탠드 복원 + 실제 책상 접촉',font=font,fill='white')
 for i,(phase,text) in enumerate([('previous','이전: 본체만 떠 있고 스탠드가 없음'),('final','수정: 본체—스탠드—책상이 연결됨')]):
  im=Image.open(root/'new-office'/'renders'/f'{phase}-3.png').crop((325,330,470,475)).resize((340,340))
  canvas.paste(im,(i*550+105,65));d.text((i*550+18,425),text,font=small,fill='white')
 canvas.save(root/'monitor-contact-comparison.png')
 doc='''<!doctype html><html lang="ko"><meta charset="utf-8"><title>관측 받침 복원과 실제 접촉</title><style>body{font:16px/1.7 system-ui;background:#101826;color:#e9eff6;max-width:1300px;margin:auto;padding:28px}a{color:#8cd3ff}img{width:100%;object-fit:contain}figure{margin:0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}section{padding:24px 0;border-top:1px solid #435068}button{padding:10px 20px;margin:8px}header{padding:20px;background:#182333}@media(max-width:700px){.grid{grid-template-columns:1fr}}</style><h1>떠 있는 모니터 → 스탠드를 통해 책상에 접촉</h1><header><p>이전 마스크가 화면만 포함해 스탠드 메시가 없었습니다. 위치만 바꾸는 것으로는 자연스러운 배치를 만들 수 없어, 원본 RGB·깊이에서 누락된 연결 표면을 추출하고 기존 본체에 정합했습니다. 임의의 원기둥·받침대를 추가하지 않았습니다.</p><p>복원한 표면의 깊이는 그대로 신뢰하지 않습니다. 본체와 연결되도록 제한된 범위에서 정합하고, 하단 접촉과 본체 중심 조건을 함께 맞췄습니다. 기존 평균 업벡터 정렬·Qwen 관계 추론은 사용하지 않았습니다.</p></header><img src="monitor-contact-comparison.png"><p><b>눈으로 확인되는 변화:</b> 화면 아래 빈 공간에 연결 기둥과 발이 생겼고, 발은 책상에 닿습니다. 화면 아래 모서리를 상판에 박아 넣은 결과가 아닙니다. 아래 전후 이미지는 같은 카메라와 조명입니다.</p><p><b>검증:</b> 최종 접촉 재검사에서 추가 수직 이동량 0, 하부 표본 16개 모두 받침면 위에 있으며 그중 10개가 접촉 허용 범위 안에 있습니다. 균일 밀도를 가정한 본체 중심이 접촉 다각형 안에 들어갑니다. 실제 재질별 질량이나 완전한 물리 안정성까지 측정한 것은 아닙니다.</p><p><b>남은 한계:</b> 추가된 부분은 한 장의 RGB·깊이에서 복원한 관측 표면으로, 뒤쪽까지 채워진 완전한 솔리드가 아닙니다. 표면이 거칠고 실제 제품 형상을 정확히 복원했다고 보장할 수 없습니다. 다른 장면에 대한 보편적 성공률도 아직 검증하지 않았습니다.</p><p>같은 규칙을 4개 개발 장면에 적용했습니다. 이번에 새로 추가된 부분은 한 객체이며, 다른 장면의 기존 보정은 유지됩니다. 원래 객체의 메시·텍스처 바이너리는 보존하고 관측 받침만 추가했습니다. 새 받침은 본체의 하위 노드라 본체 이동 시 함께 움직입니다. <a href="audit.json">보존 검증 기록</a></p><p>전체 장면 각도 <button onclick="angle(0)">0</button><button onclick="angle(1)">−45°</button><button onclick="angle(2)">+45°</button><button onclick="angle(3)">180°</button></p>'''
 doc+=''.join(sections)+'<script>function angle(i){document.querySelectorAll("img.view").forEach(e=>e.src=e.dataset.base+"-"+i+".png")}</script></html>'
 (root/'report.html').write_text(doc,encoding='utf8');print(json.dumps(audit))

if __name__=='__main__':build(Path(sys.argv[1]),Path(sys.argv[2]))
