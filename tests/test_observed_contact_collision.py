import numpy as np
import trimesh

from mapmaker.scene_contacts import improve_contacts
from test_scene_quality import scene_of


def test_unclassified_observation_blocks_contact_path_without_becoming_support():
    inputs = [('one', [2, 1, 2], [0, .5, 0]),
              ('two', [.4, .2, .4], [0, 1.4, 0])]
    baseline, objects, placement = scene_of(inputs)
    improve_contacts(baseline, objects, placement)
    assert placement['contacts']['changes']
    for offset, blocked in ((0, True), (3, False)):
        scene, objects, placement = scene_of(inputs)
        mesh = trimesh.Trimesh(
            vertices=np.array([[-1,1.2,-1], [1,1.2,-1], [1,1.2,1], [-1,1.2,1]]) + [offset,0,0],
            faces=[[0,1,2], [0,2,3]], process=False)
        scene.add_geometry(mesh, node_name='observed')
        before = scene.graph[objects[1]['id']][0].copy()
        structure = dict(surfaces=[dict(node='observed', kind='observed')])
        improve_contacts(scene, objects, placement, structure)
        contacts = placement['contacts']
        assert all(r['support_id'] != 'observed' for r in contacts['relations'])
        if blocked:
            np.testing.assert_array_equal(scene.graph[objects[1]['id']][0], before)
            assert any(q['other_id']=='observed' and q['result']=='intersection'
                       for q in contacts['collision_queries'])
        else:
            assert contacts['changes']
