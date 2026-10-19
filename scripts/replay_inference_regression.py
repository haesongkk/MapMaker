"""Rebuild immutable inference assets before testing current geometry changes."""
import argparse
from pathlib import Path
from mapmaker.scene_replay import rebuild_inference_scene
from mapmaker.scene_placement import finalize_scene
from mapmaker.scene_run import read, write, sha


def main(sources, output, *, overlap_repair=False):
    output.mkdir(parents=True, exist_ok=False)
    write(output/'implementation.json', {str(p): sha(p) for p in Path('mapmaker').glob('*.py')})
    reports = []
    for source in sources:
        target = output/source.name
        rebuild_inference_scene(source, target)
        finalize_scene(target, render=False, overlap_repair=overlap_repair)
        result = read(target/'scene_metadata.json')
        contacts = result['placement']['contacts']
        report = dict(source=str(source), run=str(target), fresh_gpu_inference=False,
            objects=sum(o['status']=='generated' for o in result['objects']),
            surfaces=[dict(id=s['id'], kind=s['kind']) if 'id' in s else
                      dict(node=s['node'], kind=s['kind']) for s in result['structure']['surfaces']],
            contact_changes=contacts['changes'], source_checks=contacts['source_checks'],
            pose_changes=result['placement'].get('pose_refinement',{}).get('changes',[]),
            overlap_changes=result['placement'].get('overlap_refinement',{}).get('changes',[]),
            placement_version=result['placement']['version'],
            source_guard_enabled=contacts['source_guard_enabled'],
            scene_sha256=sha(target/'scene.glb'))
        reports.append(report)
        write(output/'summary.json', reports)
        print(dict(source=source.name, objects=report['objects'],
                   contact_changes=len(contacts['changes']), source_checks=len(contacts['source_checks'])), flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--overlap-repair', action='store_true', help='Enable native, source-validated static overlap repair')
    args=parser.parse_args()
    main(args.sources,args.output,overlap_repair=args.overlap_repair)
