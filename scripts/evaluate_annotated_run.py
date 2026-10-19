"""Compare a frozen annotated subset by mask boxes; never label it full recall."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps
from mapmaker.scene_run import read, write, sha


def box_iou(a, b):
    a,b=np.asarray(a),np.asarray(b)
    intersection=float(np.maximum(0,np.minimum(a[2:],b[2:])-np.maximum(a[:2],b[:2])).prod())
    union=float(np.prod(a[2:]-a[:2])+np.prod(b[2:]-b[:2])-intersection)
    return intersection/union if union else 0.


def match_boxes(references, predictions, threshold=.35):
    edges={i:sorted([j for j,b in enumerate(predictions) if box_iou(a,b)>=threshold],
                    key=lambda j:-box_iou(a,predictions[j])) for i,a in enumerate(references)}
    owners={}
    def assign(i,seen):
        for j in edges[i]:
            if j in seen:continue
            seen.add(j)
            if j not in owners or assign(owners[j],seen):
                owners[j]=i;return True
        return False
    for i in edges:assign(i,set())
    return {i:j for j,i in owners.items()}, edges


def evaluate(manifest, sample, run):
    records=[r for split in ('held_out','development') for r in manifest.get(split, []) if r.get('id')==sample]
    if len(records)!=1:
        raise ValueError('Expected exactly one frozen annotation record for sample')
    record=records[0]
    source=Path(record['file'])
    if sha(source)!=record['sha256']:raise ValueError('Frozen input changed')
    meta=read(run/'scene_metadata.json')
    expected=np.asarray(ImageOps.exif_transpose(Image.open(source)).convert('RGB'))
    actual=np.asarray(Image.open(run/meta['input_image']).convert('RGB'))
    if not np.array_equal(expected,actual):raise ValueError('Run input pixels do not match evaluation input')
    generated=[o for o in meta['objects'] if o['status']=='generated']
    predictions=[]
    for obj in generated:
        mask=np.asarray(Image.open(run/obj['mask']))>0
        y,x=np.where(mask)
        if not len(x):raise ValueError('Empty generated mask')
        predictions.append([x.min()/mask.shape[1],y.min()/mask.shape[0],(x.max()+1)/mask.shape[1],(y.max()+1)/mask.shape[0]])
    refs=record['objects']; matches,edges=match_boxes([o['box_xyxy_normalized'] for o in refs],predictions)
    return dict(sample=sample,split=record.get('split','held_out'),run_id=meta['run_id'],placement_version=meta.get('placement',{}).get('version'),
        scope='coarse-box correspondence for preselected visible subset, not full recall or 3D correctness',
        annotation_protocol={key:record[key] for key in ('annotation_status','annotation_scope','annotation_author') if key in record},
        annotated=len(refs),matched=len(matches),missing=[o['id'] for i,o in enumerate(refs) if i not in matches],
        small_annotated=sum(o['small'] for o in refs),small_matched=sum(refs[i]['small'] for i in matches),
        matches={refs[i]['id']:generated[j]['id'] for i,j in matches.items()},
        possible_duplicate_candidates={refs[i]['id']:[generated[j]['id'] for j in js] for i,js in edges.items() if len(js)>1},
        required_visual_review=dict(duplicates='pending',harmful_moves='pending',support_relations='pending',room_structure='pending'),
        deployment_gate='PENDING_VISUAL_REVIEW_AND_VERSION_COMPARISON')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,default=Path('docs/QUALITY_EVALUATION_V2.json'))
    p.add_argument('--sample',required=True);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();write(a.output,evaluate(read(a.manifest),a.sample,a.run))
