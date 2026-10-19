"""Experimental removal of depth-contradicted faces in a separate scene copy."""
import argparse
from pathlib import Path
import shutil
import numpy as np
from PIL import Image
import trimesh
from mapmaker.scene_free_space import free_space_faces
from mapmaker.scene_geometry import triangles
from mapmaker.scene_projection import silhouette_evidence
from mapmaker.scene_placement import object_vertices,bounds_of
from mapmaker.scene_run import read,write,sha


def main(source,target):
    if target.resolve()==source.resolve() or target.exists():
        raise ValueError('Expected a new independent output directory')
    meta=read(source/'scene_metadata.json')
    digest=sha(source/'scene.glb')
    scene=trimesh.load(source/'scene.glb',force='scene',process=False)
    with np.load(source/meta['pointmap']['asset']) as archive:
        points=archive['points']
    inverse=np.linalg.inv(meta['placement']['common_transform'])
    target.mkdir(parents=True)
    reports=[]
    for obj in meta['objects']:
        if obj['status']!='generated':
            continue
        mask=np.asarray(Image.open(source/obj['mask']).convert('L').resize(points.shape[1::-1],Image.Resampling.NEAREST))>0
        originals={};evidence=[]
        before_faces=triangles(scene,obj['id'])
        before_faces=trimesh.transform_points(before_faces.reshape(-1,3),inverse).reshape(-1,3,3)
        for node in scene.graph.nodes_geometry:
            parent=node
            while parent not in (obj['id'],scene.graph.base_frame):
                parent=scene.graph.transforms.parents.get(parent,scene.graph.base_frame)
            if parent!=obj['id']:
                continue
            matrix,name=scene.graph[node]
            if sum(scene.graph[n][1]==name for n in scene.graph.nodes_geometry)!=1:
                raise ValueError('Shared geometry instance requires explicit independent copy')
            mesh=scene.geometry[name]
            raw=trimesh.transform_points(mesh.vertices,inverse@matrix)[mesh.faces]
            removed,report=free_space_faces(raw,points,mask)
            evidence.append(dict(node=node,**report))
            if not removed.any() or removed.all():
                continue
            original=mesh.copy()
            candidate=mesh.copy();candidate.update_faces(~removed);candidate.remove_unreferenced_vertices()
            originals[name]=original
            scene.geometry[name]=candidate
        if originals:
            after_faces=triangles(scene,obj['id'])
            after_faces=trimesh.transform_points(after_faces.reshape(-1,3),inverse).reshape(-1,3,3)
            before=silhouette_evidence(before_faces,points,mask)
            after=silhouette_evidence(after_faces,points,mask)
            accepted=(before['accepted'] and after['accepted'] and
                after['mask_covered_fraction']>=before['mask_covered_fraction'] and
                after['silhouette_iou']>=before['silhouette_iou'])
            if not accepted:
                for name,mesh in originals.items():scene.geometry[name]=mesh
            else:
                b=bounds_of(object_vertices(scene,obj['id']))
                obj['placement'].update(world_bounds_after=b.tolist(),world_center=b.mean(0).tolist(),
                    world_bottom_center=[float(b[:,0].mean()),float(b[0,1]),float(b[:,2].mean())])
                obj['geometry_refinement']=dict(method='observed_free_space_face_removal',evidence=evidence,
                    original_asset_retained=True,may_be_open=True,uses_object_names=False)
            reports.append(dict(object_id=obj['id'],applied=accepted,evidence=evidence,before=before,after=after))
        else:
            reports.append(dict(object_id=obj['id'],applied=False,evidence=evidence))
        write(target/'free_space_review.json',dict(source_scene_sha256=digest,reports=reports,complete=False))
        print(dict(object_id=obj['id'],applied=reports[-1]['applied']),flush=True)
    files={'scene_metadata.json',meta['input_image'],meta['pointmap']['asset']}
    for obj in meta['objects']:
        for key in ('mask','asset'):
            if obj.get(key):files.add(obj[key])
    for name in files:
        (target/name).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/name,target/name)
    scene.export(target/'scene.glb')
    meta['placement']['scene_sha256']=sha(target/'scene.glb')
    meta['assembly']['bounds']=scene.bounds.tolist()
    meta['placement']['free_space_experiment']=dict(source_scene_sha256=digest,
        applied_objects=[r['object_id'] for r in reports if r['applied']],quality_gate_passed=False,
        fresh_gpu_inference=False,contact_revalidation='pending')
    write(target/'scene_metadata.json',meta)
    write(target/'free_space_review.json',dict(source_scene_sha256=digest,reports=reports,complete=True))
    assert sha(source/'scene.glb')==digest


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('--target',type=Path,required=True)
    a=p.parse_args();main(a.source,a.target)
