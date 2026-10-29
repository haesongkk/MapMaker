import numpy as np
import pytest
from mapmaker.depth_floor import estimate_floor,infer_contacts


def room(roll=0):
 y,x=np.mgrid[:100,:120];rx=(x-60)/100;ry=(45-y)/100
 depth=np.where(ry<-.01,np.minimum(-1/np.minimum(ry,-.001),5),5)
 points=np.stack([rx*depth,ry*depth,depth],-1)
 a=np.deg2rad(roll);r=np.array([[np.cos(a),-np.sin(a),0],[np.sin(a),np.cos(a),0],[0,0,1]])
 return points@r.T,r


def test_floor_recovers_camera_roll_without_object_ups():
 points,r=room(17);mask=np.zeros(points.shape[:2],bool);mask[60:85,40:80]=True
 points[mask]+=np.array([0,.7,0])@r.T
 transform,e=estimate_floor(points,mask)
 expected=r@np.array([0,1,0])
 assert np.dot(e['selected']['normal'],expected)>.999
 world=points@transform[:3,:3].T+transform[:3,3]
 assert np.max(np.abs(world[90:,:,1]))<1e-5
 assert e['method']=='background_ransac_floor_no_object_up'


def test_wall_only_is_not_promoted_to_floor():
 y,x=np.mgrid[:100,:120];points=np.stack([(x-60)/30,(50-y)/30,np.full_like(x,5)],-1)
 with pytest.raises(ValueError,match='No sufficiently supported floor'):estimate_floor(points,np.zeros((100,120),bool))


def test_no_depth_refuses_alignment():
 with pytest.raises(ValueError,match='Insufficient'):estimate_floor(np.full((100,120,3),np.nan),np.zeros((100,120),bool))


def test_elevated_isolated_object_is_not_snapped_to_floor():
 y,x=np.mgrid[:40,:40];p=np.stack([x*.01,y*.01+1,np.ones_like(x)],-1)
 rows=infer_contacts(p,{'unknown':np.ones((40,40),bool)},.01)
 assert rows['unknown']['target'] is None
 assert not rows['unknown']['source_floor_contact']


def test_duplicate_floor_observations_are_not_stacked():
 y,x=np.mgrid[:40,:40];p=np.stack([x*.01,y*.01,np.ones_like(x)],-1)
 mask=np.ones((40,40),bool)
 rows=infer_contacts(p,{'a':mask,'b':mask.copy()},.01)
 assert all(r['target']=='floor' and not r['candidates'] for r in rows.values())
