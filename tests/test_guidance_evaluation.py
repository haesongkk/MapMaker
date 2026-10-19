import shutil
import numpy as np
from PIL import Image
import pytest
import trimesh
from mapmaker.scene_run import read, write, sha
from scripts.evaluate_guidance_probe import compare


def fixture(tmp_path):
    source=tmp_path/'source';probe=tmp_path/'probe'
    for path in [source/'input',source/'objects',source/'masks',probe/'objects/guidance']:
        path.mkdir(parents=True)
    Image.new('RGB',(80,80),'white').save(source/'input/source_image.png')
    y,x=np.mgrid[:80,:80]
    points=np.stack([(x-40)*.025,(y-40)*.025,np.full_like(x,2.95,dtype=float)],-1)
    np.savez_compressed(source/'input/pointmap.npz',points=points)
    mask=np.zeros((80,80),np.uint8);mask[24:57,24:57]=255
    Image.fromarray(mask).save(source/'masks/one.png')
    trimesh.creation.box(extents=[.8,.1,.8]).export(source/'objects/one.glb')
    shutil.copyfile(source/'objects/one.glb',source/'scene.glb')
    shutil.copyfile(source/'objects/one.glb',probe/'objects/guidance/000.glb')
    pose=dict(rotation=[[1,0,0,0]],translation=[[0,0,3]],scale=[[1,1,1]])
    obj=dict(id='one',name='arbitrary',status='generated',mask='masks/one.png',
        mask_sha256=sha(source/'masks/one.png'),asset='objects/one.glb',
        asset_sha256=sha(source/'objects/one.glb'),pose=pose)
    meta=dict(run_id='a'*32,input_image='input/source_image.png',
        input_sha256=sha(source/'input/source_image.png'),objects=[obj],
        pointmap=dict(asset='input/pointmap.npz',sha256=sha(source/'input/pointmap.npz')))
    write(source/'scene_metadata.json',meta)
    write(probe/'logs/guidance_comparison.json',dict(completed=True,guidance_restored=True,
        guidance_method='baseline_cfg_plus_depth_difference_v1',
        source_scene_unchanged=True,seed=42,baseline_additional_guidance=0.,candidate_additional_guidance=1.,
        source_scene_sha256=sha(source/'scene.glb'),source_input_sha256=meta['input_sha256'],
        pointmap_sha256=meta['pointmap']['sha256'],objects=[dict(object_id='one',
            baseline_asset=obj['asset'],baseline_sha256=obj['asset_sha256'],baseline_pose=pose,
            mask_sha256=obj['mask_sha256'],asset='objects/guidance/000.glb',
            sha256=sha(probe/'objects/guidance/000.glb'),pose=pose,
            guidance_evidence=dict(condition_pairs=1,prediction_pairs=25,
                                   max_condition_delta=1.,max_prediction_delta=.1))]))
    return source,probe


def test_identical_paired_geometry_and_renamed_objects_have_identical_evidence(tmp_path):
    source,probe=fixture(tmp_path)
    report=compare(source,probe)
    assert report['paired_objects']==1 and report['quality_passed'] is False
    assert report['records'][0]['baseline']['accepted']
    assert report['records'][0]['baseline']==report['records'][0]['candidate']
    meta=read(source/'scene_metadata.json');meta['objects'][0]['name']=''
    write(source/'scene_metadata.json',meta)
    assert compare(source,probe)==report


def test_expanded_mask_is_used_for_evaluation_and_scene_replay(tmp_path):
    from scripts.rebuild_guidance_scene import build
    source, probe = fixture(tmp_path)
    report = read(probe/'logs/guidance_comparison.json')
    original_hash = sha(source/'masks/one.png')
    expanded = np.asarray(Image.open(source/'masks/one.png')).copy()
    expanded[57:65, 38:43] = 255
    Image.fromarray(expanded).save(source/'input/expanded.png')
    row = dict(original_sha256=original_hash, asset='input/expanded.png',
               sha256=sha(source/'input/expanded.png'))
    write(source/'input/mask_expansions.json', dict(masks=[row]))
    report.update(guidance_method='controlled_mask_expansion_v1', conditioning_mode='mask_expansion',
                  baseline_seed=42, candidate_additional_guidance=0.)
    report['objects'][0]['mask_expansion_evidence'] = row
    write(probe/'logs/guidance_comparison.json', report)
    result = compare(source, probe)
    pair = result['records'][0]['expanded_mask_comparison']
    assert pair['baseline'] == pair['candidate']
    output = tmp_path/'expanded-scene'
    assembled = build(source, probe, output, finalize=False)
    obj = assembled['objects'][0]
    assert obj['mask_sha256'] == row['sha256'] == sha(output/obj['mask'])
    assert obj['mask_expansion']['original_sha256'] == original_hash
    assert obj['mask_area'] == int((expanded > 0).sum())
    assert obj['bbox'] == [24, 24, 57, 65]
    assert sha(source/'masks/one.png') == original_hash
    row['sha256'] = 'a'*64
    report['objects'][0]['mask_expansion_evidence'] = row
    write(probe/'logs/guidance_comparison.json', report)
    with pytest.raises(AssertionError):
        compare(source, probe)


def test_changed_candidate_is_rejected_before_source_evaluation(tmp_path):
    source,probe=fixture(tmp_path)
    (probe/'objects/guidance/000.glb').write_bytes(b'changed')
    with pytest.raises(AssertionError):compare(source,probe)


def test_seed_alternative_requires_frozen_seed_and_zero_guidance(tmp_path):
    source,probe=fixture(tmp_path)
    path=probe/'logs/guidance_comparison.json';report=read(path)
    report.update(guidance_method='controlled_seed_alternative_v1',conditioning_mode='seed_alternative',
                  seed=43,baseline_seed=42,candidate_additional_guidance=0.)
    write(path,report)
    result=compare(source,probe)
    assert result['records'][0]['baseline']['visible_depth']==result['records'][0]['candidate']['visible_depth']
    assert result['quality_passed'] is False
    for key,value in [('seed',42),('baseline_seed',43),('candidate_additional_guidance',1.)]:
        altered=dict(report);altered[key]=value;write(path,altered)
        with pytest.raises(AssertionError):compare(source,probe)


def test_accepted_only_rebuild_does_not_replace_with_equal_candidate(tmp_path):
    from scripts.rebuild_guidance_scene import build
    source,probe=fixture(tmp_path)
    original=sha(source/'scene.glb');output=tmp_path/'selected'
    with pytest.raises(ValueError,match='No alternative passed'):
        build(source,probe,output,finalize=False,accepted_only=True)
    assert not output.exists() and sha(source/'scene.glb')==original


def test_accepted_only_rebuild_retains_a_source_improving_candidate(tmp_path):
    from scripts.rebuild_guidance_scene import build
    source,probe=fixture(tmp_path)
    meta=read(source/'scene_metadata.json');meta['objects'][0]['pose']['translation']=[[2,0,3]]
    write(source/'scene_metadata.json',meta)
    report=read(probe/'logs/guidance_comparison.json')
    report['objects'][0]['baseline_pose']=meta['objects'][0]['pose']
    write(probe/'logs/guidance_comparison.json',report)
    original=sha(source/'scene.glb')
    result=build(source,probe,tmp_path/'selected',finalize=False,accepted_only=True)
    assert result['guidance_experiment']['accepted_only']
    assert result['guidance_experiment']['regenerated_object_ids']==['one']
    assert result['objects'][0]['pose']==report['objects'][0]['pose']
    assert sha(source/'scene.glb')==original


def test_rgb_only_comparison_checks_pixel_transform_and_preserves_subset_scope(tmp_path):
    import hashlib
    from mapmaker.reconstruction_conditioning import isolate_mask_rgb
    source,probe=fixture(tmp_path)
    report=read(probe/'logs/guidance_comparison.json')
    report.update(guidance_method='masked_rgb_context_v1',candidate_additional_guidance=0.,
                  target_masks=[report['objects'][0]['mask_sha256']])
    image=np.asarray(Image.open(source/'input/source_image.png'))
    mask=np.asarray(Image.open(source/'masks/one.png'))>0
    rgb=dict(condition_pairs=1,max_condition_delta=1.,geometry_inputs_unchanged=True,
        target_pixels_unchanged=True,original_pixels_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
        modified_pixels_sha256=hashlib.sha256(isolate_mask_rgb(image,mask).tobytes()).hexdigest())
    report['objects'][0]['rgb_conditioning_evidence']=rgb
    write(probe/'logs/guidance_comparison.json',report)
    result=compare(source,probe)
    assert result['paired_objects']==1 and result['conditioning_method']=='masked_rgb_context_v1'
    rgb['modified_pixels_sha256']='a'*64
    write(probe/'logs/guidance_comparison.json',report)
    with pytest.raises(AssertionError):compare(source,probe)


@pytest.mark.parametrize('field', ['guidance_method', 'guidance_evidence'])
def test_no_op_or_unmeasured_probe_cannot_enter_scene_evaluation(tmp_path, field):
    source, probe = fixture(tmp_path)
    report = read(probe/'logs/guidance_comparison.json')
    if field == 'guidance_method':
        report.pop(field)
    else:
        report['objects'][0].pop(field)
    write(probe/'logs/guidance_comparison.json', report)
    with pytest.raises(ValueError):
        compare(source, probe)


@pytest.mark.parametrize('seed',[42,43])
def test_scene_assembly_uses_candidate_pose_and_preserves_source(tmp_path,seed):
    from scripts.rebuild_guidance_scene import build
    from mapmaker.scene_replay import pose_matrix
    source,probe=fixture(tmp_path)
    original_hash=sha(source/'scene.glb')
    report=read(probe/'logs/guidance_comparison.json')
    if seed==43:
        report.update(seed=43,baseline_seed=42,candidate_additional_guidance=0.,
            guidance_method='controlled_seed_alternative_v1',conditioning_mode='seed_alternative')
    report['objects'][0]['pose']['translation']=[[.1,0,3]]
    write(probe/'logs/guidance_comparison.json',report)
    output=tmp_path/'assembled'
    result=build(source,probe,output,finalize=False)
    scene=trimesh.load(output/'scene.glb',force='scene',process=False)
    np.testing.assert_allclose(scene.graph['one'][0],pose_matrix(report['objects'][0]['pose']))
    assert result['guidance_experiment']['quality_passed'] is False
    assert result['guidance_experiment']['seed']==seed
    assert result['guidance_experiment']['conditioning_method']==report['guidance_method']
    assert sha(source/'scene.glb')==original_hash
    assert sha(output/result['objects'][0]['asset'])==report['objects'][0]['sha256']
    assert read(output/'logs/guidance_scene_provenance.json')['source']==str(source.resolve())
    provenance=read(output/'replay_provenance.json')
    assert sha(output/provenance['source_metadata_asset'])==provenance['source_metadata_sha256']
