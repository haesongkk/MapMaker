"""Final-pose collision evidence for rigid candidates; no scene edits."""
import argparse
from pathlib import Path
import numpy as np
import trimesh
from mapmaker.scene_geometry import triangles
from mapmaker.scene_collision import MeshIndex
from mapmaker.scene_run import read, write, sha


def main(source, proposals, projection, output):
    digest = sha(source/'scene.glb')
    assert read(proposals)['source_scene_sha256'] == read(projection)['source_scene_sha256'] == digest
    meta = read(source/'scene_metadata.json')
    scene = trimesh.load(source/'scene.glb', force='scene', process=False)
    faces = {o['id']: triangles(scene, o['id']) for o in meta['objects'] if o['status']=='generated'}
    for surface in meta.get('structure', {}).get('surfaces', []):
        faces[surface['node']] = triangles(scene, surface['node'])
    allowed = {p['object_id'] for p in read(projection)['reports'] if p['compatible']}
    indices = {}
    reports = []
    for proposal in read(proposals)['proposals']:
        oid = proposal['object_id']
        if not proposal['proposed'] or oid not in allowed:
            continue
        transformed = trimesh.transform_points(faces[oid].reshape(-1,3), proposal['transform']).reshape(-1,3,3)
        bounds = np.array([transformed.min((0,1)), transformed.max((0,1))])
        checks = []
        for sid, other in faces.items():
            if sid == oid:
                continue
            ob = np.array([other.min((0,1)), other.max((0,1))])
            if np.any(np.minimum(bounds[1], ob[1])-np.maximum(bounds[0],ob[0]) <= 0):
                continue
            if sid not in indices:
                if len(indices) >= 4:
                    indices.pop(next(iter(indices)))
                indices[sid] = MeshIndex(other)
            surface_hit = indices[sid].swept_collision(transformed, np.zeros(3), check_containment=False)
            closed = bool(indices[sid].mesh.is_watertight and indices[sid].mesh.is_winding_consistent)
            contained = indices[sid].penetration_samples(transformed, meta['placement']['contact_tolerance'])
            checks.append(dict(other_id=sid, surface_intersection=surface_hit,
                other_closed=closed, sampled_inside=contained))
        reports.append(dict(object_id=oid, checks=checks,
            final_surfaces_clear=all(c['surface_intersection'] is False for c in checks)))
        write(output, dict(source_scene_sha256=digest, reports=reports,
            scope='Final pose only; motion path and reverse containment remain unchecked'))
        print(dict(object_id=oid, checks=len(checks),
            intersections=sum(c['surface_intersection'] is True for c in checks),
            unknown=sum(c['surface_intersection'] is None for c in checks)), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('--proposals', type=Path, required=True)
    p.add_argument('--projection', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    main(a.source,a.proposals,a.projection,a.output)
