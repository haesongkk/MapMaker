import numpy as np
import pytest
import trimesh

from mapmaker.scene_collision import MeshIndex


@pytest.mark.parametrize('bulk_available', [True,False])
def test_batched_queries_preserve_each_exact_triangle_candidate_set(bulk_available):
    rng=np.random.default_rng(901)
    faces=rng.uniform(-1,1,(40,3,3))
    index=MeshIndex(faces)
    lower=rng.uniform(-2,2,(273,3));upper=lower+rng.uniform(0,.5,(273,3))
    candidates=np.arange(len(lower))
    expected={i:sorted(index.tree.intersection(np.r_[lower[i],upper[i]])) for i in candidates}
    if not bulk_available:
        original=index.tree
        class ScalarOnly:
            count=original.count
            intersection=original.intersection
            def intersection_v(self,*args):raise TypeError('unsupported bulk binding')
        index.tree=ScalarOnly()
    actual={int(i):sorted(ids.tolist()) for i,ids in index._candidate_intersections(lower,upper,candidates)}
    assert actual=={i:ids for i,ids in expected.items() if ids}
    assert list(actual)==sorted(actual)


def test_bulk_queries_keep_pair_budget_unknown_and_real_collision_verdicts():
    mesh=trimesh.creation.box()
    index=MeshIndex(mesh.triangles)
    moving=mesh.triangles+[.8,0,0]
    assert index.swept_collision(moving,np.zeros(3),max_pairs=0) is None
    assert index.swept_collision(moving,np.zeros(3)) is True
    assert index.swept_collision(moving+[3,0,0],np.zeros(3)) is False


def test_dense_group_uses_scalar_queries_without_large_bulk_allocation():
    index=MeshIndex(trimesh.creation.box().triangles)
    class Dense:
        def count(self,bounds):return 100001
        def intersection(self,bounds):return iter([2])
        def intersection_v(self,*args):raise AssertionError('unbounded bulk query')
    index.tree=Dense()
    rows=list(index._candidate_intersections(np.zeros((2,3)),np.ones((2,3)),np.arange(2)))
    assert [(int(i),ids.tolist()) for i,ids in rows]==[(0,[2]),(1,[2])]
