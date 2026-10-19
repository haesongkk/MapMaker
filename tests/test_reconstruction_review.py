import pytest
import shutil
import trimesh

from mapmaker.reconstruction_review import reconstruct_with_review


def evidence(coverage=.1, depth=.3, retry=True):
    return dict(accepted=True, retry_recommended=retry,
        projection=dict(mask_covered_fraction=coverage, silhouette_iou=coverage),
        normalized_depth_median=depth, normalized_depth_p90=depth*2)


def test_failed_or_worse_retry_keeps_original_and_spends_budget_once():
    for failure in ('exception', 'missing_mesh', 'worse'):
        calls=[];saved=[];budget=dict(remaining=1)
        original=dict(glb=object(),seed=42)
        def generate(seed):
            calls.append(seed)
            if seed==42:return original
            if failure=='exception':raise RuntimeError('inference failed')
            return dict(glb=None if failure=='missing_mesh' else object(),seed=seed)
        selected,review=reconstruct_with_review(generate,lambda _:evidence(),
            lambda result,seed:saved.append(seed),budget)
        assert selected is original and review['selected_seed']==42
        assert budget['remaining']==0 and calls==[42,43] and saved[0]==42
        calls.clear()
        selected,review=reconstruct_with_review(generate,lambda _:evidence(),
            lambda result,seed:saved.append(seed),budget)
        assert selected is original and calls==[42]
        assert review['reason']=='scene_retry_budget_exhausted'


def test_better_candidate_is_selected_with_both_artifacts_preserved():
    results={seed:dict(glb=object(),seed=seed) for seed in (42,43)}
    saved=[]
    selected,review=reconstruct_with_review(lambda seed:results[seed],
        lambda result:evidence(.9,.03) if result['seed']==43 else evidence(),
        lambda result,seed:saved.append(seed),dict(remaining=1))
    assert selected is results[43]
    assert review['selected_seed']==43 and saved==[42,43]


def test_unreliable_evidence_does_not_spend_retry_budget():
    calls=[];budget=dict(remaining=1)
    reconstruct_with_review(lambda seed:(calls.append(seed) or dict(glb=object())),
        lambda result:dict(accepted=False),lambda *_:pytest.fail('unexpected archive'),budget)
    assert calls==[42] and budget['remaining']==1


def test_candidate_selection_survives_transfer_and_detects_tampering(tmp_path):
    from mapmaker.scene_run import write, read, sha
    from mapmaker.scene_transfer import pack_run, unpack_run
    from mapmaker.reconstruction_review import validate_review_artifacts
    run=tmp_path/'run';(run/'objects/candidates/item').mkdir(parents=True)
    artifacts=[]
    for seed,size in ((42,1),(43,2)):
        asset=f'objects/candidates/item/seed_{seed}.glb'
        pose=f'objects/candidates/item/seed_{seed}.pose.json'
        trimesh.creation.box(extents=[size]*3).export(run/asset)
        write(run/pose,dict(scale=[size]*3))
        artifacts.append(dict(asset=asset,pose=pose,sha256=sha(run/asset),pose_sha256=sha(run/pose)))
    shutil.copyfile(run/artifacts[1]['asset'],run/'objects/item.glb')
    meta=dict(reconstruction_review=dict(maximum_extra_inferences=1,extra_inferences_used=1),
        objects=[dict(asset='objects/item.glb',pose=dict(scale=[2]*3),reconstruction_review=dict(
            selected_seed=43,attempted_seeds=[42,43],original=evidence(),alternative=evidence(.9,.03),
            original_artifact=artifacts[0],alternative_artifact=artifacts[1]))])
    write(run/'scene_metadata.json',meta)
    pack_run(run,tmp_path/'result.zip')
    unpack_run(tmp_path/'result.zip',tmp_path/'received')
    target=tmp_path/'received'
    assert validate_review_artifacts(target,read(target/'scene_metadata.json'))['candidate_artifacts']==2
    shutil.copyfile(target/artifacts[0]['asset'],target/'objects/item.glb')
    with pytest.raises(AssertionError,match='Selected mesh differs'):
        validate_review_artifacts(target,meta)
    shutil.copyfile(target/artifacts[1]['asset'],target/'objects/item.glb')
    write(target/artifacts[0]['pose'],dict(scale=[999]*3))
    with pytest.raises(AssertionError,match='Candidate artifact changed'):
        validate_review_artifacts(target,meta)


def test_ranked_policy_validates_budget_and_scheduled_mask_identity(tmp_path):
    from mapmaker.reconstruction_review import validate_review_artifacts
    hashes=['a'*64,'b'*64]
    meta=dict(reconstruction_review=dict(maximum_extra_inferences=2,extra_inferences_used=2,
        order='descending_visible_depth_error_then_mask_sha256',visible_depth=True,
        scheduled_mask_hashes=hashes.copy()),objects=[dict(mask_sha256=h,reconstruction_review=dict(
            attempted_seeds=[42,43],selected_seed=42,reason='retry_failed')) for h in hashes])
    assert validate_review_artifacts(tmp_path,meta)['extra_inferences']==2
    meta['reconstruction_review']['scheduled_mask_hashes']=['c'*64,'b'*64]
    with pytest.raises(AssertionError):validate_review_artifacts(tmp_path,meta)
    meta['reconstruction_review']['scheduled_mask_hashes']=hashes
    meta['reconstruction_review']['maximum_extra_inferences']=3
    with pytest.raises(AssertionError):validate_review_artifacts(tmp_path,meta)
