"""Bounded scene-wide retry ordering from measured geometry, never labels."""
import math


def ranked_depth_retries(objects, maximum=2):
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 0 <= maximum <= 2:
        raise ValueError('Expected a retry budget between zero and two')
    candidates = []
    for obj in objects:
        evidence = obj.get('reconstruction_review', {}).get('original', {})
        ray = evidence.get('visible_depth', {})
        error = ray.get('normalized_median')
        digest = obj.get('mask_sha256', '')
        if (obj.get('status') != 'generated' or not evidence.get('accepted')
                or not evidence.get('retry_recommended') or not ray.get('available')
                or ray.get('matched_rays', 0) < 64 or ray.get('hit_fraction', 0) < .5
                or error is None or not math.isfinite(error) or error <= .1):
            continue
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Retry ordering requires a verified mask hash')
        candidates.append((float(error), digest, obj))
    # Duplicate mask identities cannot be resolved by semantic names or IDs.
    hashes = [row[1] for row in candidates]
    if len(hashes) != len(set(hashes)):
        raise ValueError('Ambiguous duplicate mask identity')
    return [row[2] for row in sorted(candidates, key=lambda row: (-row[0], row[1]))[:maximum]]
