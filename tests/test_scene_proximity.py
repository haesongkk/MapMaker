import numpy as np
import pytest
import trimesh

from mapmaker.scene_proximity import closest_points


@pytest.mark.parametrize('budget',[1,37,262144])
def test_exact_reference_for_surface_edges_vertices_and_distant_queries(budget):
    mesh=trimesh.util.concatenate([trimesh.creation.box(),
        trimesh.creation.icosphere(subdivisions=2).apply_translation([4,1,0])])
    random=np.random.default_rng(12).normal(size=(91,3))
    points=np.concatenate([mesh.vertices[::29],mesh.triangles_center[::23],random,random*20])
    expected=trimesh.proximity.closest_point(mesh,points)
    actual=closest_points(mesh,points,pair_budget=budget,prune=True)
    for a,b in zip(expected,actual):
        np.testing.assert_array_equal(a,b)


def test_candidate_work_is_bounded_without_dropping_far_observations(monkeypatch):
    mesh=trimesh.creation.icosphere(subdivisions=2)
    points=np.random.default_rng(7).normal(size=(67,3))*30
    expected=trimesh.proximity.closest_point(mesh,points)
    original=trimesh.triangles.closest_point
    sizes=[]
    def measured(triangles,queries):
        sizes.append(len(triangles))
        return original(triangles,queries)
    monkeypatch.setattr(trimesh.triangles,'closest_point',measured)
    actual=closest_points(mesh,points,pair_budget=750)
    assert len(sizes)>1 and max(sizes)<=max(750,len(mesh.faces))
    for a,b in zip(expected,actual):
        np.testing.assert_array_equal(a,b)


def test_empty_queries_and_invalid_observations():
    mesh=trimesh.creation.box()
    close,distance,ids=closest_points(mesh,np.empty((0,3)))
    assert close.shape==(0,3) and distance.shape==ids.shape==(0,)
    with pytest.raises(ValueError):
        closest_points(mesh,[[np.nan,0,0]])


def test_failed_vector_query_is_not_repeated_and_geometry_mutation_retries(monkeypatch):
    import rtree
    mesh=trimesh.creation.icosphere(subdivisions=2)
    points=np.random.default_rng(19).normal(size=(35,3))*4
    expected=trimesh.proximity.closest_point(mesh,points);calls=[]
    def incompatible(*args,**kwargs):
        calls.append(1);raise TypeError('integer buffer size required')
    monkeypatch.setattr(rtree.index.Index,'intersection_v',incompatible)
    for _ in range(2):
        actual=closest_points(mesh,points,pair_budget=700)
        for a,b in zip(actual,expected):np.testing.assert_array_equal(a,b)
    assert len(calls)==1
    mesh.vertices += [1,0,0]
    actual=closest_points(mesh,points,pair_budget=700)
    assert len(calls)==2
    expected=trimesh.proximity.closest_point(mesh,points)
    for a,b in zip(actual,expected):np.testing.assert_array_equal(a,b)


@pytest.mark.parametrize('budget', [1,262144])
def test_large_mesh_pruning_preserves_reference_ties(budget):
    mesh=trimesh.creation.icosphere(subdivisions=4)
    points=np.concatenate([mesh.vertices[::401],mesh.triangles_center[::701],
        np.random.default_rng(9).normal(size=(20,3))*3])
    expected=closest_points(mesh,points,pair_budget=budget,prune=False)
    actual=closest_points(mesh,points,pair_budget=budget,prune=True)
    for a,b in zip(expected,actual):np.testing.assert_array_equal(a,b)


def test_cached_indices_follow_vertex_and_face_mutation():
    mesh=trimesh.creation.icosphere(subdivisions=4)
    points=np.array([[0,0,2.],[1,2,3.],[-2,-2,0.]])
    closest_points(mesh,points,prune=True)
    tree=mesh._cache['mapmaker_proximity_vertex_tree']
    closest_points(mesh,points)
    assert mesh._cache['mapmaker_proximity_vertex_tree'] is tree
    for change in ('vertices','faces'):
        if change=='vertices':mesh.vertices += [3.,1.,-.5]
        else:mesh.faces=mesh.faces[::2].copy()
        actual=closest_points(mesh,points,prune=True)
        expected=trimesh.proximity.closest_point(mesh,points)
        for a,b in zip(expected,actual):np.testing.assert_array_equal(a,b)
        assert mesh._cache['mapmaker_proximity_vertex_tree'] is not tree
        tree=mesh._cache['mapmaker_proximity_vertex_tree']


def test_dense_plane_pruning_reduces_triangle_work_without_changing_answers(monkeypatch):
    n=70;y,x=np.mgrid[:n,:n]
    vertices=np.stack([x.ravel(),y.ravel(),np.zeros(n*n)],axis=1)/n
    a=np.arange(n*n).reshape(n,n)[:-1,:-1].ravel()
    faces=np.concatenate([np.stack([a,a+1,a+n],1),np.stack([a+1,a+n+1,a+n],1)])
    mesh=trimesh.Trimesh(vertices,faces,process=False)
    points=np.column_stack([np.random.default_rng(1).uniform(.2,.8,(10,2)),np.ones(10)])
    calls=[];original=trimesh.triangles.closest_point
    def measured(triangles,queries):
        calls.append(len(triangles));return original(triangles,queries)
    monkeypatch.setattr(trimesh.triangles,'closest_point',measured)
    expected=closest_points(mesh,points,prune=False);unpruned=sum(calls);calls.clear()
    actual=closest_points(mesh,points,prune=True)
    assert sum(calls)<unpruned*.1
    for a,b in zip(expected,actual):np.testing.assert_array_equal(a,b)
