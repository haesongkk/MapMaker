"""Read-only candidate/contact diagnostics on saved GPU artifacts; no new inference."""
import argparse
import copy
import json
from pathlib import Path
import numpy as np
import trimesh
from PIL import Image
from mapmaker.mask_geometry import refine_selected
from mapmaker.scene_contacts import improve_contacts
from mapmaker.scene_run import sha


def audit(run):
    files = [run / 'scene.glb', run / 'scene_metadata.json', run / 'input/pointmap.npz']
    before = [sha(f) for f in files]
    meta = json.loads(files[1].read_text(encoding='utf-8'))
    points = np.load(files[2])['points']
    refined = copy.deepcopy(meta)
    rgb = np.asarray(Image.open(run / meta['input_image']).convert('RGB'))
    refine_selected(run, refined, points, rgb)
    scene = trimesh.load(files[0], force='scene', process=False)
    objects = [o for o in meta['objects'] if o['status'] == 'generated']
    placement = copy.deepcopy(meta['placement'])
    improve_contacts(scene, objects, placement, meta.get('structure'))
    assert [sha(f) for f in files] == before, 'Source artifact changed'
    return dict(run_id=run.name, source_hashes=dict(zip([f.name for f in files], before)),
                source_unchanged=True, new_gpu_inference=False,
                candidate_review=refined['geometric_mask_selection'],
                contacts=placement['contacts'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    summaries = []
    for run in args.runs:
        report = audit(run)
        (args.output / f'{run.name}.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        summary = dict(run_id=run.name, reviews=len(report['candidate_review']['candidate_reviews']),
                       suppressions=len(report['candidate_review']['decisions']),
                       rejection_counts=report['contacts']['rejection_counts'], source_unchanged=True)
        summaries.append(summary)
        print(json.dumps(summary), flush=True)
    (args.output / 'summary.json').write_text(json.dumps(summaries, indent=2), encoding='utf-8')
