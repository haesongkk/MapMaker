"""Bounded alternative inference, preserving the first usable reconstruction."""
from .reconstruction_evidence import prefer_alternative


def validate_review_artifacts(run, meta):
    from .scene_run import sha, read
    from .scene_transfer import safe_name
    policy = meta.get('reconstruction_review')
    if policy is None:
        return dict(present=False)
    attempts = 0
    checked = 0
    for obj in meta['objects']:
        review = obj.get('reconstruction_review')
        if review is None:
            continue
        seeds = review['attempted_seeds']
        assert seeds in ([42], [42,43])
        attempts += len(seeds)-1
        assert review['selected_seed'] in seeds
        for key in ('original_artifact', 'alternative_artifact'):
            artifact = review.get(key)
            if artifact is None:
                continue
            for field, digest in (('asset','sha256'), ('pose','pose_sha256')):
                path = safe_name(artifact[field])
                assert path.parts[0]=='objects'
                assert sha(run/artifact[field])==artifact[digest], 'Candidate artifact changed'
            checked += 1
        selected = review.get('alternative_artifact' if review['selected_seed']==43 else 'original_artifact')
        if review['selected_seed']==43:
            assert selected and prefer_alternative(review['original'],review['alternative'])
            if review.get('context_review_required'):
                assert review.get('context_review', {}).get('accepted') is True
        if selected and obj.get('asset'):
            assert sha(run/obj['asset'])==selected['sha256'], 'Selected mesh differs from candidate'
            assert obj['pose']==read(run/selected['pose']), 'Selected pose differs from candidate'
    assert attempts==policy['extra_inferences_used']
    maximum = policy['maximum_extra_inferences']
    if policy.get('order') == 'descending_visible_depth_error_then_mask_sha256':
        assert maximum == 2 and policy.get('visible_depth') is True
        scheduled = policy['scheduled_mask_hashes']
        assert len(scheduled) <= maximum and len(scheduled) == len(set(scheduled))
        attempted = [o['mask_sha256'] for o in meta['objects']
                     if len(o.get('reconstruction_review', {}).get('attempted_seeds', [])) == 2]
        assert set(attempted) <= set(scheduled)
    else:
        assert maximum == 1
    assert attempts <= maximum
    return dict(present=True, extra_inferences=attempts, candidate_artifacts=checked)


def reconstruct_with_review(generate, measure, preserve, budget, *, context_guard=None):
    original = generate(42)
    if original.get('glb') is None:
        raise RuntimeError('SAM3D returned no mesh')
    review = dict(selected_seed=42, attempted_seeds=[42], uses_object_names=False,
                  context_review_required=context_guard is not None,
                  selection_scope='visible_source_evidence; scene quality still requires validation')
    try:
        evidence = measure(original)
        review['original'] = evidence
        if not evidence.get('retry_recommended'):
            review['reason'] = 'no_reconstruction_retry_requested'
            return original, review
        if budget['remaining'] <= 0:
            review['reason'] = 'scene_retry_budget_exhausted'
            return original, review
        # Preserve before attempting another inference; failure cannot erase it.
        review['original_artifact'] = preserve(original, 42)
        budget['remaining'] -= 1
        review['attempted_seeds'].append(43)
        alternative = generate(43)
        if alternative.get('glb') is None:
            raise RuntimeError('Alternative inference returned no mesh')
        review['alternative_artifact'] = preserve(alternative, 43)
        review['alternative'] = measure(alternative)
        if prefer_alternative(evidence, review['alternative']):
            if context_guard is not None:
                review['context_review'] = context_guard(original, alternative)
                if review['context_review'].get('accepted') is not True:
                    review['reason'] = 'context_regression_original_preserved'
                    return original, review
            review.update(selected_seed=43, reason='visible_source_evidence_improved')
            return alternative, review
        review['reason'] = 'alternative_did_not_improve_both_measures'
    except Exception as exc:
        review.update(reason='review_or_retry_failed_original_preserved', error=str(exc))
    return original, review
