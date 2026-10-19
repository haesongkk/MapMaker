"""Export unclaimed observed background, without assigning room semantics."""
import argparse
from pathlib import Path
import shutil
import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation
import trimesh
from mapmaker.scene_structure import observed_context_mesh
from mapmaker.scene_geometry import triangles
from mapmaker.scene_placement import group_export_nodes
from mapmaker.scene_run import read,write,sha


def main(source,target):
    if target.exists() or source.resolve()==target.resolve():
        raise ValueError('Expected a new independent output directory')
    meta=read(source/'scene_metadata.json');digest=sha(source/'scene.glb')
    info=meta['pointmap'];assert sha(source/info['asset'])==info['sha256']
    with np.load(source/info['asset'],allow_pickle=False) as archive:points=archive['points']
    h,w=points.shape[:2]
    excluded=np.zeros((h,w),bool)
    for obj in meta['objects']:
        if obj.get('mask') and obj['status'] not in ('structural','duplicate'):
            excluded |= np.asarray(Image.open(source/obj['mask']).convert('L').resize((w,h),Image.Resampling.NEAREST))>0
    excluded=binary_dilation(excluded,structure=np.ones((3,3)))
    valid=np.isfinite(points).all(-1)&(np.linalg.norm(points,axis=-1)>1e-6)
    selected=valid&~excluded
    rgb=np.asarray(Image.open(source/meta['input_image']).convert('RGB').resize((w,h)))
    scene=trimesh.load(source/'scene.glb',force='scene',process=False)
    surfaces=[]
    previous_context=0
    for surface in meta['structure']['surfaces']:
        if surface['node']=='structure_observed_context':
            _,name=scene.graph[surface['node']]
            previous_context+=len(scene.geometry[name].faces)
            scene.delete_geometry(name);scene.graph.transforms.remove_node(surface['node'])
        else:surfaces.append(surface)
    planes=[s for s in surfaces if 'point' in s and 'normal' in s]
    mesh=observed_context_mesh(points,selected,rgb,meta['placement']['common_transform'],planes,
        plane_faces=[triangles(scene,s['node']) for s in planes])
    if mesh is not None:
        node='structure_observed_context'
        scene.add_geometry(mesh,node_name=node,geom_name=node,parent_node_name=scene.graph.base_frame)
        surfaces.append(dict(node=node,kind='observed',bounds=mesh.bounds.tolist(),
            evidence='valid_unclaimed_shared_pointmap_neighbors',completion='observed_patches_only',
            confidence=dict(kind='unclassified_monocular_depth_not_room_semantics'),
            limitation='May include undetected objects; no wall/floor/ceiling assertion or hidden completion'))
    objects=[o for o in meta['objects'] if o['status']=='generated']
    groups=group_export_nodes(scene,objects,surfaces)
    target.mkdir(parents=True)
    files={meta['input_image'],info['asset']}
    for obj in meta['objects']:
        for key in ('mask','asset'):
            if obj.get(key):files.add(obj[key])
    for name in files:
        (target/name).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/name,target/name)
    scene.export(target/'scene.glb')
    meta['structure']['surfaces']=surfaces;meta['background']=surfaces
    meta['assembly'].update(groups=groups,bounds=scene.bounds.tolist(),geometry_nodes=len(scene.graph.nodes_geometry))
    meta['placement']['scene_sha256']=sha(target/'scene.glb')
    report=dict(source_scene_sha256=digest,pointmap_sha256=info['sha256'],
        valid_depth_pixels=int(valid.sum()),unclaimed_pixels=int(selected.sum()),
        previous_context_faces=previous_context,context_faces=len(mesh.faces) if mesh is not None else 0,
        fresh_gpu_inference=False,quality_gate_passed=False,pose_revalidation='pending',
        classified_room_surfaces_unchanged=True,uses_object_names=False)
    meta['structure']['background_experiment']=report
    write(target/'scene_metadata.json',meta);write(target/'background_review.json',report)
    assert sha(source/'scene.glb')==digest
    print(report,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('--target',type=Path,required=True)
    a=p.parse_args();main(a.source,a.target)
