"""Development-only orientation evidence at fixed image-line resolutions."""
from pathlib import Path
import argparse
import numpy as np
from PIL import Image
from mapmaker.scene_orientation import estimate_up
from mapmaker.scene_run import read, write, sha


def main(sources, output):
    reports=[]
    for source in sources:
        meta=read(source/'scene_metadata.json')
        points=np.load(source/meta['pointmap']['asset'])['points']
        image=np.asarray(Image.open(source/meta['input_image']).convert('RGB'))
        variants=[]
        for size in (320,640,960):
            evidence=estimate_up(points,image,line_sizes=(size,))
            variants.append(dict(maximum_size=size,evidence=evidence))
            print(dict(run=source.name,resolution=size,accepted=evidence['accepted'],reason=evidence['reason'],
                disagreement=evidence.get('evidence_disagreement_degrees')),flush=True)
        combined=estimate_up(points,image)
        print(dict(run=source.name,combined=combined['accepted'],reason=combined['reason']),flush=True)
        reports.append(dict(run=source.name,input_sha256=sha(source/meta['input_image']),variants=variants,combined=combined))
        write(output,dict(reports=reports,scope='Observed orientation evidence only; no room reconstruction or ground-truth claim'))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('sources',type=Path,nargs='+')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.sources,a.output)
