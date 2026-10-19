"""Rebuild immutable inference assets for genuine CPU correction experiments."""
import copy
from pathlib import Path
import shutil

import numpy as np
import trimesh

from .scene_assembly import NATIVE_TO_GLB_ROW
from .scene_placement import update_transform
from .scene_run import read, write, sha


def pose_matrix(pose):
    """CPU equivalent of the stored SAM3D scale/rotation/translation pose."""
    rotation = trimesh.transformations.quaternion_matrix(np.asarray(pose['rotation']).reshape(4))
    # PyTorch3D Transform3d composes row-vector rotations; the official assembly
    # transposes that composed matrix before undoing the exported vertex axes.
    rotation[:3, :3] = rotation[:3, :3].T
    rotation[:3, :3] *= np.asarray(pose['scale']).reshape(3)[None, :]
    rotation[:3, 3] = np.asarray(pose['translation']).reshape(3)
    undo_export = np.eye(4)
    undo_export[:3, :3] = NATIVE_TO_GLB_ROW
    return rotation @ undo_export


def rebuild_inference_scene(source, target):
    """Restore even asset-backed objects removed by previous correction passes.

    Never relabel a finalized scene as an old version: that loses removed meshes
    and silently contaminates ablations. Refuse missing or altered source assets.
    """
    source, target = Path(source).resolve(), Path(target).resolve()
    if target == source or source in target.parents:
        raise ValueError('Replay output must be separate from source')
    original = read(source / 'scene_metadata.json')
    meta = copy.deepcopy(original)
    files = {meta['input_image']: meta['input_sha256']}
    if meta.get('pointmap'):
        files[meta['pointmap']['asset']] = meta['pointmap']['sha256']
    matrices = {}
    for obj in meta['objects']:
        if obj.get('mask'):
            files[obj['mask']] = obj['mask_sha256']
        expansion=obj.get('mask_expansion',{})
        if expansion.get('original_mask'):
            name=expansion['original_mask'];expected=expansion.get('original_sha256')
            if not expected or (name in files and files[name]!=expected):
                raise ValueError('Invalid original mask provenance for replay')
            files[name]=expected
        if not obj.get('asset'):
            continue
        files[obj['asset']] = obj['asset_sha256']
        review = obj.get('reconstruction_review', {})
        for kind in ('original_artifact', 'alternative_artifact'):
            candidate = review.get(kind)
            if candidate:
                files[candidate['asset']] = candidate['sha256']
                files[candidate['pose']] = candidate['pose_sha256']
        matrix = pose_matrix(obj['pose'])
        recorded = obj.get('placement', {}).get('original_matrix')
        if recorded is not None and not np.allclose(matrix, recorded, atol=1e-5):
            raise ValueError(f"CPU pose differs from official recorded transform: {obj['id']}")
        matrices[obj['id']] = np.asarray(recorded) if recorded is not None else matrix
    for name, expected in files.items():
        path = (source / name).resolve()
        if source not in path.parents or sha(path) != expected:
            raise ValueError(f'Invalid replay source asset: {name}')
    target.mkdir(parents=True, exist_ok=False)
    for name in files:
        (target / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target / name)
    scene = trimesh.Scene(base_frame='Scene')
    restored = []
    for obj in meta['objects']:
        if obj['id'] not in matrices:
            continue
        oid = obj['id']
        for key in ('placement', 'structural_evidence', 'duplicate_of', 'geometry_source'):
            obj.pop(key, None)
        obj['status'] = 'generated'
        obj.setdefault('transform', {})
        update_transform(obj, matrices[oid])
        scene.graph.update(frame_from='Scene', frame_to=oid, matrix=matrices[oid])
        asset = trimesh.load(source / obj['asset'], force='scene', process=False)
        for index, node in enumerate(asset.graph.nodes_geometry):
            matrix, name = asset.graph[node]
            scene.add_geometry(asset.geometry[name].copy(), node_name=f'{oid}__{index}',
                geom_name=f'{oid}__geometry_{index}', parent_node_name=oid, transform=matrix)
        restored.append(oid)
    for key in ('placement', 'structure', 'background', 'projection_context_review',
                'reconstructed_composite_review', 'geometric_mask_selection'):
        meta.pop(key, None)
    scene.export(target / 'scene.glb')
    write(target / 'scene_metadata.json', meta)
    write(target / 'replay_provenance.json', dict(source=str(source),
        source_metadata_sha256=sha(source / 'scene_metadata.json'),
        inference_asset_hashes=files, restored_object_ids=restored,
        fresh_gpu_inference=False, source_unchanged=all(sha(source / f) == h for f, h in files.items())))
    return meta
