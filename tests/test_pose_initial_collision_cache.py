import numpy as np
import trimesh

from mapmaker.scene_collision import MeshIndex
from mapmaker.scene_pose_refinement import pose_collision_checks


def test_initial_cache_preserves_geometry_verdicts_and_rechecks_every_endpoint():
    moving=trimesh.creation.box().triangles
    fixed_mesh=trimesh.creation.box();fixed_mesh.apply_translation([.8,0,0])
    bounds={'moving':np.array([moving.min((0,1)),moving.max((0,1))]),'fixed':fixed_mesh.bounds}
    class CountingIndex(MeshIndex):
        def __init__(self):
            super().__init__(fixed_mesh.triangles)
            self.initial_calls=0;self.endpoint_calls=0
        def swept_collision(self, faces, delta, **kwargs):
            if np.array_equal(faces,moving):self.initial_calls+=1
            else:self.endpoint_calls+=1
            return super().swept_collision(faces,delta,**kwargs)
    transforms=[]
    for x in (.01,.02):
        transform=np.eye(4);transform[0,3]=x;transforms.append(transform)
    def run(shared):
        index=CountingIndex();cache={};records=[]
        for transform in transforms:
            records.append(pose_collision_checks(moving,transform,bounds,'moving',set(),lambda _:index,
                           initial_cache=cache if shared else None))
        return records,index
    uncached,a=run(False);cached,b=run(True)
    assert cached==uncached
    assert a.initial_calls==2 and b.initial_calls==1
    assert a.endpoint_calls==b.endpoint_calls==2
    assert all(r[0]['after']=='intersection' for r in cached)
