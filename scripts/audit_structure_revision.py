"""Recompute room structure from completed runs, without changing their artifacts.

Reports geometry differences only. Changed surfaces still require downstream
pose/contact validation; this audit cannot certify the final assembled scene.
"""
import argparse
import hashlib
from pathlib import Path

import numpy as np
import trimesh

from mapmaker.scene_geometry import triangles
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_structure import restore_structure


def geometry(scene, surfaces):
    result = []
    for surface in surfaces:
        faces = triangles(scene, surface['node'])
        # Order-independent fingerprint at GLB's float32 storage precision.
        vertices = np.asarray(faces, dtype='<f4')
        canonical = []
        for face in vertices:
            canonical.append(face[np.lexsort(face.T[::-1])].ravel())
        canonical = np.asarray(canonical, dtype='<f4')
        canonical = canonical[np.lexsort(canonical.T[::-1])]
        result.append(dict(node=surface['node'], kind=surface['kind'],
            faces=len(faces), area=float(trimesh.triangles.area(faces).sum()),
            geometry_sha256=hashlib.sha256(canonical.tobytes()).hexdigest(),
            completion=surface.get('completion'),
            inferred_pixels=surface.get('inferred_pixels', 0)))
    return result


def audit(run):
    meta = read(run/'scene_metadata.json')
    original = sha(run/'scene.glb')
    assert original == meta['placement']['scene_sha256']
    scene = trimesh.load(run/'scene.glb', force='scene', process=False)
    before = geometry(scene, meta['structure']['surfaces'])
    rebuilt = trimesh.Scene()
    result = restore_structure(run, rebuilt, meta, meta['placement'])
    after = geometry(rebuilt, result['surfaces'])
    same = [(s['node'], s['geometry_sha256']) for s in before] == [
        (s['node'], s['geometry_sha256']) for s in after]
    assert sha(run/'scene.glb') == original
    return dict(run=str(run), source_scene_sha256=original, before=before, after=after,
        geometry_unchanged=same, downstream_replay_required=not same,
        source_unchanged=True, fresh_gpu_inference=False, quality_gate_passed=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Use a new audit directory')
    args.output.mkdir(parents=True)
    write(args.output/'implementation.json', {
        str(p): sha(p) for p in Path('mapmaker').glob('*.py')})
    reports = []
    for run in args.runs:
        report = audit(run)
        reports.append(report)
        write(args.output/'summary.json', reports)
        print(dict(run=run.name, geometry_unchanged=report['geometry_unchanged']), flush=True)
