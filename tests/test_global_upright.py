import numpy as np
import pytest
import trimesh
import json
from mapmaker.global_upright import align, consensus_up


def test_consensus_excludes_sideways_and_rejects_no_majority():
    up, included, _ = consensus_up([[0, 1, 0], [.1, 1, 0], [0, 1, .1], [1, 0, 0]])
    assert included.tolist() == [True, True, True, False]
    assert up[1] > .99
    with pytest.raises(ValueError, match='No majority'):
        consensus_up([[1, 0, 0], [0, 1, 0], [0, 0, 1]])


def test_global_transform_preserves_relative_geometry_and_binary(tmp_path):
    source = tmp_path/'source'; source.mkdir(); (source/'input').mkdir()
    scene = trimesh.Scene(base_frame='Scene')
    objects = []
    for i in range(3):
        matrix = trimesh.transformations.rotation_matrix(.4, [1, 0, 0])
        matrix[:3, 3] = [i*2, i*.3-2, i*.5]
        oid = f'object{i}'
        scene.graph.update(frame_from='Scene', frame_to=oid, matrix=matrix)
        scene.add_geometry(trimesh.creation.box(), parent_node_name=oid, node_name=oid+'_mesh')
        objects.append(dict(id=oid, name=oid, status='generated', transform={'matrix': matrix.tolist()}))
    scene.export(source/'scene.glb')
    (source/'scene_metadata.json').write_text(json.dumps(dict(run_id='original', objects=objects)))
    evidence = align(source, tmp_path/'output')
    output = trimesh.load(tmp_path/'output/scene.glb', force='scene')
    common = np.asarray(evidence['common_transform'])
    for obj in objects:
        assert np.allclose(output.graph[obj['id']][0], common @ np.asarray(obj['transform']['matrix']))
    assert abs(output.bounds[0, 1]) < 1e-7
    assert evidence['binary_preserved']
    assert np.allclose(evidence['up_after'], [0, 1, 0])
