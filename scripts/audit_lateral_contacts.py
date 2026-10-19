"""Read-only test of bounded lateral support alignment on recovered meshes."""
from pathlib import Path
import argparse
import numpy as np
import trimesh
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_geometry import triangles, contact_footprint, support_translation, HorizontalSurface
from mapmaker.scene_placement import object_vertices


def main(source, output):
    meta = read(source/'scene_metadata.json')
    scene = trimesh.load(source/'scene.glb', force='scene', process=False)
    digest = sha(source/'scene.glb')
    objects = {o['id']: o for o in meta['objects'] if o['status'] == 'generated'}
    vertices = {key: object_vertices(scene, key) for key in objects}
    faces = {key: triangles(scene, key) for key in objects}
    indices, queries = {}, {}
    candidates = []
    counts = dict(reviewed=0, near_pairs=0)
    for rejection in meta['placement']['contacts']['rejections']:
        if rejection['reason'] != 'missing_support_surface':
            continue
        oid, sid = rejection['object_id'], rejection['candidate_id']
        if oid not in objects or sid not in objects:
            continue
        counts['reviewed'] += 1
        v, f = vertices[oid], faces[sid]
        size, extent = np.ptp(vertices[sid], axis=0), np.ptp(v, axis=0)
        limit = min(.2*max(float(min(size[[0,2]])), float(extent[1]), 1e-6), .8*max(float(max(extent)), 1e-6))
        # An early box test only skips impossible candidates, never certifies one.
        if np.any(v.max(0)+limit < vertices[sid].min(0)) or np.any(vertices[sid].max(0)+limit < v.min(0)):
            continue
        counts['near_pairs'] += 1
        if sid not in indices:
            normal = np.cross(f[:,1]-f[:,0], f[:,2]-f[:,0])
            horizontal = abs(normal[:,1]) >= .85*np.linalg.norm(normal, axis=1)
            selected = f[horizontal]
            if not len(selected):
                indices[sid] = None
                continue
            indices[sid] = trimesh.Trimesh(selected.reshape(-1,3), np.arange(len(selected)*3).reshape(-1,3), process=False)
            queries[sid] = HorizontalSurface(f)
        if indices[sid] is None:
            continue
        feet = contact_footprint(v)
        nearest, distance, _ = trimesh.proximity.closest_point(indices[sid], feet)
        shifts = nearest-feet
        shifts[:,1] = 0
        options = []
        for shift, gap in zip(shifts, distance):
            if gap > limit or np.linalg.norm(shift) <= 1e-6 or np.linalg.norm(shift) > limit*.25:
                continue
            # Go slightly into the measured support, not merely its boundary.
            shift *= 1.05
            delta, evidence = support_translation(v+shift, f, limit,
                max(meta['placement']['contact_tolerance'], float(extent[1])*.02), surface=queries[sid])
            if delta is None:
                continue
            delta += shift
            if np.linalg.norm(delta) <= limit:
                options.append(dict(translation=delta.tolist(), norm=float(np.linalg.norm(delta)), evidence=evidence))
        if options:
            best = min(options, key=lambda x: x['norm'])
            candidates.append(dict(object_id=oid, support_id=sid, limit=limit, **best))
    assert sha(source/'scene.glb') == digest
    write(output, dict(source=str(source), source_sha256=digest, counts=counts,
        candidates=candidates, source_unchanged=True,
        limitation='Contact proposals only; collision and source-image/depth consistency not certified'))
    print(dict(source=source.name, counts=counts, candidates=len(candidates)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    main(args.source, args.output)
