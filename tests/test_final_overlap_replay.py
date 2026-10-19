import copy
import numpy as np
import pytest
import trimesh

from scripts.replay_final_overlap import restore_before_overlap


def fixture():
    scene = trimesh.Scene()
    objects, changes, records, poses = [], [], [], []
    for index in range(2):
        oid = str(index)
        before = np.eye(4)
        before[0,3] = index*4
        change = np.eye(4)
        change[1,3] = .1
        after = change @ before
        scene.add_geometry(trimesh.creation.box(), node_name=oid, transform=after)
        objects.append(dict(id=oid,status='generated',transform={'matrix':after.tolist()},
                            placement={'pose_depth_transform':change.tolist()}))
        changes.append(dict(object_id=oid,transform=change.tolist()))
        records.append(dict(object_id=oid,applied=True,selected_candidate=0,
                            candidates=[dict(accepted=True,transform=change.tolist())]))
        poses.append(dict(object_id=oid,applied=False,starting_world_transform=before.tolist()))
    meta = dict(objects=objects, placement=dict(pose_refinement={'records':poses},
                overlap_refinement=dict(complete=True,changes=changes,records=records)))
    return scene, meta


def test_undo_preserves_geometry_and_recovers_recorded_origins():
    scene, meta = fixture()
    geometry = {key: mesh.vertices.copy() for key,mesh in scene.geometry.items()}
    originals = [np.asarray(r['starting_world_transform']) for r in meta['placement']['pose_refinement']['records']]
    assert restore_before_overlap(scene, meta) == ['0','1']
    for obj, expected in zip(meta['objects'], originals):
        np.testing.assert_array_equal(scene.graph[obj['id']][0], expected)
        np.testing.assert_array_equal(obj['transform']['matrix'], expected)
        assert 'pose_depth_transform' not in obj['placement']
    for key, vertices in geometry.items():
        np.testing.assert_array_equal(scene.geometry[key].vertices, vertices)
    assert 'overlap_refinement' not in meta['placement']


def test_later_invalid_origin_prevents_all_edits():
    scene, meta = fixture()
    meta['placement']['pose_refinement']['records'][1]['starting_world_transform'][0][3] = 99
    before = {oid: scene.graph[oid][0].copy() for oid in ('0','1')}
    original_meta = copy.deepcopy(meta)
    with pytest.raises(ValueError, match='mismatch'):
        restore_before_overlap(scene, meta)
    assert meta == original_meta
    for oid, matrix in before.items():
        np.testing.assert_array_equal(scene.graph[oid][0], matrix)


def test_contact_replay_rejects_previous_contact_edits_before_writing(tmp_path):
    from mapmaker.scene_run import write
    from scripts.replay_final_overlap import replay
    source, target = tmp_path/'source', tmp_path/'target'
    source.mkdir()
    write(source/'scene_metadata.json', {'placement': {'contacts': {
        'changes': [{'object_id': 'one', 'translation': [0, .1, 0]}]}}})
    with pytest.raises(ValueError, match='unchanged original contact stage'):
        replay(source, target, replay_contacts=True)
    assert not target.exists()
