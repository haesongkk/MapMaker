"""Project exported room patches back onto the input for spatial-class review."""
import argparse
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
import trimesh
from mapmaker.scene_geometry import triangles
from mapmaker.scene_vanishing import fit_camera
from mapmaker.scene_run import read, write


def main(run, output):
    meta=read(run/'scene_metadata.json')
    points=np.load(run/meta['pointmap']['asset'])['points']
    camera=fit_camera(points)
    if not camera['accepted']: raise ValueError('Unverified source projection')
    scene=trimesh.load(run/'scene.glb',force='scene',process=False)
    inverse=np.linalg.inv(meta['placement']['common_transform'])
    source=Image.open(run/meta['input_image']).convert('RGB')
    source.thumbnail((1024,1024))
    ratio=np.asarray(source.size)/np.asarray(points.shape[1::-1])
    output.mkdir(parents=True,exist_ok=True)
    reports=[]
    for surface in meta.get('structure',{}).get('surfaces',[]):
        faces=triangles(scene,surface['node'])
        raw=trimesh.transform_points(faces.reshape(-1,3),inverse).reshape(-1,3,3)
        uv=raw@np.asarray(camera['matrix']).T
        valid=np.isfinite(uv).all((1,2)) & (uv[:,:,2]>1e-8).all(1)
        uv=uv[valid,:,:2]/uv[valid,:,2,None]*ratio
        result=source.copy()
        draw=ImageDraw.Draw(result,'RGBA')
        for face in uv:
            draw.polygon([tuple(point) for point in face],fill=(0,230,255,145))
        draw.text((8,8),surface['node']+' / '+surface['kind'],fill=(255,255,255,255),stroke_width=2,stroke_fill=(0,0,0,255))
        file=output/(surface['node']+'.png');result.save(file)
        reports.append(dict(node=surface['node'],kind=surface['kind'],file=str(file),triangles=len(faces)))
    write(output/'manifest.json',dict(scope='Exported patch projection on input; classification requires review',surfaces=reports))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.run,a.output)
