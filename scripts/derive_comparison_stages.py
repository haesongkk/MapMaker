"""Derive corrected objects and identical objects plus space from stage 2."""
import argparse
import copy
import hashlib
from pathlib import Path
import shutil
import sys
import json

ROOT=Path(__file__).resolve().parents[1]
FROZEN=ROOT/'.runtime/four-way-comparison/profiles/correction'
sys.path.insert(0,str(FROZEN))
from mapmaker.scene_run import read,write,sha
from mapmaker.scene_replay import rebuild_inference_scene
from mapmaker.scene_placement import finalize_scene
import mapmaker.scene_placement as placement_module
import numpy as np
import trimesh


def object_signature(scene,objects):
    result={}
    ids={o['id'] for o in objects if o.get('status')=='generated'}
    for node in scene.graph.nodes_geometry:
        parent=node
        while parent not in ids and parent!=scene.graph.base_frame:
            parent=scene.graph.transforms.parents.get(parent,scene.graph.base_frame)
        if parent not in ids:continue
        transform,name=scene.graph[node];mesh=scene.geometry[name]
        result[node]=dict(transform=np.asarray(transform).tolist(),
            vertices=hashlib.sha256(np.asarray(mesh.vertices).tobytes()).hexdigest(),
            faces=hashlib.sha256(np.asarray(mesh.faces).tobytes()).hexdigest())
    return result


def main(sample):
    assert FROZEN in Path(placement_module.__file__).parents
    manifest=read(FROZEN/'manifest.json')
    assert all(sha(FROZEN/n)==h for n,h in manifest['files'].items())
    root=ROOT/'.runtime/four-way-comparison';source=root/'results'/sample/'2'
    four=root/'results'/sample/'4';three=root/'results'/sample/'3'
    before={name:sha(source/name) for name in ('scene.glb','scene_metadata.json')}
    if not four.exists():
        rebuild_inference_scene(source,four)
        write(four/'comparison-progress.json',dict(stage='correction_started',complete=False))
    if not (four/'comparison-complete.json').exists():
        result=finalize_scene(four,render=False,supported_repair=True,overlap_repair=True)
        write(four/'comparison-complete.json',dict(complete=True,scene_sha256=result['scene_sha256'],
            correction_profile_sha256=manifest['sha256'],source_sha256=before))
    meta=read(four/'scene_metadata.json');scene=trimesh.load(four/'scene.glb',force='scene',process=False)
    expected=object_signature(scene,meta['objects'])
    for surface in meta['structure']['surfaces']:
        node=surface['node']
        if node in scene.graph.nodes_geometry:
            _,name=scene.graph[node];scene.delete_geometry(name)
            scene.graph.transforms.remove_node(node)
    assert object_signature(scene,meta['objects'])==expected
    three.mkdir(exist_ok=False)
    for name in [meta['input_image']]:
        path=three/name;path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(four/name,path)
    scene.export(three/'scene.glb')
    reloaded=trimesh.load(three/'scene.glb',force='scene',process=False)
    # GLB float32 roundtripping may alter local arrays; compare world geometry
    # against the same export precision on both sides.
    for node in expected:
        np.testing.assert_allclose(reloaded.graph[node][0],scene.graph[node][0],rtol=1e-6,atol=1e-7)
        a=scene.geometry[scene.graph[node][1]];b=reloaded.geometry[reloaded.graph[node][1]]
        np.testing.assert_array_equal(a.faces,b.faces)
        np.testing.assert_allclose(a.vertices,b.vertices,rtol=1e-6,atol=1e-7)
    meta3=copy.deepcopy(meta);meta3['structure']=dict(status='hidden_for_comparison',surfaces=[])
    meta3['background']=[];meta3['pipeline']['structural_geometry']=False
    meta3['placement']['scene_sha256']=sha(three/'scene.glb')
    meta3['comparison']=dict(stage=3,space_used_for_correction=True,space_exported=False,
        same_objects_as_stage4=True)
    write(three/'scene_metadata.json',meta3)
    assert all(sha(source/n)==h for n,h in before.items())
    assert all(sha(FROZEN/n)==h for n,h in manifest['files'].items())
    write(three/'comparison-complete.json',dict(complete=True,object_nodes=len(expected),
        same_objects_as_stage4=True,source_unchanged=True,snapshot_unchanged=True))
    print(sample,'stages 3 and 4 complete',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('sample');main(p.parse_args().sample)
