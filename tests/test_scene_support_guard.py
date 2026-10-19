import numpy as np
import trimesh

from mapmaker.scene_support_guard import support_preservation


def cube(extents, center):
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(center)
    return mesh.triangles


def movement(delta):
    matrix = np.eye(4)
    matrix[:3, 3] = delta
    return matrix


def test_lifting_a_supported_body_is_rejected():
    faces = dict(a=cube([1, 1, 1], [0, .5, 0]), floor=cube([10, 1, 10], [0, -.5, 0]))
    result = support_preservation(faces, ['a'], ['floor'], 'a', movement([0, .1, 0]), .001)
    assert not result['accepted']
    assert result['checks'][0]['support_id'] == 'floor'


def test_small_slide_on_same_surface_preserves_contact():
    faces = dict(a=cube([1, 1, 1], [0, .5, 0]), floor=cube([10, 1, 10], [0, -.5, 0]))
    result = support_preservation(faces, ['a'], ['floor'], 'a', movement([.1, 0, 0]), .001)
    assert result['accepted'] and len(result['checks']) == 1


def test_moving_support_out_from_under_another_object_is_rejected():
    faces = dict(a=cube([1, 1, 1], [0, .5, 0]), b=cube([.5, .5, .5], [0, 1.25, 0]))
    result = support_preservation(faces, ['a', 'b'], [], 'a', movement([0, -.1, 0]), .001)
    assert not result['accepted']
    assert any(r['object_id']=='b' and r['support_id']=='a' and not r['preserved'] for r in result['checks'])


def test_no_identified_support_is_explicit_in_evidence():
    faces = dict(a=cube([1, 1, 1], [0, 10, 0]), floor=cube([10, 1, 10], [0, -.5, 0]))
    result = support_preservation(faces, ['a'], ['floor'], 'a', movement([.1, 0, 0]), .001)
    assert result['checks'] == []


def test_cached_initial_contacts_keep_candidate_checks_and_results_independent(monkeypatch):
    import mapmaker.scene_support_guard as guard
    faces = dict(a=cube([1, 1, 1], [0, .5, 0]),
                 b=cube([.5, .5, .5], [0, 1.25, 0]),
                 floor=cube([10, 1, 10], [0, -.5, 0]))
    moves = [movement([.1, 0, 0]), movement([0, .1, 0]), movement([0, -.1, 0])]
    expected = [support_preservation(faces, ['a', 'b'], ['floor'], 'a', m, .001) for m in moves]
    original = guard._initial_contacts
    calls = []
    def observed(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(guard, '_initial_contacts', observed)
    cache = {}
    actual = [support_preservation(faces, ['a', 'b'], ['floor'], 'a', m, .001,
                                   initial_cache=cache) for m in moves]
    assert actual == expected and len(calls) == 1
    assert any(not r['accepted'] for r in actual)
    actual[0]['checks'][0]['before']['changed_by_caller'] = True
    assert support_preservation(faces, ['a', 'b'], ['floor'], 'a', moves[0], .001,
                                initial_cache=cache) == expected[0]
    faces['b'] = cube([.5, .5, .5], [0, 10, 0])
    updated = support_preservation(faces, ['a', 'b'], ['floor'], 'a', moves[0], .001,
                                   initial_cache=cache)
    assert len(calls) == 2
    assert updated == support_preservation(faces, ['a', 'b'], ['floor'], 'a', moves[0], .001)
