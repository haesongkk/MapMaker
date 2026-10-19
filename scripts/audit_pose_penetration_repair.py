"""Distinguish existing penetrations repaired by a pose from new collisions."""
import argparse
from pathlib import Path
import numpy as np
import trimesh
from mapmaker.scene_run import read,write,sha
from mapmaker.scene_geometry import triangles
from mapmaker.scene_collision import MeshIndex,certified_penetration_repair,initial_penetration_evidence


def main(source,proposals,paths,output):
    digest=sha(source/'scene.glb')
    proposal_digest=sha(proposals)
    assert read(paths)['source_scene_sha256']==read(proposals)['source_scene_sha256']==digest
    scene=trimesh.load(source/'scene.glb',force='scene',process=False)
    proposal_map={r['object_id']:r for r in read(proposals)['proposals'] if r['proposed']}
    reports=[]
    for path in read(paths)['reports']:
        if path['certified_clear']:continue
        oid=path['object_id'];moving=triangles(scene,oid)
        end=trimesh.transform_points(moving.reshape(-1,3),proposal_map[oid]['transform']).reshape(-1,3,3)
        checks=[]
        for previous in path['checks']:
            sid=previous['other_id'];index=MeshIndex(triangles(scene,sid))
            before=index.swept_collision(moving,np.zeros(3))
            after=index.swept_collision(end,np.zeros(3))
            checks.append(dict(other_id=sid,path_result=previous['result'],
                before='unknown' if before is None else 'intersection' if before else 'clear',
                after='unknown' if after is None else 'intersection' if after else 'clear'))
            if before is True and after is False and previous['result']=='intersection':
                checks[-1].update(initial_penetration_evidence(index,moving))
        repair=certified_penetration_repair(checks)
        reports.append(dict(object_id=oid,existing_penetration_repaired=repair,checks=checks))
        assert sha(proposals)==proposal_digest and sha(source/'scene.glb')==digest
        write(output,dict(source_scene_sha256=digest,proposals_sha256=proposal_digest,reports=reports,
            scope='Endpoint collision and containment; only measured pre-existing collisions may explain a blocked path'))
        print(reports[-1],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('--proposals',type=Path,required=True)
    p.add_argument('--paths',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.source,a.proposals,a.paths,a.output)
