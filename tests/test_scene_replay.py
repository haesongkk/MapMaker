import numpy as np
import pytest
import trimesh

from mapmaker.scene_assembly import NATIVE_TO_GLB_ROW
from mapmaker.scene_replay import rebuild_inference_scene, pose_matrix
from mapmaker.scene_run import read, write, sha


def fixture_run(root):
    root.mkdir()
    (root / 'input.png').write_bytes(b'fixture image')
    trimesh.creation.box().export(root / 'asset.glb')
    pose = dict(rotation=[[1, 0, 0, 0]], scale=[[2, 3, 4]], translation=[[1, 2, 3]])
    obj = dict(id='part', name='arbitrary', status='duplicate', asset='asset.glb',
        asset_sha256=sha(root/'asset.glb'), pose=pose, duplicate_of=['other'],
        placement=dict(original_matrix=pose_matrix(pose).tolist()))
    write(root/'scene_metadata.json', dict(input_image='input.png',
        input_sha256=sha(root/'input.png'), objects=[obj], placement=dict(version=9)))


def test_rebuild_restores_removed_asset_and_original_pose_without_touching_source(tmp_path):
    source, target = tmp_path/'source', tmp_path/'target'
    fixture_run(source)
    digest = sha(source/'scene_metadata.json')
    meta = rebuild_inference_scene(source, target)
    assert sha(source/'scene_metadata.json') == digest
    assert 'placement' not in meta and 'duplicate_of' not in meta['objects'][0]
    assert meta['objects'][0]['status'] == 'generated'
    scene = trimesh.load(target/'scene.glb', force='scene')
    expected = np.eye(4)
    expected[:3, :3] = np.diag([2, 3, 4]) @ NATIVE_TO_GLB_ROW
    expected[:3, 3] = [1, 2, 3]
    np.testing.assert_allclose(scene.graph['part'][0], expected)
    assert read(target/'replay_provenance.json')['source_unchanged']


def test_rebuild_refuses_changed_asset_and_existing_target(tmp_path):
    source, target = tmp_path/'source', tmp_path/'target'
    fixture_run(source)
    target.mkdir()
    with pytest.raises(FileExistsError):
        rebuild_inference_scene(source, target)
    (source/'asset.glb').write_bytes(b'altered')
    with pytest.raises(ValueError, match='Invalid replay source asset'):
        rebuild_inference_scene(source, tmp_path/'new')
    assert not (tmp_path/'new').exists()


def test_nontrivial_rotation_matches_official_recorded_matrix():
    pose = dict(rotation=[[.00341160665, .0010090092, -.7948732972, -.6067650318]],
        scale=[[3.1140880585]*3], translation=[[-.0691312775, -.1250704527, .9936696291]])
    expected = [[-3.11400938, .01307645, .01788781, -.06913128],
                [.00789738, 3.00387907, -.82109278, -.12507045],
                [-.02070262, -.82102650, -3.00383615, .99366963], [0,0,0,1]]
    np.testing.assert_allclose(pose_matrix(pose), expected, atol=1e-6)


def test_replay_preserves_and_verifies_alternative_mesh_and_pose(tmp_path):
    source, target = tmp_path/'source', tmp_path/'target'
    fixture_run(source)
    candidate = source/'objects/candidates/part'
    candidate.mkdir(parents=True)
    trimesh.creation.icosphere(subdivisions=1).export(candidate/'seed_43.glb')
    write(candidate/'seed_43.pose.json', dict(rotation=[[1,0,0,0]],scale=[[1,1,1]],translation=[[0,0,0]]))
    mesh='objects/candidates/part/seed_43.glb'
    pose='objects/candidates/part/seed_43.pose.json'
    meta=read(source/'scene_metadata.json')
    meta['objects'][0]['reconstruction_review']=dict(alternative_artifact=dict(
        asset=mesh,sha256=sha(source/mesh),pose=pose,pose_sha256=sha(source/pose)))
    write(source/'scene_metadata.json',meta)
    rebuild_inference_scene(source,target)
    assert sha(target/mesh)==sha(source/mesh) and sha(target/pose)==sha(source/pose)
    assert mesh in read(target/'replay_provenance.json')['inference_asset_hashes']
    (source/pose).write_bytes(b'changed pose')
    with pytest.raises(ValueError,match='Invalid replay source asset'):
        rebuild_inference_scene(source,tmp_path/'refused')


def test_replay_preserves_original_mask_evidence_after_expansion(tmp_path):
    source,target=tmp_path/'source',tmp_path/'target';fixture_run(source)
    (source/'original.png').write_bytes(b'original mask')
    (source/'expanded.png').write_bytes(b'expanded mask')
    meta=read(source/'scene_metadata.json');obj=meta['objects'][0]
    obj.update(mask='expanded.png',mask_sha256=sha(source/'expanded.png'),
        mask_expansion=dict(original_mask='original.png',original_sha256=sha(source/'original.png')))
    write(source/'scene_metadata.json',meta)
    rebuild_inference_scene(source,target)
    for name in ('original.png','expanded.png'):
        assert sha(target/name)==sha(source/name)
        assert name in read(target/'replay_provenance.json')['inference_asset_hashes']
    (source/'original.png').write_bytes(b'changed original')
    with pytest.raises(ValueError,match='Invalid replay source asset'):
        rebuild_inference_scene(source,tmp_path/'refused')
