import numpy as np
from PIL import Image
import trimesh
from mapmaker.scene_source_guard import contact_source_guard


def fixture(tmp_path, displacement=0):
    y,x=np.mgrid[:200,:200]
    points=np.stack([(100-x)*.03,(100-y)*.03,np.full_like(x,3.)],axis=-1)
    mask=np.zeros((200,200),np.uint8);mask[84:117,84:117]=255
    Image.fromarray(mask).save(tmp_path/'mask.png')
    mesh=trimesh.creation.box(extents=[1,1,.2]);mesh.apply_translation([0,displacement,3.1])
    scene=trimesh.Scene(base_frame='Scene')
    scene.graph.update(frame_from='Scene',frame_to='object',matrix=np.eye(4))
    scene.add_geometry(mesh,node_name='mesh',parent_node_name='object')
    obj=dict(id='object',name='arbitrary',mask='mask.png')
    guard=contact_source_guard(tmp_path,scene,{},dict(common_transform=np.eye(4)),points)
    return obj,guard


def test_correct_source_alignment_is_preserved_and_wrong_shift_is_rejected(tmp_path):
    obj,guard=fixture(tmp_path)
    assert guard(obj,np.zeros(3))['accepted']
    result=guard(obj,np.array([0,.4,0]))
    assert not result['accepted'] and result['reason']=='contact_degrades_source_silhouette'
    obj['name']=''
    assert guard(obj,np.array([0,.4,0])) == result


def test_source_improving_bounded_shift_remains_available(tmp_path):
    obj,guard=fixture(tmp_path,displacement=.1)
    result=guard(obj,np.array([0,-.1,0]))
    assert result['accepted']
    assert result['after_projection']['silhouette_iou'] > result['before_projection']['silhouette_iou']


def test_contact_solver_honors_source_veto():
    from test_scene_quality import scene_of
    from mapmaker.scene_contacts import improve_contacts
    scene,objects,placement=scene_of([('support',[2,1,2],[0,.5,0]),('prop',[.4,.2,.4],[0,1.4,0])])
    before=scene.graph[objects[1]['id']][0].copy()
    improve_contacts(scene,objects,placement,source_guard=lambda obj,delta:
        dict(accepted=False,reason='contact_degrades_source_silhouette'))
    np.testing.assert_array_equal(scene.graph[objects[1]['id']][0],before)
    assert placement['contacts']['source_guard_enabled']
    assert placement['contacts']['source_checks']


def test_penetration_separation_also_honors_source_veto():
    from test_scene_quality import scene_of
    from mapmaker.scene_contacts import improve_contacts
    inputs=[('arbitrary',[2,1,2],[0,.5,0]),('other',[2,1,2],[1.95,.5,0])]
    baseline,baseline_objects,baseline_placement=scene_of(inputs)
    improve_contacts(baseline,baseline_objects,baseline_placement)
    assert any(c['reason']=='bounded_mesh_penetration' for c in baseline_placement['contacts']['changes'])
    scene,objects,placement=scene_of(inputs)
    before={o['id']:scene.graph[o['id']][0].copy() for o in objects}
    improve_contacts(scene,objects,placement,source_guard=lambda obj,delta:
        dict(accepted=False,reason='contact_degrades_source_silhouette'))
    for obj in objects:
        np.testing.assert_array_equal(scene.graph[obj['id']][0],before[obj['id']])
    assert any(r['stage']=='separation' and r['reason']=='contact_degrades_source_silhouette'
               for r in placement['contacts']['rejections'])
