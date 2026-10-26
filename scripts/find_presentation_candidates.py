from pathlib import Path
import json,io
import requests
from PIL import Image,ImageOps,ImageDraw
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/assets/ram-qwen-filter-presentation'
SOURCES=[
 ('chair','https://houseofmorrison.com/products/marigold-chair','https://houseofmorrison.com/cdn/shop/files/HOM_061923_1-263_1100x.jpg?v=1689008022'),
 ('cabinet','https://www.modernfurniture.com.au/products/hayton-tall-ideboard-70cm-white-oak','https://www.modernfurniture.com.au/cdn/shop/files/342007HaytontallsideboardLifestyle1-1000_1024x1024.jpg?v=1700990245'),
 ('dresser','https://www.casavee.com.br/comoda-kaki-4-gavetas-115-cm-x-80-cm-x-45-cm-tauari','https://casavee.cdn.magazord.com.br/img/2024/10/produto/5681/11-comoda-kaki-4g-final.jpg?ims=fit-in%2F1000x1000%2Ffilters%3Afill%28white%29'),
 ('bench','https://www.wayfair.com/furniture/pdp/wade-logan-linzy-modern-wood-bench-w010371284.html','https://assets.wfcdn.com/im/48726512/resize-h800-w800%5Ecompr-r85/2664/266473401/Linzy%2BModern%2BWood%2BBench.jpg'),
 ('bench2','https://www.homedepot.com/p/PLANK-BEAM-Contour-46-in-Blonde-Dining-Bench-2400313000-010/339045877','https://images.thdstatic.com/productImages/47248df8-7cf3-582d-aee2-77f17c6be97b/svn/blonde-plank-beam-dining-benches-2400313000-010-64_600.jpg'),
]
def main():
 OUT.mkdir(parents=True,exist_ok=True); rows=[]
 sheet=Image.new('RGB',(1500,1040),'#182231');draw=ImageDraw.Draw(sheet)
 for i,(name,source,url) in enumerate(SOURCES):
  path=OUT/f'{name}-input.png'
  if not path.exists():
   r=requests.get(url,timeout=60);r.raise_for_status()
   im=ImageOps.exif_transpose(Image.open(io.BytesIO(r.content))).convert('RGB');im.thumbnail((1600,1600));im.save(path)
  im=Image.open(path);thumb=ImageOps.contain(im,(480,470));x=(i%3)*500;y=(i//3)*520
  sheet.paste(thumb,(x+(500-thumb.width)//2,y+30));draw.text((x+15,y+8),name,fill='white')
  rows.append(dict(sample='present-'+name,source_url=source,image_url=url,input_path=path.relative_to(ROOT).as_posix(),image_kind='상품 연출 이미지 · 실사/렌더 미확인',size=list(im.size)))
 (OUT/'sources.json').write_text(json.dumps(rows,indent=2),encoding='utf-8');sheet.save(OUT/'candidates.jpg')
if __name__=='__main__':main()
