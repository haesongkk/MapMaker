"""Experimental mean-up -> VLM floor anchors -> VLM support placement.

Only GLB node matrices change. Binary geometry/material buffers remain byte-identical.
"""
import hashlib
import json
import struct
from pathlib import Path

import numpy as np
import trimesh

from .baseline_assembly import read_header
from .scene_run import read, write, sha
from .scene_relations import local_file
from .scene_geometry import HorizontalSurface, contact_footprint


def mean_up(matrices):
    matrices = np.asarray(matrices, dtype=float)
    if matrices.ndim != 3 or matrices.shape[1:] != (4, 4) or not np.isfinite(matrices).all():
        raise ValueError('Expected finite object matrices')
    vectors = matrices[:, :3, 1]
    lengths = np.linalg.norm(vectors, axis=1)
    if np.any(lengths <= 1e-12):
        raise ValueError('Degenerate object up')
    vectors = vectors / lengths[:, None]
    average = vectors.mean(axis=0)
    agreement = float(np.linalg.norm(average))
    if agreement < 1e-6:
        raise ValueError('Mean up cancels; no defined world up')
    up = average / agreement
    rotation = trimesh.geometry.align_vectors(up, [0, 1, 0])
    return rotation, dict(method='all_generated_objects_equal_weight_normalized_up_mean',
                         up_before=up.tolist(), up_after=(rotation[:3,:3]@up).tolist(),
                         mean_length=agreement, object_count=len(matrices),
                         rotation_degrees=float(np.degrees(np.arccos(np.clip(up[1],-1,1)))),
                         deviations_degrees=np.degrees(np.arccos(np.clip(vectors@up,-1,1))).tolist())


def node_matrix(node):
    if 'matrix' in node:
        return np.asarray(node['matrix']).reshape(4,4).T
    q = node.get('rotation',[0,0,0,1])
    m = trimesh.transformations.quaternion_matrix([q[3],*q[:3]])
    m[:3,:3] *= np.asarray(node.get('scale',[1,1,1]))[None,:]
    m[:3,3] = node.get('translation',[0,0,0])
    return m


def write_scene(source, destination, matrices, *, omit=()):
    """Replace direct object root transforms in baseline GLB, stream untouched binary."""
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError('Refusing to overwrite scene')
    document, offset, size = read_header(source)
    found = set()
    for node in document['nodes']:
        name = node.get('name')
        if name in matrices:
            m = np.asarray(matrices[name])
            if m.shape != (4,4) or not np.isfinite(m).all():
                raise ValueError('Invalid scene transform')
            if name in found:
                raise ValueError('Duplicate object root')
            for key in ('rotation','translation','scale'):
                node.pop(key,None)
            node['matrix'] = m.T.reshape(-1).tolist()
            found.add(name)
    if found != set(matrices):
        raise ValueError('Missing object roots')
    omitted=set(omit)
    if not omitted<=found:raise ValueError('Unknown omitted object')
    if omitted:
        for node in document['nodes']:
            if 'children' in node:
                node['children']=[i for i in node['children'] if document['nodes'][i].get('name') not in omitted]
    payload = json.dumps(document,separators=(',',':'),allow_nan=False).encode()
    payload += b' '*(-len(payload)%4)
    if 28+len(payload)+size >= 2**32:
        raise ValueError('GLB size limit')
    destination.parent.mkdir(parents=True,exist_ok=True)
    before, after = hashlib.sha256(), hashlib.sha256()
    with source.open('rb') as inp, destination.open('wb') as out:
        out.write(struct.pack('<4sII',b'glTF',2,28+len(payload)+size))
        out.write(struct.pack('<II',len(payload),0x4E4F534A)); out.write(payload)
        out.write(struct.pack('<II',size,0x004E4942)); inp.seek(offset)
        for chunk in iter(lambda:inp.read(1024**2),b''):
            before.update(chunk);out.write(chunk)
    _, new_offset, _ = read_header(destination)
    with destination.open('rb') as out:
        out.seek(new_offset)
        for chunk in iter(lambda:out.read(1024**2),b''):
            after.update(chunk)
    if before.digest()!=after.digest():
        raise ValueError('Binary preservation failed')
    return dict(binary_preserved=True,binary_sha256=before.hexdigest(),scene_sha256=sha(destination),omitted_objects=sorted(omitted))


def load_run(run):
    run = Path(run)
    meta = read(run/'scene_metadata.json')
    if meta.get('execution',{}).get('mode') != 1:
        raise ValueError('This experiment expects mode 1')
    objects = [o for o in meta['objects'] if o.get('status')=='generated']
    if not objects or len({o['id'] for o in objects}) != len(objects):
        raise ValueError('No objects or duplicate IDs')
    document,_,_ = read_header(run/'scene.glb')
    names = {n.get('name'):n for n in document['nodes']}
    # Current baseline assembly has an identity scene root and direct object children.
    roots = document['scenes'][document.get('scene',0)]['nodes']
    if len(roots)!=1 or not np.allclose(node_matrix(document['nodes'][roots[0]]),np.eye(4)):
        raise ValueError('Expected identity baseline root')
    children = {document['nodes'][i].get('name') for i in document['nodes'][roots[0]].get('children',[])}
    matrices = {}
    for obj in objects:
        oid = obj['id']
        if oid not in children:
            raise ValueError('Expected direct object child')
        m = np.asarray(obj['transform']['matrix'])
        if not np.allclose(m,node_matrix(names[oid]),atol=1e-6):
            raise ValueError('Pose/GLB mismatch')
        matrices[oid] = m
        asset = local_file(run,obj['asset'])
        if obj.get('asset_sha256') and sha(asset)!=obj['asset_sha256']:
            raise ValueError('Object asset changed')
    return meta, objects, matrices


def geometry(run, objects, matrices):
    """Load only vertex/index arrays, without material images, one object at a time."""
    result = {}
    for obj in objects:
        asset = trimesh.load(Path(run)/obj['asset'],force='scene',process=False,skip_materials=True)
        points, faces = [], []
        count = 0
        for node in asset.graph.nodes_geometry:
            child, name = asset.graph[node]
            mesh = asset.geometry[name]
            v = trimesh.transform_points(mesh.vertices,matrices[obj['id']]@child)
            points.append(v);faces.append(mesh.faces+count);count+=len(v)
        if not points:
            raise ValueError('Empty object geometry')
        result[obj['id']] = (np.concatenate(points),np.concatenate(faces))
    return result


def initialize(run, output):
    run, output = Path(run).resolve(),Path(output).resolve()
    if output.exists() or output.is_relative_to(run):
        raise ValueError('Choose a fresh output outside the source run')
    meta, objects, matrices = load_run(run)
    rotation, evidence = mean_up(list(matrices.values()))
    upright = {key:rotation@m for key,m in matrices.items()}
    output.mkdir(parents=True)
    evidence.update(write_scene(run/'scene.glb',output/'upright.glb',upright))
    write(output/'state.json',dict(source=str(run),source_metadata_sha256=sha(run/'scene_metadata.json'),
          source_scene_sha256=sha(run/'scene.glb'),objects=objects,
          upright={key:m.tolist() for key,m in upright.items()},world_rotation=rotation.tolist(),
          up_evidence=evidence))
    return evidence


def floor_align(geo, matrices, floor_ids):
    if not floor_ids or not set(floor_ids)<=set(geo):
        raise ValueError('No valid floor anchors')
    bottoms={k:float(v[0][:,1].min()) for k,v in geo.items()}
    level=float(np.median([bottoms[k] for k in floor_ids]))
    updated={k:np.asarray(m).copy() for k,m in matrices.items()}
    shifts={}
    for key,m in updated.items():
        dy=-bottoms[key] if key in floor_ids else -level
        m[1,3]+=dy;shifts[key]=dy
    return updated,dict(floor_y=0.,original_floor_height=level,anchor_ids=floor_ids,
                       anchor_bottoms={k:bottoms[k] for k in floor_ids},shifts=shifts,
                       method='median_anchor_bottom_plane_then_vertical_anchor_contact')


def contact_candidates(geo, floor_ids, tolerance):
    surfaces={k:HorizontalSurface(v[f]) for k,(v,f) in geo.items()}
    candidates=[]; evidence={}
    for key,(v,f) in geo.items():
        if key in floor_ids:continue
        feet=contact_footprint(v)
        bottom=float(v[:,1].min())
        hits=[]
        for sid,surface in surfaces.items():
            if sid==key:continue
            offsets=[h-p[1] for p in feet if (h:=surface.height(p[[0,2]],maximum=p[1]+tolerance)) is not None]
            if offsets and abs(max(offsets))<=tolerance:hits.append(sid)
        evidence[key]=dict(bottom=bottom,contact_ids=hits,
                           floor_gap=bottom,candidate=not hits and bottom>tolerance)
        if evidence[key]['candidate']:candidates.append(key)
    return candidates,evidence


def settle_on(vertices, target_faces, tolerance):
    """Vertical first contact against the finite mesh, with broad footprint coverage.

    No rotation, scale or horizontal snapping. No claim of complete collision freedom.
    """
    feet=contact_footprint(vertices)
    bottom=float(vertices[:,1].min())
    extent=max(float(np.linalg.norm(np.ptp(vertices,axis=0))),1e-6)
    surface=HorizontalSurface(target_faces)
    limit=extent*.75
    offsets=[h-p[1] for p in feet if (h:=surface.height(p[[0,2]],maximum=bottom+limit)) is not None]
    if len(offsets)<max(3,int(np.ceil(len(feet)*.5))):
        return None,dict(reason='insufficient_support_footprint',hits=len(offsets),queries=len(feet))
    dy=float(max(offsets))
    if abs(dy)>limit:
        return None,dict(reason='excessive_vertical_motion',dy=dy,limit=limit)
    return dy,dict(reason='vertical_first_contact',dy=dy,footprint_coverage=len(offsets)/len(feet),
                   contact_spread=float(np.ptp(offsets)),tolerance=tolerance,
                   limitation='surface contact proxy; no full collision or center-of-mass guarantee')
