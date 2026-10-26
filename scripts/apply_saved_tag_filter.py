"""Apply Qwen tag decisions to existing objects without GPU inference."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from mapmaker.scene_run import read, write, sha
from mapmaker.baseline_assembly import assemble_streamed, read_header
from mapmaker.global_upright import node_matrix
from mapmaker.qwen_background_filter import parse_response

ASSETS = ROOT / 'docs/assets/ram-qwen-filter-v1'


def main(version='v1'):
    assets = ROOT / f'docs/assets/ram-qwen-filter-{version}'
    prefix = 'ram-filter' if version == 'v1' else f'ram-filter-{version}'
    evidence = read(assets / 'results.json')
    manifest, viewers = {}, {}
    for record in evidence['samples']:
        name = record['sample']
        source = ROOT / record['source_run']
        target = ROOT / f'.runtime/ram-qwen-filter-{version}/scenes' / name
        if target.exists():
            raise ValueError(f'Refusing overwrite: {target}')
        meta = read(source / 'scene_metadata.json')
        assert sha(source / 'scene_metadata.json') == record['source_metadata_sha256']
        assert sha(source / 'object_candidates.json') == record['source_candidates_sha256']
        kept_tags = parse_response(record['raw_response'], record['raw_tags'], allow_trailing_explanation=True)
        assert kept_tags == record['kept_tags']
        remaining = Counter(kept_tags)
        kept_indices = set()
        for index, tag in enumerate(record['raw_tags']):
            if remaining[tag]:
                kept_indices.add(index)
                remaining[tag] -= 1
        original, _, _ = read_header(source / 'scene.glb')
        nodes = {node.get('name'): node for node in original['nodes']}
        selected, removed = [], []
        for obj in meta['objects']:
            assert obj['name'] == record['raw_tags'][obj['prompt_index']]
            (selected if obj['prompt_index'] in kept_indices else removed).append(copy.deepcopy(obj))
        generated = [obj for obj in selected if obj['status'] == 'generated']
        target.mkdir(parents=True)
        for obj in selected:
            for field in ('asset', 'mask'):
                if field not in obj:
                    continue
                src = source / obj[field]
                dst = target / obj[field]
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.link(src, dst)
            if obj['status'] == 'generated':
                assert sha(source / obj['asset']) == obj['asset_sha256']
                assert np.allclose(node_matrix(nodes[obj['id']]), obj['transform']['matrix'], atol=1e-6)
        shutil.copytree(source / 'input', target / 'input')
        assembly_objects = copy.deepcopy(generated)
        for obj in assembly_objects:
            obj['pose'] = {'matrix': obj['transform']['matrix']}
        if assembly_objects:
            assemble_streamed(target, assembly_objects, matrix_for_pose=lambda pose: pose['matrix'])
        else:
            import struct
            doc = dict(asset={'version':'2.0'}, scene=0, scenes=[{'nodes':[0]}],
                       nodes=[{'name':'Scene'}], buffers=[{'byteLength':4}])
            encoded=json.dumps(doc).encode('utf-8'); encoded+=b' '*(-len(encoded)%4)
            (target/'scene.glb').write_bytes(struct.pack('<4sII',b'glTF',2,32+len(encoded))+
                struct.pack('<II',len(encoded),0x4E4F534A)+encoded+
                struct.pack('<II',4,0x004E4942)+b'\x00'*4)
        rebuilt, _, _ = read_header(target / 'scene.glb')
        rebuilt_nodes = {node.get('name'): node for node in rebuilt['nodes']}
        assert not any(obj['id'] in rebuilt_nodes for obj in removed)
        for obj in generated:
            assert np.allclose(node_matrix(rebuilt_nodes[obj['id']]), obj['transform']['matrix'], atol=1e-6)
        item = dict(source_run=record['source_run'], target_run=target.relative_to(ROOT).as_posix(),
                    source_scene_sha256=sha(source / 'scene.glb'), scene_sha256=sha(target / 'scene.glb'),
                    objects_before=len(meta['objects']), objects_after=len(selected),
                    removed_objects=[dict(id=o['id'], tag=o['name']) for o in removed],
                    kept_object_ids=[o['id'] for o in selected], removed_tags=record['removed_tags'],
                    kept_tags=kept_tags, geometry_and_textures_reused=True,
                    original_transform_matrices_preserved=True, gpu_inference=False)
        derived = copy.deepcopy(meta)
        derived['objects'] = selected
        derived['source_run_id'] = meta['run_id']
        derived['run_id'] = f'ram-qwen-filter-{version}-{name}'
        derived.pop('scene_url', None)
        derived['tag_filter_derivation'] = item
        derived['scene_asset'] = 'scene.glb'
        write(target / 'scene_metadata.json', derived)
        write(target / 'object_candidates.json', dict(raw_tags=record['raw_tags'], candidates=kept_tags,
                                                     rejected=record['removed_tags'], policy=f'qwen_background_filter_{version}'))
        manifest[name] = item
        viewers[f'{prefix}-{name}-before'] = record['source_run']
        viewers[f'{prefix}-{name}-after'] = item['target_run']
        write(assets / 'scene-manifest.json', manifest)
        write(assets / 'viewers.json', viewers)
        print(name, item['objects_before'], '->', item['objects_after'], flush=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', choices=['v1', 'v2', 'v3', 'movable', 'furniture'], default='v1')
    main(parser.parse_args().version)
