"""Lossless scene-wide up alignment and grounding for static baseline GLBs."""
import hashlib
import json
import shutil
import struct
from pathlib import Path

import numpy as np
from trimesh.transformations import quaternion_matrix

from .baseline_assembly import read_header
from .scene_placement import rotation_to_world_up


def consensus_up(vectors, threshold_degrees=30):
    vectors = np.asarray(vectors, dtype=float)
    lengths = np.linalg.norm(vectors, axis=1)
    if not np.isfinite(vectors).all() or np.any(lengths < 1e-10):
        raise ValueError('Invalid object up vectors')
    vectors = vectors / lengths[:, None]
    dots = np.clip(vectors @ vectors.T, -1, 1)
    # Angular medoid of the densest cone; each object receives one vote.
    cones = dots >= np.cos(np.radians(threshold_degrees))
    index = max(range(len(vectors)), key=lambda i: (int(cones[i].sum()), float(dots[i].sum())))
    included = cones[index]
    if included.sum() <= len(vectors) / 2:
        raise ValueError('No majority object-up consensus; refusing arbitrary rotation')
    up = vectors[included].mean(axis=0)
    up /= np.linalg.norm(up)
    return up, included, np.degrees(np.arccos(np.clip(vectors @ up, -1, 1)))


def node_matrix(node):
    if 'matrix' in node:
        return np.asarray(node['matrix']).reshape(4, 4).T
    q = node.get('rotation', [0, 0, 0, 1])
    matrix = quaternion_matrix([q[3], *q[:3]])
    matrix[:3, :3] *= np.asarray(node.get('scale', [1, 1, 1]))[None, :]
    matrix[:3, 3] = node.get('translation', [0, 0, 0])
    return matrix


def scene_bounds(path, document, offset, common):
    """Visit real POSITION values, not rotated axis-aligned bounding boxes."""
    binary = np.memmap(path, mode='r', dtype=np.uint8)
    bounds = np.array([[np.inf]*3, [-np.inf]*3])
    def visit(index, parent):
        node = document['nodes'][index]
        matrix = parent @ node_matrix(node)
        if 'mesh' in node:
            for primitive in document['meshes'][node['mesh']]['primitives']:
                accessor = document['accessors'][primitive['attributes']['POSITION']]
                if accessor['componentType'] != 5126 or accessor['type'] != 'VEC3' or 'sparse' in accessor or primitive.get('targets'):
                    raise ValueError('Expected static float32 POSITION accessor')
                view = document['bufferViews'][accessor['bufferView']]
                start = offset + view.get('byteOffset', 0) + accessor.get('byteOffset', 0)
                points = np.ndarray((accessor['count'], 3), dtype='<f4', buffer=binary,
                                    offset=start, strides=(view.get('byteStride', 12), 4))
                for begin in range(0, len(points), 100000):
                    world = points[begin:begin+100000] @ matrix[:3, :3].T + matrix[:3, 3]
                    if not np.isfinite(world).all():
                        raise ValueError('Non-finite vertices')
                    bounds[0] = np.minimum(bounds[0], world.min(axis=0))
                    bounds[1] = np.maximum(bounds[1], world.max(axis=0))
        for child in node.get('children', []):
            visit(child, matrix)
    for root in document['scenes'][document.get('scene', 0)]['nodes']:
        visit(root, common)
    if not np.isfinite(bounds).all():
        raise ValueError('Empty scene')
    return bounds


def digest(path, offset=0):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        stream.seek(offset)
        for chunk in iter(lambda: stream.read(1024**2), b''):
            h.update(chunk)
    return h.hexdigest()


def align(source, destination):
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError('Preserve the source run')
    path = source/'scene.glb'
    document, offset, size = read_header(path)
    metadata = json.loads((source/'scene_metadata.json').read_text(encoding='utf-8'))
    objects = [o for o in metadata['objects'] if o.get('status') == 'generated']
    matrices = [np.asarray(o['transform']['matrix']) for o in objects]
    names = {n.get('name'): n for n in document['nodes']}
    for obj, matrix in zip(objects, matrices):
        if not np.allclose(node_matrix(names[obj['id']]), matrix, atol=1e-6):
            raise ValueError('Metadata and GLB object matrix mismatch')
    up, included, deviations = consensus_up([m[:3, 1] for m in matrices])
    common = np.eye(4)
    common[:3, :3] = rotation_to_world_up(up)
    before = scene_bounds(path, document, offset, np.eye(4))
    rotated = scene_bounds(path, document, offset, common)
    common[1, 3] = -rotated[0, 1]
    roots = document['scenes'][document.get('scene', 0)]['nodes']
    document['scenes'][document.get('scene', 0)]['nodes'] = [len(document['nodes'])]
    document['nodes'].append(dict(name='global_up_and_ground', matrix=common.T.reshape(-1).tolist(), children=roots))
    destination.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(document, separators=(',', ':'), allow_nan=False).encode()
    encoded += b' '*(-len(encoded) % 4)
    target = destination/'scene.glb'
    with target.open('wb') as output, path.open('rb') as original:
        output.write(struct.pack('<4sII', b'glTF', 2, 28+len(encoded)+size))
        output.write(struct.pack('<II', len(encoded), 0x4E4F534A)); output.write(encoded)
        output.write(struct.pack('<II', size, 0x004E4942))
        original.seek(offset); shutil.copyfileobj(original, output, 1024**2)
    verified, new_offset, _ = read_header(target)
    after = scene_bounds(target, verified, new_offset, np.eye(4))
    binary_hash = digest(path, offset)
    if digest(target, new_offset) != binary_hash or abs(after[0, 1]) > 1e-7:
        raise ValueError('Binary preservation / grounding verification failed')
    evidence = dict(method='majority_30_degree_cone_equal_object_weight', local_up='+Y in exported object GLB',
        up_before=up.tolist(), up_after=(common[:3, :3]@up).tolist(),
        rotation_degrees=float(np.degrees(np.arccos(np.clip(up[1], -1, 1)))),
        common_transform=common.tolist(), translation_y=float(common[1, 3]),
        bounds_before=before.tolist(), bounds_after=after.tolist(),
        object_count=len(objects), consensus_count=int(included.sum()),
        objects=[dict(id=o['id'], name=o['name'], included=bool(keep), deviation_degrees=float(angle))
                 for o, keep, angle in zip(objects, included, deviations)],
        source_scene_sha256=digest(path), scene_sha256=digest(target), binary_sha256=binary_hash,
        binary_preserved=True, individual_correction=False)
    for obj, matrix in zip(objects, matrices):
        from .scene_placement import update_transform
        obj['original_transform'] = obj['transform']
        update_transform(obj, common @ matrix)
    metadata['global_upright'] = evidence
    metadata['source_run_id'] = metadata['run_id']
    metadata['run_id'] = hashlib.sha256(str(destination).encode()).hexdigest()[:32]
    metadata.pop('scene_url', None)
    (destination/'scene_metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    shutil.copytree(source/'input', destination/'input', dirs_exist_ok=True)
    return evidence
