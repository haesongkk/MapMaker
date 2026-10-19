"""Apply ranked retries to saved baselines without regenerating seed 42."""
import shutil
import numpy as np
import trimesh
from PIL import Image
from .scene_run import write, sha
from .reconstruction_review import reconstruct_with_review
from .reconstruction_schedule import ranked_depth_retries


def review_ranked_scene(run, meta, successful, outputs, generate, measure, pose_of, *, progress=None, context_guard=None):
    policy = meta['reconstruction_review']
    maximum = policy['maximum_extra_inferences']
    selected = ranked_depth_retries(successful, maximum)
    policy['scheduled_mask_hashes'] = [o['mask_sha256'] for o in selected]
    write(run/'scene_metadata.json', meta)
    budget = dict(remaining=maximum)
    positions = {o['id']: i for i, o in enumerate(successful)}
    for obj in selected:
        if progress: progress(obj, len(selected))
        mask = np.asarray(Image.open(run/obj['mask'])) > 0
        assert sha(run/obj['mask']) == obj['mask_sha256']
        assert sha(run/obj['asset']) == obj['asset_sha256']
        position = positions[obj['id']]
        original = dict(outputs[position], glb=trimesh.load(run/obj['asset'], force='scene', process=False))
        evidence = obj['reconstruction_review']['original']

        def preserve(candidate, seed):
            path = run/'objects/candidates'/obj['id']/f'seed_{seed}.glb'
            path.parent.mkdir(parents=True, exist_ok=True)
            if seed == 42: shutil.copyfile(run/obj['asset'], path)
            else: candidate['glb'].export(path)
            pose_path = path.with_suffix('.pose.json')
            write(pose_path, pose_of(candidate))
            return dict(asset=path.relative_to(run).as_posix(), sha256=sha(path),
                pose=pose_path.relative_to(run).as_posix(), pose_sha256=sha(pose_path))

        result, review = reconstruct_with_review(
            lambda seed: original if seed == 42 else generate(obj, mask, seed),
            lambda candidate: evidence if candidate is original else measure(candidate, mask),
            preserve, budget,
            context_guard=(lambda old,new: context_guard(obj,old,new)) if context_guard is not None else None)
        obj['reconstruction_review'] = review
        if review['selected_seed'] == 43:
            shutil.copyfile(run/review['alternative_artifact']['asset'], run/obj['asset'])
            obj['pose'] = pose_of(result)
            write(run/'objects'/f"{obj['id']}.pose.json", obj['pose'])
            obj['asset_sha256'] = sha(run/obj['asset'])
            outputs[position] = {k: result[k] for k in ('gaussian','rotation','translation','scale')}
        policy['extra_inferences_used'] = maximum-budget['remaining']
        write(run/'scene_metadata.json', meta)
