import numpy as np
from PIL import Image

from mapmaker.mask_geometry import refine_selected
from mapmaker.scene_structure import observed_context_mesh


def test_observed_triangle_checks_its_interior_without_eroding_neighbors():
    from mapmaker.scene_structure import observed_grid_triangles
    support=np.ones((9,9),bool)
    support[3,3]=False  # Inside only the lower-right triangle of the first cell.
    actual=observed_grid_triangles(support,4).reshape(2,2,2)
    expected=np.ones((2,2,2),bool);expected[1,0,0]=False
    np.testing.assert_array_equal(actual,expected)
    support[1,3]=False  # Shared diagonal belongs to both triangles.
    assert not observed_grid_triangles(support,4).reshape(2,2,2)[:,0,0].any()


def test_observed_triangles_retain_fully_supported_mesh_area():
    y,x=np.mgrid[:512,:512]
    points=np.stack([x/512,y/512,np.ones_like(x)],-1).astype(float)
    mask=np.ones((512,512),bool);mask[:,255]=False
    mesh=observed_context_mesh(points,mask,np.full((512,512,3),128,np.uint8),np.eye(4),[])
    # Only the strip containing the hole is excluded, not neighboring cells.
    expected=(510/512)*(508/512)
    assert abs(mesh.area-expected)<1e-10
import trimesh


def test_full_view_context_preserves_small_instances_and_source_masks(tmp_path):
    y, x = np.mgrid[:100, :100]
    points = np.stack([x/100, y/100, 2 + x/200], -1)
    masks = {'context': np.ones((100,100), bool), 'first': np.zeros((100,100), bool), 'second': np.zeros((100,100), bool)}
    masks['first'][20:35,20:35] = True
    masks['second'][60:75,60:75] = True
    meta = dict(objects=[])
    original = {}
    for key, mask in masks.items():
        path = tmp_path/f'{key}.png'
        Image.fromarray(mask.astype(np.uint8)*255).save(path)
        original[path] = path.read_bytes()
        meta['objects'].append(dict(id=key, name='same', mask=path.name, status='masked'))
    refine_selected(tmp_path, meta, points, np.full((100,100,3),128,np.uint8))
    assert meta['objects'][0]['status'] == 'structural'
    assert meta['objects'][0]['structural_evidence']['observed_context']
    assert [o['status'] for o in meta['objects'][1:]] == ['masked', 'masked']
    assert all(path.read_bytes() == data for path, data in original.items())


def test_one_full_frame_object_without_instance_evidence_is_retained(tmp_path):
    y, x = np.mgrid[:100, :100]
    points = np.stack([x/100, y/100, np.ones_like(x)], -1)
    Image.fromarray(np.full((100,100),255,np.uint8)).save(tmp_path/'mask.png')
    meta = dict(objects=[dict(id='one', name='anything', mask='mask.png', status='masked')])
    refine_selected(tmp_path, meta, points, np.full((100,100,3),128,np.uint8))
    assert meta['objects'][0]['status'] == 'masked'


def test_measured_context_has_no_depth_or_mask_bridges():
    y,x = np.mgrid[:80,:80]
    points = np.stack([x/80, y/80, np.ones_like(x)], -1)
    points[:,40:,2] = 3
    mask = np.ones((80,80),bool); mask[30:50,10:30] = False
    mesh = observed_context_mesh(points, mask, np.full((80,80,3),128,np.uint8), np.eye(4), [])
    assert mesh is not None
    assert np.ptp(mesh.triangles[:,:,2],axis=1).max() == 0
    centers = mesh.triangles_center
    assert not np.any((centers[:,0] > 10/80) & (centers[:,0] < 29/80) &
                      (centers[:,1] > 30/80) & (centers[:,1] < 49/80))
    assert set(np.unique(mesh.vertices[:,2])) == {1.,3.}


def test_downsampling_does_not_bridge_subsample_mask_depth_holes_or_jumps():
    y,x=np.mgrid[:512,:512]
    base=np.stack([x/512,y/512,np.ones_like(x)],-1).astype(float)
    for kind in ('mask','missing','jump'):
        points=base.copy();mask=np.ones((512,512),bool)
        if kind=='mask':mask[255,255]=False
        elif kind=='missing':points[255,255]=np.nan
        else:points[255,255,2]=4
        mesh=observed_context_mesh(points,mask,np.full((512,512,3),128,np.uint8),np.eye(4),[])
        assert mesh is not None
        lower=mesh.triangles.min(1);upper=mesh.triangles.max(1)
        assert not np.any((lower[:,0]<=255/512)&(upper[:,0]>=255/512)&
                          (lower[:,1]<=255/512)&(upper[:,1]>=255/512))


def test_finite_plane_holes_remain_available_for_observed_context():
    y,x=np.mgrid[:80,:80]
    points=np.stack([x/79,y/79,np.ones_like(x)],-1)
    vertices=np.array([[0,0,1],[.2,0,1],[.2,1,1],[0,1,1],
                       [.8,0,1],[1,0,1],[1,1,1],[.8,1,1]])
    mesh=trimesh.Trimesh(vertices,[[0,1,2],[0,2,3],[4,5,6],[4,6,7]],process=False)
    plane=dict(point=[0,0,1],normal=[0,0,1],tolerance=.005,bounds=[[0,0,1],[1,1,1]])
    context=observed_context_mesh(points,np.ones((80,80),bool),np.full((80,80,3),128,np.uint8),
        np.eye(4),[plane],plane_faces=[mesh.triangles])
    assert context is not None
    assert context.bounds[0,0]>.2 and context.bounds[1,0]<.8


def test_unclassified_background_is_preserved_without_asserting_room_orientation(tmp_path):
    from mapmaker.scene_structure import restore_structure
    from mapmaker.scene_run import sha
    y,x=np.mgrid[:80,:80]
    points=np.stack([x/80,y/80,np.ones_like(x)],-1)
    np.savez_compressed(tmp_path/'points.npz',points=points)
    Image.fromarray(np.full((80,80,3),128,np.uint8)).save(tmp_path/'input.png')
    meta=dict(objects=[],input_image='input.png',pointmap=dict(asset='points.npz',
        frame='sam3d_pytorch3d_camera',sha256=sha(tmp_path/'points.npz')))
    placement=dict(common_transform=np.eye(4),orientation_evidence=dict(accepted=False))
    result=restore_structure(tmp_path,trimesh.Scene(),meta,placement)
    assert [s['kind'] for s in result['surfaces']]==['observed']
    assert result['surfaces'][0]['unclaimed_background_included']
    disabled=restore_structure(tmp_path,trimesh.Scene(),meta,placement,include_unclaimed=False)
    assert not disabled['surfaces']


def test_classified_plane_does_not_bridge_missing_or_masked_subsample():
    from mapmaker.scene_structure import fit_surfaces
    y, x = np.mgrid[:512, :512]
    base = np.stack([x/512, y/512, np.ones_like(x)], -1).astype(float)
    for missing in (True, False):
        points = base.copy()
        excluded = np.zeros((512,512), bool)
        if missing:
            points[255,255] = np.nan
        else:
            excluded[255,255] = True
        patches, _ = fit_surfaces(points, excluded, np.eye(4))
        assert patches
        for mesh, _ in patches:
            # The other half of a cell may have the same bounding rectangle
            # without covering the missing pixel. Test the triangles themselves.
            hole=np.broadcast_to(base[255,255],(len(mesh.faces),3))
            closest=trimesh.triangles.closest_point(mesh.triangles,hole)
            assert np.linalg.norm(closest-hole,axis=1).min()>1e-8


def test_room_normal_requires_observed_neighbors_not_only_center():
    from mapmaker.scene_structure import observed_normals
    y,x=np.mgrid[:30,:30]
    world=np.stack([x/30,y/30,np.ones_like(x)],-1).astype(float)
    observed=np.ones((30,30),bool)
    observed[:,15]=False
    world[:,15,2]=1.01
    normals,reliable=observed_normals(world,observed)
    assert not reliable[:,14:17].any()
    assert not normals[:,14:17].any()
    assert reliable[2:-2,2:13].all()
    assert np.allclose(abs(normals[reliable,2]),1)


def test_classified_plane_preserves_observed_cells_next_to_exclusion():
    from mapmaker.scene_structure import fit_surfaces
    y,x=np.mgrid[:512,:512]
    points=np.stack([x/512,y/512,np.ones_like(x)],-1).astype(float)
    excluded=np.zeros((512,512),bool);excluded[:,255]=True
    patches,_=fit_surfaces(points,excluded,np.eye(4))
    assert len(patches)==1
    mesh,record=patches[0]
    assert record['kind']=='wall' and record['inferred_pixels']==0
    assert record['fully_observed_triangles']==len(mesh.faces)
    assert record['occlusion_extended_triangles']==0
    assert abs(mesh.area-(508/512)*(504/512))<1e-10
