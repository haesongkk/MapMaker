"""Certify candidate rigid paths after source projection and final-pose checks."""
import argparse
from pathlib import Path
import numpy as np
import trimesh
from mapmaker.scene_collision import MeshIndex
from mapmaker.scene_geometry import triangles
from mapmaker.scene_run import read, write, sha


def main(source, proposals, collisions, output):
    digest = sha(source/'scene.glb')
    proposal_digest=sha(proposals)
    assert read(proposals)['source_scene_sha256'] == read(collisions)['source_scene_sha256'] == digest
    meta = read(source/'scene_metadata.json')
    scene = trimesh.load(source/'scene.glb', force='scene', process=False)
    faces = {o['id']: triangles(scene,o['id']) for o in meta['objects'] if o['status']=='generated'}
    for surface in meta.get('structure',{}).get('surfaces',[]):
        faces[surface['node']] = triangles(scene,surface['node'])
    allowed = {r['object_id'] for r in read(collisions)['reports'] if r['final_surfaces_clear']}
    reports = []
    for proposal in read(proposals)['proposals']:
        oid = proposal['object_id']
        if oid not in allowed:
            continue
        moving = faces[oid]
        transform = np.asarray(proposal['transform'])
        end = trimesh.transform_points(moving.reshape(-1,3),transform).reshape(-1,3,3)
        center = (moving.min((0,1))+moving.max((0,1)))/2
        radius = np.linalg.norm(moving-center,axis=-1).max()
        angle=np.deg2rad(proposal['rotation_degrees'])
        factor=proposal.get('scale_factor',1.)
        padding = radius*(max(1.,factor)*angle**2+2*abs(factor-1)*angle)/8+1e-9
        lower = np.minimum(moving.min((0,1)),end.min((0,1)))-padding
        upper = np.maximum(moving.max((0,1)),end.max((0,1)))+padding
        checks = []
        for sid, other in faces.items():
            if sid == oid or np.any(upper < other.min((0,1))) or np.any(lower > other.max((0,1))):
                continue
            collision = MeshIndex(other).similarity_swept_collision(moving,transform)
            checks.append(dict(other_id=sid, result='unknown' if collision is None else 'intersection' if collision else 'clear'))
        reports.append(dict(object_id=oid, certified_clear=all(c['result']=='clear' for c in checks), checks=checks))
        print(reports[-1],flush=True)
        assert sha(proposals)==proposal_digest and sha(source/'scene.glb')==digest
        write(output,dict(source_scene_sha256=digest, proposals_sha256=proposal_digest,
            reports=reports, scope='Full bounded uniform-scale/rigid path and closed containment, without weakening unknown policy'))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('--proposals',type=Path,required=True)
    p.add_argument('--collisions',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    main(a.source,a.proposals,a.collisions,a.output)
