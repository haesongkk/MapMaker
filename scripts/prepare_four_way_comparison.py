"""Inventory exact input matches without relabelling historical outputs."""
import hashlib
import json
from pathlib import Path
import subprocess

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pixels(path):
    with Image.open(path) as source:
        im = ImageOps.exif_transpose(source).convert('RGB')
        return hashlib.sha256(str(im.size).encode()+im.tobytes()).hexdigest()


def main():
    out = ROOT / '.runtime/four-way-comparison'
    out.mkdir(exist_ok=True)
    old = json.loads((ROOT/'docs/assets/experiment_review_2026-10-18/manifest.json').read_text(encoding='utf-8'))
    inputs = [('house','집',ROOT/'.runtime/v6-validation/holdout/01_HouseIndoor.jpg'),
              ('office','사무실',ROOT/'.runtime/v6-validation/holdout/02_Office.jpg'),
              ('restaurant','식당',ROOT/'.runtime/v6-validation/holdout/09_Restaurant.jpg')]
    for key,label in [('displaycase','진열장'),('stairhall','계단홀')]:
        folder=ROOT/old['scenes'][key+'-v9']
        meta=json.loads((folder/'scene_metadata.json').read_text(encoding='utf-8'))
        inputs.append((key,label,folder/meta['input_image']))
    for i,path in enumerate(sorted((ROOT/'samples').iterdir()),1):
        if path.suffix.lower() in ('.jpg','.jpeg','.png','.webp'):
            inputs.append((f'sample-{i:02}',path.name,path))
    records=[]
    for key,label,path in inputs:
        records.append(dict(id=key,label=label,input=str(path.relative_to(ROOT)),
            file_sha256=digest(path),pixel_sha256=pixels(path),existing_candidates=[],
            stages={str(i):dict(status='pending',scene=None,image=None) for i in range(1,5)}))
    wanted={r['pixel_sha256'] for r in records}
    candidates=[]
    names=subprocess.check_output(['rg','--files','--hidden','--no-ignore','.runtime','runs','-g','scene_metadata.json'],cwd=ROOT,text=True,encoding='utf-8',errors='replace').splitlines()
    for name in names:
        path=ROOT/name
        try:
            meta=json.loads(path.read_text(encoding='utf-8'))
            image=path.parent/meta['input_image']
            if not image.is_file() or not (path.parent/'scene.glb').is_file():continue
            match=pixels(image)
            if match not in wanted:continue
            objects=meta.get('objects',[])
            row=dict(path=str(path.parent.relative_to(ROOT)),pixel_sha256=match,
                metadata_sha256=digest(path),objects=sum(o.get('status')=='generated' for o in objects),
                regions=len(meta.get('object_extraction',{}).get('regions',[])),
                point_search=bool(meta.get('object_extraction',{}).get('point_segmentation')),
                placement_version=meta.get('placement',{}).get('version'),
                surfaces=len(meta.get('structure',{}).get('surfaces',[])),
                has_pointmap=bool(meta.get('pointmap')),
                inference_assets_complete=all((path.parent/o['asset']).is_file() and o.get('pose') for o in objects if o.get('asset')))
            candidates.append(row)
        except (ValueError,KeyError,OSError):continue
    for r in records:r['existing_candidates']=[c for c in candidates if c['pixel_sha256']==r['pixel_sha256']]
    report=dict(schema=1,baseline_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        input_count=len(records),requested_results=len(records)*4,
        policy='No historical result is a controlled stage until its code and inference provenance match.',inputs=records)
    (out/'inventory.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([dict(id=r['id'],matches=len(r['existing_candidates'])) for r in records],ensure_ascii=False))


if __name__=='__main__':main()
