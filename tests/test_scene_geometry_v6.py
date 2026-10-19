import copy
import numpy as np
import pytest
import trimesh
from PIL import Image
from mapmaker.scene_contacts import improve_contacts
from mapmaker.scene_geometry import sampled_penetration, wall_contact
from mapmaker.scene_structure import fit_surfaces
from mapmaker.mask_geometry import partial_duplicate
from mapmaker.mask_selection import select_masks
from mapmaker.scene_placement import finalize_scene, correct_placement, align_objects
from mapmaker.scene_run import read, write, sha
from test_scene_quality import scene_of


def room_pointmap(n=80):
    x,y=np.meshgrid(np.linspace(-1.2,1.2,n),np.linspace(.9,-.9,n))
    rays=np.stack([x,y,np.ones_like(x)],axis=-1)
    t=np.minimum(4.,np.minimum(3/np.maximum(abs(x),1e-8),1.5/np.maximum(abs(y),1e-8)))
    return rays*t[...,None]


@pytest.mark.parametrize('scale', [.1,1.,10.])
def test_contact_is_name_independent_and_scale_consistent(scale):
    specs=[('anything',[2,1,2],[0,.5,0]),('anything_else',[.4,.2,.4],[0,1.4,0])]
    specs=[(n,np.array(s)*scale,np.array(c)*scale) for n,s,c in specs]
    scene,objects,placement=scene_of(specs)
    renamed=copy.deepcopy(objects); alternate=scene.copy(); report=copy.deepcopy(placement)
    for obj in renamed: obj.pop('name')
    improve_contacts(scene,objects,placement);improve_contacts(alternate,renamed,report)
    for obj in objects: np.testing.assert_allclose(scene.graph[obj['id']][0],alternate.graph[obj['id']][0])
    assert objects[1]['placement']['world_bounds_after'][0][1]==pytest.approx(scale)


def test_mask_selection_names_and_prompt_order_do_not_change_geometry():
    masks=[]
    for i in range(14):
        mask=np.zeros((300,300),bool);mask[i*20:i*20+15,0:80]=True;masks.append(mask)
    def run(reverse):
        raw=[(dict(name=str(99-i) if reverse else 'same',candidate_index=i,confidence=.9),m) for i,m in enumerate(masks)]
        if reverse:raw.reverse()
        return [r['geometry_key'] for r,m in select_masks(raw,90000)]
    assert run(False)==run(True)


def test_partial_mask_requires_all_geometric_and_boundary_evidence():
    y,x=np.mgrid[:100,:100]
    points=np.stack([x/100,y/100,np.ones_like(x)],axis=-1)
    rgb=np.full((100,100,3),128,np.uint8)
    large=np.zeros((100,100),bool);large[10:90,10:90]=True
    small=np.zeros_like(large);small[10:30,10:90]=True
    assert partial_duplicate(small,large,points,rgb)
    different_depth=points.copy();different_depth[small,2]+=.2
    assert not partial_duplicate(small,large,different_depth,rgb)
    visible_border=rgb.copy();visible_border[small]=255
    assert not partial_duplicate(small,large,points,visible_border)
    independent=np.zeros_like(large);independent[30:50,30:50]=True
    assert not partial_duplicate(independent,large,points,rgb)


def test_room_planes_are_observed_and_no_fake_box_when_missing():
    points=room_pointmap();common=np.eye(4);common[1,3]=1.5
    excluded=np.zeros(points.shape[:2],bool);excluded[25:45,25:45]=True
    patches,report=fit_surfaces(points,excluded,common)
    assert {'floor','wall','ceiling'} <= {r['kind'] for m,r in patches}
    for mesh,record in patches:
        assert record['completion']=='observed_patches_only'
        assert record['residual_p95'] <= record['tolerance']
        assert np.isfinite(mesh.vertices).all()
        assert np.all(mesh.face_normals@record['normal'] > .99)
    patches,report=fit_surfaces(np.full_like(points,np.nan),excluded,common)
    assert patches==[] and report['reason']=='insufficient_background_points'


def test_disconnected_horizontal_regions_are_not_certified_as_floor():
    y,x=np.mgrid[:100,:100]
    points=np.stack([(x-50)/25,np.full_like(x,-1,dtype=float),1+y/25],axis=-1)
    excluded=np.ones((100,100),bool)
    for row in (10,40,70):
        for column in (10,40,70):
            excluded[row:row+15,column:column+15]=False
    patches,_=fit_surfaces(points,excluded,np.eye(4))
    assert patches and all(r['kind']=='observed' for _,r in patches)
    assert all(r['largest_connected_fraction'] < .5 for _,r in patches)
    assert all('withheld' in r['classification'] for _,r in patches)


def test_real_mesh_penetration_and_open_mesh_unknown():
    a=trimesh.creation.box();b=trimesh.creation.box();b.apply_translation([.8,0,0])
    assert sampled_penetration(a.triangles,b.triangles,.001)>0
    b.apply_translation([3,0,0]); assert sampled_penetration(a.triangles,b.triangles,.001)==0
    assert sampled_penetration(a.triangles,b.triangles[:1],.001) is None


def test_overlapping_bounds_of_hollow_mesh_do_not_imply_penetration():
    bars=[]
    for x in (-.95,.95):
        bar=trimesh.creation.box(extents=[.1,2,2]);bar.apply_translation([x,0,0]);bars.append(bar)
    frame=trimesh.util.concatenate(bars)
    inside_gap=trimesh.creation.box(extents=[.4,.4,.4])
    assert sampled_penetration(inside_gap.triangles,frame.triangles,.001)==0


def test_mask_refinement_retains_a_depth_separated_small_object(tmp_path):
    from mapmaker.mask_geometry import refine_selected
    large=np.zeros((100,100),np.uint8);large[10:90,10:90]=255
    small=np.zeros_like(large);small[10:30,10:90]=255
    Image.fromarray(large).save(tmp_path/'large.png');Image.fromarray(small).save(tmp_path/'small.png')
    meta=dict(objects=[dict(id='a',name='same',mask='large.png',status='masked'),dict(id='b',name='same',mask='small.png',status='masked')])
    y,x=np.mgrid[:100,:100];points=np.stack([x/100,y/100,np.ones_like(x)],axis=-1)
    points[small>0,2]+=.2
    refine_selected(tmp_path,meta,points,np.full((100,100,3),128,np.uint8))
    assert all(o['status']=='masked' for o in meta['objects'])
    assert meta['geometric_mask_selection']['decisions']==[]


def test_wall_attachment_uses_observed_patch_and_keeps_large_gaps():
    wall=trimesh.Trimesh(vertices=[[-2,0,0],[2,0,0],[2,3,0],[-2,3,0]],faces=[[0,1,2],[0,2,3]])
    panel=trimesh.creation.box(extents=[1,.8,.1]);panel.apply_translation([0,1.5,.07])
    delta=wall_contact(panel.vertices,wall.triangles,[0,0,1],[0,0,0])
    np.testing.assert_allclose(delta,[0,0,-.02],atol=1e-8)
    panel.apply_translation([0,0,1]);assert wall_contact(panel.vertices,wall.triangles,[0,0,1],[0,0,0]) is None
    panel.apply_translation([4,0,-1]);assert wall_contact(panel.vertices,wall.triangles,[0,0,1],[0,0,0]) is None


@pytest.mark.parametrize('scale',[.1,1.,10.])
def test_ceiling_contact_is_geometric_bounded_and_source_guarded(scale):
    def run(offset=0,gap=.02,allow=True,name='arbitrary'):
        scene,objects,placement=scene_of([(name,np.array([1,1,1])*scale,np.array([0,.5,0])*scale)])
        ceiling=trimesh.Trimesh(vertices=np.array([[-2,1+gap,-2],[2,1+gap,-2],
            [2,1+gap,2],[-2,1+gap,2]])*scale+np.array([offset*scale,0,0]),faces=[[0,1,2],[0,2,3]])
        scene.add_geometry(ceiling,node_name='ceiling_patch')
        surface=dict(node='ceiling_patch',kind='ceiling',normal=[0,-1,0],
            point=[0,(1+gap)*scale,0],bounds=ceiling.bounds.tolist())
        improve_contacts(scene,objects,placement,dict(surfaces=[surface]),
            source_guard=lambda obj,delta:dict(accepted=allow,reason='test_source_evidence'))
        return scene,objects,placement
    scene,objects,placement=run()
    assert placement['contacts']['relations'][0]['type']=='ceiling_contact'
    np.testing.assert_allclose(objects[0]['placement']['contacts'][0]['translation'],[0,.02*scale,0],atol=1e-8)
    renamed,other,report=run(name='')
    np.testing.assert_allclose(scene.graph[objects[0]['id']][0],renamed.graph[other[0]['id']][0])
    for args in [dict(offset=10),dict(gap=1),dict(allow=False)]:
        _,_,report=run(**args)
        assert not report['contacts']['changes']


def test_structure_roundtrip_and_idempotence(tmp_path):
    scene,objects,_=scene_of([('arbitrary',[.5,1,.5],[0,-1,2])])
    # scene_of already transformed once; restore its raw roots for finalization.
    for obj in objects:
        scene.graph.update(frame_from=scene.graph.base_frame,frame_to=obj['id'],matrix=obj['placement']['original_matrix'])
        obj.update(status='generated',mask='mask.png')
    scene.export(tmp_path/'scene.glb')
    Image.fromarray(np.zeros((80,80),np.uint8)).save(tmp_path/'mask.png')
    np.savez_compressed(tmp_path/'pointmap.npz',points=room_pointmap())
    write(tmp_path/'scene_metadata.json',dict(objects=objects,pipeline={},pointmap=dict(
        asset='pointmap.npz',sha256=sha(tmp_path/'pointmap.npz'),frame='sam3d_pytorch3d_camera')))
    finalize_scene(tmp_path,render=False)
    meta=read(tmp_path/'scene_metadata.json');assert meta['pipeline']['structural_geometry']
    from mapmaker.scene_placement import PLACEMENT_VERSION
    assert meta['placement']['version']==PLACEMENT_VERSION
    loaded=trimesh.load(tmp_path/'scene.glb',force='scene')
    assert all(r['node'] in loaded.graph.nodes for r in meta['structure']['surfaces'])
    before=sha(tmp_path/'scene.glb');finalize_scene(tmp_path,render=False)
    assert sha(tmp_path/'scene.glb')==before
