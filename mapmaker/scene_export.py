"""Export object-only views without changing object geometry or transforms."""
import copy
from pathlib import Path
import shutil
import trimesh
from .scene_run import read, write, sha


def objects_only(source, target):
    source, target = Path(source), Path(target)
    meta = copy.deepcopy(read(source / 'scene_metadata.json'))
    scene = trimesh.load(source / 'scene.glb', force='scene', process=False)
    # Remove nodes, not shared geometry resources that objects might also use.
    for surface in meta.get('structure', {}).get('surfaces', []):
        node = surface['node']
        if node in scene.graph.nodes_geometry:
            scene.graph.transforms.remove_node(node)
    if source.resolve() != target.resolve():
        target.mkdir(parents=True, exist_ok=False)
        image = meta['input_image']
        (target / image).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / image, target / image)
    scene.export(target / 'scene.glb')
    meta['structure'] = dict(status='hidden_for_comparison', surfaces=[])
    meta['background'] = []
    meta['pipeline']['structural_geometry'] = False
    meta.setdefault('placement', {})['scene_sha256'] = sha(target / 'scene.glb')
    meta['execution'] = dict(mode=3, completed_mode=3)
    meta['comparison'] = dict(stage=3, space_used_for_correction=True,
                              space_exported=False, same_objects_as_stage4=True)
    write(target / 'scene_metadata.json', meta)


def finish_mode(run):
    """One finalization owner, running in the geometry-capable SAM3D worker."""
    from .execution_modes import requested
    from .scene_placement import finalize_scene
    meta = read(run / 'scene_metadata.json')
    selected = requested(meta)
    if selected is None:
        finalize_scene(run, render=False)
        return
    if selected.correct:
        finalize_scene(run, render=False, supported_repair=True, overlap_repair=True)
        if not selected.space:
            objects_only(run, run)
    meta = read(run / 'scene_metadata.json')
    meta['execution']['completed_mode'] = selected.number
    write(run / 'scene_metadata.json', meta)
