"""Apply audited rigid or uniform-scale poses to a separate local scene."""
import argparse
from pathlib import Path
import shutil
import numpy as np
import trimesh
from mapmaker.scene_geometry import triangles
from mapmaker.scene_collision import MeshIndex,certified_penetration_repair
from mapmaker.scene_contacts import improve_contacts
from mapmaker.scene_placement import update_transform, object_vertices, bounds_of, group_export_nodes
from mapmaker.scene_run import read, write, sha


def main(source, proposals, paths, target, repairs=None):
    meta = read(source/'scene_metadata.json')
    original_digest = sha(source/'scene.glb')
    assert read(proposals)['source_scene_sha256'] == read(paths)['source_scene_sha256'] == original_digest
    assert read(paths)['proposals_sha256']==sha(proposals), 'Path proof belongs to another pose proposal'
    allowed = {r['object_id'] for r in read(paths)['reports'] if r['certified_clear']}
    repaired=set()
    if repairs is not None:
        review=read(repairs)
        assert review['source_scene_sha256']==original_digest and review['proposals_sha256']==sha(proposals)
        repaired={r['object_id'] for r in review['reports']
                  if r['existing_penetration_repaired'] and certified_penetration_repair(r['checks'])}
        allowed |= repaired
    proposed = {r['object_id']:r for r in read(proposals)['proposals'] if r['proposed']}
    scene = trimesh.load(source/'scene.glb',force='scene',process=False)
    objects = [o for o in meta['objects'] if o['status']=='generated']
    if any(o.get('placement',{}).get('pose_depth_transform') is not None or
           o.get('placement',{}).get('rigid_depth_transform') is not None for o in objects):
        raise ValueError('Experiment requires a scene without previous experimental pose edits')
    changed=[]
    changed_ids=set()
    for obj in objects:
        oid=obj['id']
        if oid not in allowed:
            continue
        transform=np.asarray(proposed[oid]['transform'])
        moving=triangles(scene,oid)
        # The source hash certifies unchanged geometry. Recheck only objects
        # changed by earlier applications, where that certificate is stale.
        blockers=[]
        for sid in [o['id'] for o in objects]+[s['node'] for s in meta.get('structure',{}).get('surfaces',[])]:
            if sid==oid:
                continue
            if sid not in changed_ids:
                continue
            fixed=triangles(scene,sid)
            end=trimesh.transform_points(moving.reshape(-1,3),transform).reshape(-1,3,3)
            center=(moving.min((0,1))+moving.max((0,1)))/2
            radius=np.linalg.norm(moving-center,axis=-1).max()
            angle=np.deg2rad(proposed[oid]['rotation_degrees'])
            factor=proposed[oid].get('scale_factor',1.)
            pad=radius*(max(1.,factor)*angle**2+2*abs(factor-1)*angle)/8+1e-9
            lower=np.minimum(moving.min((0,1)),end.min((0,1)))-pad
            upper=np.maximum(moving.max((0,1)),end.max((0,1)))+pad
            if np.any(upper<fixed.min((0,1))) or np.any(lower>fixed.max((0,1))):
                continue
            if MeshIndex(fixed).similarity_swept_collision(moving,transform) is not False:
                blockers.append(sid)
        if blockers:
            continue
        matrix=transform@scene.graph[oid][0]
        scene.graph.update(frame_from=scene.graph.base_frame,frame_to=oid,matrix=matrix)
        update_transform(obj,matrix)
        b=bounds_of(object_vertices(scene,oid))
        obj['placement'].update(world_bounds_after=b.tolist(), world_center=b.mean(0).tolist(),
            world_bottom_center=[float(b[:,0].mean()),float(b[0,1]),float(b[:,2].mean())],
            world_up_after=(matrix[:3,1]/np.linalg.norm(matrix[:3,1])).tolist(),
            pose_depth_transform=transform.tolist(),
            pose_depth_prior_contact_count=len(obj['placement'].get('contacts',[])))
        changed.append(dict(object_id=oid, evidence=proposed[oid],
            existing_penetration_repair=oid in repaired))
        changed_ids.add(oid)
    from mapmaker.scene_source_guard import contact_source_guard
    with np.load(source/meta['pointmap']['asset']) as archive:
        guard=contact_source_guard(source,scene,meta,meta['placement'],archive['points'])
    improve_contacts(scene,objects,meta['placement'],meta.get('structure'),source_guard=guard)
    group_export_nodes(scene,objects,meta.get('structure',{}).get('surfaces',[]))
    files={'scene_metadata.json',meta['input_image'],meta['pointmap']['asset']}
    for obj in meta['objects']:
        for key in ('mask','asset'):
            if obj.get(key): files.add(obj[key])
    target.mkdir(parents=True,exist_ok=False)
    for name in files:
        (target/name).parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/name,target/name)
    scene.export(target/'scene.glb')
    meta['placement']['scene_sha256']=sha(target/'scene.glb')
    meta['placement']['pose_depth_experiment']=dict(changes=changed,source_scene_sha256=original_digest,
        proposals_sha256=sha(proposals),path_report_sha256=sha(paths),fresh_gpu_inference=False,
        repair_report_sha256=sha(repairs) if repairs is not None else None,
        quality_gate_passed=False)
    write(target/'scene_metadata.json',meta)
    write(target/'logs/placement.json',meta['placement'])
    write(target/'status.json',dict(stage='done',message='Local pose experiment; quality gate not passed'))
    assert sha(source/'scene.glb')==original_digest
    print(dict(changed=[r['object_id'] for r in changed],contact_changes=meta['placement']['contacts']['changes'],target=str(target)),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('--proposals',type=Path,required=True)
    p.add_argument('--paths',type=Path,required=True)
    p.add_argument('--target',type=Path,required=True)
    p.add_argument('--repairs',type=Path)
    a=p.parse_args()
    main(a.source,a.proposals,a.paths,a.target,a.repairs)
