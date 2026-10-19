"""Replay saved spatial runs in a new directory, preserving all source hashes."""
import argparse
from pathlib import Path
import shutil
from mapmaker.scene_run import read, write, sha
from mapmaker.scene_placement import finalize_scene


def replay(sources, output):
    output.mkdir(parents=True, exist_ok=False)
    write(output/'provenance.json', {str(p):sha(p) for p in Path('mapmaker').glob('*.py')})
    reports = []
    for source in sources:
        meta = read(source/'scene_metadata.json')
        target = output/source.name; target.mkdir()
        files = {'scene.glb','scene_metadata.json',meta['input_image'],meta['pointmap']['asset']}
        files.update(o['mask'] for o in meta['objects'] if o.get('mask'))
        before = {f:sha(source/f) for f in files}
        for f in files:
            (target/f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source/f, target/f)
        finalize_scene(target, render=False)
        result = read(target/'scene_metadata.json')
        digest = sha(target/'scene.glb'); finalize_scene(target, render=False)
        assert digest == sha(target/'scene.glb')
        assert before == {f:sha(source/f) for f in files}
        report = dict(run_id=source.name, source_hashes=before, source_unchanged=True,
            idempotent=True, new_gpu_inference=False, scene_sha256=digest,
            generated=sum(o['status']=='generated' for o in result['objects']),
            structural_regions=[o['id'] for o in result['objects'] if o['status']=='structural'],
            duplicates=result['geometric_mask_selection']['decisions'],
            contact_changes=result['placement']['contacts']['changes'],
            surfaces=result['structure']['surfaces'])
        reports.append(report); write(output/'summary.json', reports)
        print(dict(run=source.name, objects=report['generated'], structural=report['structural_regions'],
                   contacts=len(report['contact_changes'])), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('sources', nargs='+', type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args(); replay(a.sources,a.output)
