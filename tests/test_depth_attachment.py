import numpy as np
import trimesh
from mapmaker.depth_attachment import recover_attachment,surface_mesh,join_body,settle_rigid,fit_attachment_contact
from mapmaker.scene_geometry import contact_footprint,contact_polygon_margin


def fixture(scale=1.):
 y,x=np.mgrid[:100,:100];p=np.stack([(x-50)*.01,(100-y)*.01,np.full_like(x,.03,dtype=float)],-1)
 body=(x>=25)&(x<=75)&(y<=40)
 stem=(x>=45)&(x<=55)&(y>=40)&(y<=70)
 p[~(body|stem)]=np.nan
 colors=np.zeros((100,100,3),np.uint8)+10
 return p*scale,body,stem,colors


def test_connected_observation_recovered_and_scale_invariant():
 p,b,stem,c=fixture();v=p[b]
 mask,e=recover_attachment(v,p,b,np.zeros_like(b),.3,.02,c,np.array([150,100,80]))
 assert mask is not None and np.sum(mask&stem)>250
 assert e['reason']=='observed_rgbd_bridge'
 p2,b2,_,_=fixture(9)
 m2,_=recover_attachment(p2[b2],p2,b2,np.zeros_like(b2),2.7,.18,c,np.array([150,100,80]))
 assert np.array_equal(mask,m2)


def test_other_object_pixels_not_reconstructed_as_attachment():
 p,b,stem,c=fixture()
 mask,e=recover_attachment(p[b],p,b,stem,.3,.02,c,np.array([150,100,80]))
 assert mask is None


def test_no_observed_bridge_is_not_fabricated():
 p,b,stem,c=fixture();p[stem&~b]=np.nan
 mask,e=recover_attachment(p[b],p,b,np.zeros_like(b),.3,.02,c,np.array([150,100,80]))
 assert mask is None


def test_surface_mesh_does_not_join_disconnected_depth_layers():
 y,x=np.mgrid[:10,:10];p=np.stack([x*.01,y*.01,np.zeros_like(x)],-1);p[:,5:,2]=3
 v,f,c=surface_mesh(p,np.zeros((10,10,3),np.uint8),np.ones((10,10),bool),.02)
 assert len(f)>0
 assert np.ptp(v[:,2])==0
 assert np.max(np.linalg.norm(v[f]-np.roll(v[f],1,axis=1),axis=2))<=.02


def test_body_join_is_bounded_and_connects_without_stretching_base():
 body=trimesh.creation.box(extents=[1,.4,.4]);body.apply_translation([0,.8,0])
 patch=trimesh.creation.box(extents=[.1,.3,.1]);patch.apply_translation([0,.43,0])
 joined,e=join_body(patch.vertices,body.vertices,body.faces,.01)
 assert joined is not None and e['body_contact_vertices']>=3
 assert abs(joined[:,1].max()-.6)<1e-8
 far=patch.vertices+[0,-3,0]
 rejected,e=join_body(far,body.vertices,body.faces,.01)
 assert rejected is None


def test_settle_rigid_closes_large_gap_on_actual_support():
 body=trimesh.creation.box(extents=[.3,.4,.3]);body.apply_translation([0,1.4,0])
 parent=trimesh.creation.box(extents=[2,.2,2]);parent.apply_translation([0,.9,0])
 transform,e=settle_rigid(body.vertices,parent.triangles,.01,body.center_mass)
 assert transform is not None
 moved=trimesh.transform_points(body.vertices,transform)
 assert abs(moved[:,1].min()-1)<1e-8
 assert e['verification']['load_bearing_queries']>=3


def test_contact_sampling_and_margin_are_rigid_translation_invariant():
 y,x=np.mgrid[:6,:6];points=np.stack([x.ravel()*.1,np.zeros(36),y.ravel()*.1],1)
 shift=np.array([.019630758,.0710888,-.013881])
 assert np.allclose(contact_footprint(points)+shift,contact_footprint(points+shift))
 poly=np.array([[-.2,-.01],[.2,-.01],[.2,.01],[-.2,.01]])
 assert np.isclose(contact_polygon_margin(poly),.0002)


def test_joint_fit_makes_contact_and_preserves_upper_joint():
 body=trimesh.creation.box(extents=[1,.4,.4]);body.apply_translation([0,.8,0])
 patch=trimesh.creation.box(extents=[.2,.4,.2]);patch.apply_translation([0,.4,0])
 parent=trimesh.creation.box(extents=[2,.2,2])
 fitted,transform,e=fit_attachment_contact(patch.vertices,body.vertices,body.faces,parent.triangles,.01,body.center_mass)
 assert transform is not None and fitted is not None
 assert np.allclose(fitted[patch.vertices[:,1]>.59],patch.vertices[patch.vertices[:,1]>.59])
 assert abs(trimesh.transform_points(fitted,transform)[:,1].min()-.1)<1e-8
 assert abs(e['verification']['shift'])<1e-8


def test_added_part_is_bound_to_owner_and_original_binary_preserved(tmp_path):
 from scripts.complete_depth_support import append_patches
 from mapmaker.baseline_assembly import read_header
 scene=trimesh.Scene();t=np.eye(4);t[:3,3]=[2,3,4]
 scene.add_geometry(trimesh.creation.box(),node_name='owner',transform=t)
 source=tmp_path/'source.glb';source.write_bytes(scene.export(file_type='glb'))
 v=np.array([[2,3,4],[2.2,3,4],[2,3.2,4]],float);f=np.array([[0,1,2]])
 result=tmp_path/'result.glb';append_patches(source,result,[('owner',v,f,np.full((3,3),20,np.uint8))])
 doc,offset,size=read_header(result);old,old_offset,old_size=read_header(source)
 assert result.read_bytes()[offset:offset+old_size]==source.read_bytes()[old_offset:old_offset+old_size]
 owner=next(n for n in doc['nodes'] if n.get('name')=='owner')
 assert any(doc['nodes'][i].get('name')=='owner_observed_connection' for i in owner['children'])
 loaded=trimesh.load(result,force='scene',process=False)
 transform,geometry_name=loaded.graph['owner_observed_connection']
 assert np.allclose(trimesh.transform_points(loaded.geometry[geometry_name].vertices,transform),v,atol=1e-6)
