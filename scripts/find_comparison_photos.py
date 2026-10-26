"""Download public candidate images and record source provenance for visual selection."""
import concurrent.futures, html, io, json, re, sys, urllib.request
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/assets/ram-qwen-filter-new-scenes/candidates'
URLS = [
 'https://unsplash.com/photos/a-living-room-with-a-couch-chair-and-table-P0q_HK_-GGM',
 'https://unsplash.com/photos/a-room-with-a-desk-and-a-chair-dew3BVFPLIc',
 'https://unsplash.com/photos/modern-dining-table-with-two-chairs-and-flowers-Jw_A2sTisYc',
 'https://www.pexels.com/photo/empty-two-chairs-in-front-of-table-2079233/',
 'https://www.pexels.com/photo/cozy-home-office-workspace-with-wooden-chair-28808298/',
 'https://www.pexels.com/photo/room-interior-with-chair-near-table-with-laptop-6636251/',
 'https://www.pexels.com/photo/wooden-chair-beside-a-side-table-6633498/',
 'https://www.pexels.com/photo/rustic-rattan-chair-and-side-table-setting-30059652/',
 'https://www.pexels.com/photo/two-armchairs-and-a-table-17756352/',
 'https://www.shopify.com/stock-photos/photos/patio-chairs-and-white-cushions?c=patio',
 'https://www.pexels.com/photo/cozy-bedroom-interior-with-bed-and-nightstand-28536694/',
 'https://www.pexels.com/photo/bedside-table-and-shelves-in-cozy-bedroom-7005280/',
 'https://unsplash.com/photos/workspace-with-laptop-and-wooden-desk-ngpAHJludHA',
 'https://unsplash.com/photos/a-bedroom-with-a-white-bed-and-two-nightstands-etRc_Kp3U_4',
 'https://unsplash.com/photos/a-patio-with-a-table-and-chairs-and-a-couch-OtBwtMTTxWQ',
 'https://unsplash.com/photos/outdoor-patio-furniture-with-chairs-and-a-coffee-table-qBgeOPvGrdE',
 'https://unsplash.com/pt-br/fotografias/roupa-de-cama-branca-e-preta-ook8KEPiB6A',
 'https://sivrilermobilya.com/product/konfor-koltuk-takimi/',
 'https://www.pexels.com/photo/minimalist-design-of-a-home-office-8004011/',
 'https://www.pexels.com/photo/minimalist-setup-office-27920699/',
 'https://www.pexels.com/photo/a-room-with-a-desk-and-a-window-with-a-view-27941302/',
 'https://www.pexels.com/photo/comfortable-bed-with-pillows-and-lamps-on-bedsides-7061089/',
 'https://www.pexels.com/photo/bed-next-to-window-4682137/',
 'https://www.pexels.com/photo/wooden-chairs-and-table-before-tea-5991536/',
 'https://www.pexels.com/photo/empty-white-chairs-beside-table-2995012/',
 'https://www.pexels.com/photo/wooden-chairs-by-table-in-room-19712266/',
 'https://www.pexels.com/photo/a-room-with-a-wooden-table-and-bench-with-a-pair-of-accent-chairs-7028108/',
 'https://www.pexels.com/photo/two-lounge-chairs-by-the-wall-16153260/',
 'https://www.pexels.com/photo/chairs-and-table-on-a-ground-terrace-14737974/',
 'https://www.pexels.com/photo/chairs-by-table-16715649/',
 'https://www.pexels.com/photo/plastic-chairs-by-table-on-balcony-19722321/',
 'https://www.pexels.com/photo/bedside-tables-and-ottoman-bench-in-classy-bedroom-7534540/',
]
def get(url):
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req,timeout=35) as r:return r.read()
def fetch(pair):
    i,url=pair; record={'id':f'candidate-{i:02d}','source_url':url}
    saved=OUT/'sources.json'
    if saved.exists():
        old=next((r for r in json.loads(saved.read_text(encoding='utf-8')) if r['source_url']==url and r['status']=='downloaded'),None)
        if old and (ROOT/old['path']).exists():return old
    try:
        known={1:'https://images.unsplash.com/photo-1693578616322-c8abe6c7393d',2:'https://images.unsplash.com/photo-1650347325139-ba08eeb317d3',3:'https://images.unsplash.com/photo-1784653548815-aacb09fcb220',13:'https://images.unsplash.com/photo-1781106743595-1a2c6397e812',14:'https://images.unsplash.com/photo-1722349670328-1fdd226e6eeb',15:'https://images.unsplash.com/photo-1715090576114-c07384af2069',16:'https://images.unsplash.com/photo-1757430578574-29f8d96af440',17:'https://images.unsplash.com/photo-1616137507072-f7276b168614',18:'https://sivrilermobilya.com/sivriler/uploads/products/konfor-koltuk-takimi.webp'}
        if i in known: image_url=known[i]
        elif 'pexels.com/photo/' in url:
            pid=re.search(r'-(\d+)/$',url)[1]
            image_url=f'https://images.pexels.com/photos/{pid}/pexels-photo-{pid}.jpeg'
        else:
            page=get(url).decode('utf-8',errors='replace')
            (OUT/f'{record["id"]}.html').write_text(page,encoding='utf-8')
            tags=re.findall(r'<meta\b[^>]*>',page,re.I)
            tag=next(t for t in tags if re.search(r'(?:property|name)=[\"\']og:image[\"\']',t))
            image_url=html.unescape(re.search(r'content=[\"\']([^\"\']+)',tag)[1])
        if 'images.unsplash.com/' in image_url:
            image_url=image_url.split('?')[0]+'?auto=format&fit=max&w=1600&q=90'
        elif 'images.pexels.com/' in image_url:
            image_url=image_url.split('?')[0]+'?auto=compress&cs=tinysrgb&w=1600'
        raw=get(image_url)
        im=ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert('RGB')
        im.thumbnail((1600,1600))
        target=OUT/f'{record["id"]}.png';im.save(target)
        record.update(image_url=image_url,path=target.relative_to(ROOT).as_posix(),size=list(im.size),status='downloaded')
    except Exception as e:record.update(status='failed',error=str(e))
    return record
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        records=list(pool.map(fetch,enumerate(URLS,1)))
    (OUT/'sources.json').write_text(json.dumps(records,indent=2,ensure_ascii=False),encoding='utf-8')
    canvas=Image.new('RGB',(1440,((len(records)+2)//3)*400),'#eee'); draw=ImageDraw.Draw(canvas)
    for index,r in enumerate(records):
        x=(index%3)*480;y=(index//3)*400
        draw.text((x+10,y+8),r['id'],fill='black')
        if r['status']=='downloaded':
            im=Image.open(ROOT/r['path']); im.thumbnail((460,360));canvas.paste(im,(x+(480-im.width)//2,y+30))
        else:draw.text((x+10,y+45),r['error'][:55],fill='red')
    canvas.save(OUT/'contact-sheet.jpg')
    print(json.dumps(records,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
