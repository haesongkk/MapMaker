"""CPU ablations on frozen failed GPU runs. Does not measure new detection recall."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import zipfile
import numpy as np
import trimesh
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_placement import correct_placement, align_objects, finalize_scene
from mapmaker.scene_contacts import improve_contacts
from mapmaker.scene_structure import restore_structure
from mapmaker.scene_orientation import estimate_up


def summary(placement, structure):
    c = placement['contacts']
    return dict(changes=c['changes'], relations=c['relations'], unresolved=c['unresolved_props'],
                overlap_candidates=len(c['remaining_aabb_overlaps']),
                rejection_counts=c.get('rejection_counts'), orientation=placement.get('orientation_evidence'),
                surfaces=[dict(kind=s['kind'], observed_pixels=s.get('observed_pixels')) for s in structure['surfaces']])


def compare(source, output, baseline_contacts):
    original = read(source/'scene_metadata.json')
    digest = {f: sha(source/f) for f in ('scene.glb','scene_metadata.json','input/pointmap.npz')}
    reports = {'v6': summary(original['placement'], original['structure'])}
    for variant in ('contacts_only', 'orientation_and_surfaces_only'):
        scene = trimesh.load(source/'scene.glb', force='scene', process=False)
        meta = copy.deepcopy(original)
        objects = [o for o in meta['objects'] if o['status']=='generated']
        if variant == 'contacts_only':
            placement = meta['placement']
            # v6 holdout contains no contact changes; avoid accidental replay of a moved input.
            if placement['contacts']['changes']:
                raise ValueError('Contact ablation requires unchanged baseline poses')
            improve_contacts(scene, objects, placement, meta['structure'])
            structure = meta['structure']
        else:
            for o in objects:
                scene.graph.update(frame_from=scene.graph.base_frame, frame_to=o['id'], matrix=o['placement']['original_matrix'])
            for surface in meta['structure']['surfaces']:
                node = surface['node']; _, geometry = scene.graph[node]
                scene.delete_geometry(geometry); scene.graph.transforms.remove_node(node)
            orientation = estimate_up(np.load(source/'input/pointmap.npz')['points'])
            placement = correct_placement(scene, objects, orientation)
            align_objects(scene, objects, placement)
            structure = restore_structure(source, scene, meta, placement)
            baseline_contacts(scene, objects, placement, structure)
        reports[variant] = summary(placement, structure)
        write(output/f'{source.name}-{variant}.json', reports[variant])
        del scene
    target = output/'combined'/source.name
    target.mkdir(parents=True, exist_ok=False)
    files = {'scene.glb','scene_metadata.json',original['input_image'],original['pointmap']['asset']}
    files.update(o['mask'] for o in original['objects'] if o.get('mask'))
    for file in files:
        (target/file).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source/file, target/file)
    finalize_scene(target, render=False)
    result = read(target/'scene_metadata.json')
    reports['combined'] = summary(result['placement'], result['structure'])
    final_hash = sha(target/'scene.glb'); finalize_scene(target, render=False)
    assert sha(target/'scene.glb') == final_hash
    assert digest == {f: sha(source/f) for f in digest}
    report = dict(run_id=source.name, source_hashes=digest, source_unchanged=True,
                  new_gpu_inference=False, previously_seen_development_input=True,
                  quality_verdict='pending_visual_review', variants=reports)
    write(output/f'{source.name}.json', report)
    print(json.dumps(dict(run_id=source.name, variants={k:dict(changes=len(v['changes']),surfaces=len(v['surfaces'])) for k,v in reports.items()})), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('runs', nargs='+', type=Path)
    p.add_argument('--baseline-release', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args(); a.output.mkdir(parents=True, exist_ok=False)
    baseline = a.output/'baseline_contacts.py'
    with zipfile.ZipFile(a.baseline_release) as z:
        baseline.write_bytes(z.read('mapmaker/scene_contacts.py'))
    spec = importlib.util.spec_from_file_location('mapmaker._frozen_contacts', baseline)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    write(a.output/'provenance.json', dict(baseline_release_sha256=sha(a.baseline_release),
        baseline_contacts_sha256=sha(baseline), current={str(f):sha(f) for f in Path('mapmaker').glob('*.py')}))
    for run in a.runs:
        compare(run, a.output, module.improve_contacts)
