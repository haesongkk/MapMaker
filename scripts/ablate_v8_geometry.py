"""Fixed-input CPU ablations. Does not claim fresh inference or held-out quality."""
import argparse
from contextlib import ExitStack
import importlib
import importlib.util
from pathlib import Path
import shutil
import sys
from unittest.mock import patch
import zipfile

from mapmaker.scene_placement import finalize_scene, PLACEMENT_VERSION
from mapmaker.scene_run import read, write, sha


def load_baseline(bundle, output):
    package = output/'frozen_v7'
    package.mkdir()
    with zipfile.ZipFile(bundle) as archive:
        for name in archive.namelist():
            path = Path(name)
            if path.parts[:1] == ('mapmaker',) and len(path.parts) == 2 and path.suffix == '.py':
                (package/path.name).write_bytes(archive.read(name))
    spec = importlib.util.spec_from_file_location('frozen_v7', package/'__init__.py', submodule_search_locations=[str(package)])
    module = importlib.util.module_from_spec(spec)
    sys.modules['frozen_v7'] = module
    spec.loader.exec_module(module)
    return {name: importlib.import_module('frozen_v7.'+name) for name in
            ('scene_orientation', 'mask_geometry', 'scene_geometry', 'scene_contacts')}


def main(args):
    for source in args.sources:
        if read(source/'scene_metadata.json').get('placement', {}).get('version') == PLACEMENT_VERSION:
            raise ValueError('Current-version finalized input would skip ablation; rebuild from inference assets first')
    args.output.mkdir(parents=True, exist_ok=False)
    baseline = load_baseline(args.baseline, args.output)
    write(args.output/'provenance.json', dict(baseline_sha256=sha(args.baseline),
        current={str(p):sha(p) for p in Path('mapmaker').glob('*.py')},
        fresh_gpu_inference=False, held_out=False))
    reports=[]
    for source in args.sources:
        original=read(source/'scene_metadata.json')
        files={'scene.glb','scene_metadata.json',original['input_image'],original['pointmap']['asset']}
        files.update(o['mask'] for o in original['objects'] if o.get('mask'))
        source_hashes={file:sha(source/file) for file in files}
        for variant in args.variants:
            target=args.output/variant/source.name
            target.mkdir(parents=True)
            for file in files:
                (target/file).parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source/file,target/file)
            if variant == 'names_removed':
                meta=read(target/'scene_metadata.json')
                for obj in meta['objects']:
                    obj.pop('name',None)
                write(target/'scene_metadata.json',meta)
            with ExitStack() as stack:
                if variant == 'without_vanishing':
                    stack.enter_context(patch('mapmaker.scene_orientation.estimate_up',
                        lambda points,image=None:baseline['scene_orientation'].estimate_up(points)))
                if variant == 'without_context':
                    stack.enter_context(patch('mapmaker.mask_geometry.refine_selected', baseline['mask_geometry'].refine_selected))
                if variant == 'without_contact_repairs':
                    def old_contacts(scene, objects, placement, structure=None, source_guard=None):
                        compatible = dict(structure or {}, surfaces=[s for s in (structure or {}).get('surfaces', [])
                            if s['kind'] in ('floor','wall','ceiling')])
                        return baseline['scene_contacts'].improve_contacts(scene, objects, placement, compatible)
                    stack.enter_context(patch('mapmaker.scene_contacts.improve_contacts', old_contacts))
                if variant == 'without_support_polygon':
                    stack.enter_context(patch('mapmaker.scene_contacts.support_translation', baseline['scene_geometry'].support_translation))
                if variant == 'without_finite_collision':
                    stack.enter_context(patch('mapmaker.scene_collision.MeshIndex', side_effect=ImportError('ablation: spatial queries disabled')))
                    stack.enter_context(patch('mapmaker.scene_pose_refinement.refine_poses',
                        return_value=dict(changes=[],ablation_disabled=True)))
                if variant == 'without_source_guard':
                    stack.enter_context(patch('mapmaker.scene_source_guard.contact_source_guard',return_value=None))
                if variant == 'without_unclaimed_background':
                    from mapmaker.scene_structure import restore_structure
                    stack.enter_context(patch('mapmaker.scene_structure.restore_structure',
                        lambda run,scene,meta,placement:restore_structure(run,scene,meta,placement,include_unclaimed=False)))
                if variant == 'without_ownership':
                    stack.enter_context(patch('mapmaker.scene_ownership.composite_residuals',return_value={}))
                if variant in ('without_registration','without_pose_refinement'):
                    stack.enter_context(patch('mapmaker.scene_pose_refinement.refine_poses',
                        return_value=dict(changes=[],ablation_disabled=True)))
                if variant == 'without_projection_context':
                    stack.enter_context(patch('mapmaker.scene_projection.route_inconsistent_context', return_value=[]))
                if variant == 'without_reconstructed_composites':
                    stack.enter_context(patch('mapmaker.scene_composite_review.review_reconstructed_composites', return_value=[]))
                finalize_scene(target,render=False)
            result=read(target/'scene_metadata.json')
            digest=sha(target/'scene.glb');finalize_scene(target,render=False)
            assert digest==sha(target/'scene.glb')
            if variant == 'names_removed':
                reference_root=getattr(args,'reference_root',None) or args.output/'combined'
                reference=read(reference_root/source.name/'scene_metadata.json')
                assert result['placement'] == reference['placement']
                assert result['structure'] == reference['structure']
                assert result.get('projection_context_review') == reference.get('projection_context_review')
                assert result.get('reconstructed_composite_review') == reference.get('reconstructed_composite_review')
                assert digest == sha(reference_root/source.name/'scene.glb')
            report=dict(run_id=source.name,variant=variant,scene_sha256=digest,
                changes=result['placement']['contacts']['changes'],
                registration_changes=result['placement'].get('registration',{}).get('changes',[]),
                pose_changes=result['placement'].get('pose_refinement',{}).get('changes',[]),
                surfaces=[s['kind'] for s in result['structure']['surfaces']],
                objects=sum(o['status']=='generated' for o in result['objects']),
                routed_context=[o['id'] for o in result['objects'] if o.get('structural_evidence',{}).get('observed_context')],
                orientation_reason=result['placement']['orientation_evidence']['reason'],
                idempotent=True, source_unchanged=all(sha(source/f)==value for f,value in source_hashes.items()))
            assert report['source_unchanged']
            reports.append(report);write(args.output/'summary.json',reports)
            print(dict(run=source.name,variant=variant,changes=len(report['changes']),surfaces=report['surfaces']),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources',nargs='+',type=Path)
    parser.add_argument('--baseline',type=Path,default=Path('.runtime/v7-release/application.zip'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--reference-root',type=Path)
    parser.add_argument('--variants',nargs='+',default=['combined','names_removed','without_vanishing','without_context',
        'without_contact_repairs','without_support_polygon','without_finite_collision'])
    main(parser.parse_args())
