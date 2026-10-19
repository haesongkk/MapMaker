import numpy as np
import trimesh
from mapmaker.scene_contact_retention import contact_retention


def test_side_contact_loss_is_detected_and_equivalent_surface_retained():
    wall=trimesh.creation.box(extents=[.1,2,2]);wall.apply_translation([-.05,0,0])
    body=trimesh.creation.box(extents=[1,.4,.4]);body.apply_translation([.5,0,0])
    missing=wall.copy();missing.apply_translation([-1,0,0])
    lost=contact_retention(wall.triangles,missing.triangles,body.triangles,.01)
    assert lost['status']=='sampled_contact_lost' and lost['lost_contacts']>0
    same=contact_retention(wall.triangles,wall.triangles,body.triangles,.01)
    assert same['status']=='sampled_contacts_retained' and not same['suppression_authorized']
    rotation=trimesh.transformations.rotation_matrix(np.pi/2,[0,0,1])
    for mesh in (wall,body,missing):mesh.apply_transform(rotation)
    assert contact_retention(wall.triangles,missing.triangles,body.triangles,.01)['status']=='sampled_contact_lost'


def test_no_contacts_does_not_authorize_removal():
    a=trimesh.creation.box();b=a.copy();b.apply_translation([5,0,0])
    evidence=contact_retention(a.triangles,a.triangles,b.triangles,.01)
    assert evidence['observed_contacts']==0 and not evidence['suppression_authorized']
