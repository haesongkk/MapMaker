"""Observed room patches from the SAME pointmap used for SAM3D layout.

No room box is fabricated. Missing pixels, masks and unsupported gaps stay holes.
The shared alignment is the only coordinate transform applied to these points.
"""
from pathlib import Path
import numpy as np
from PIL import Image
import trimesh
from scipy.ndimage import label, minimum_filter, maximum_filter


def observed_normals(world, observed=None):
    """Centered local normals, excluding depth-jump chords and invalid pixels."""
    normals = np.zeros_like(world)
    dx = world[1:-1,2:]-world[1:-1,:-2]
    dy = world[2:,1:-1]-world[:-2,1:-1]
    cross = np.cross(dx,dy)
    lengths = np.linalg.norm(cross,axis=-1)
    edges = np.maximum(np.linalg.norm(dx,axis=-1),np.linalg.norm(dy,axis=-1))
    valid = np.isfinite(cross).all(-1) & (lengths>1e-12) & np.isfinite(edges)
    if observed is not None:
        observed = np.asarray(observed, bool)
        if observed.shape != world.shape[:2]:
            raise ValueError('Expected a matching observed-pixel mask')
        # An unmasked center does not make its neighbors room observations.
        # Object silhouettes and invalid depth must not supply a wall normal.
        valid &= (observed[1:-1,1:-1] & observed[:-2,1:-1] & observed[2:,1:-1]
                  & observed[1:-1,:-2] & observed[1:-1,2:])
    if valid.any():
        valid &= edges <= np.median(edges[valid])*4
    normals[1:-1,1:-1] = np.divide(cross,lengths[...,None],out=np.zeros_like(cross),
        where=valid[...,None])
    return normals, np.linalg.norm(normals,axis=-1)>.5


def enclosed_occlusion_points(world, observed, excluded, camera, center, normal):
    """Extend a measured plane only into bounded foreground occlusions.

    Four-sided observed support is required. Do not fill image edges, windows,
    unobserved depth, or pixels whose measured surface is behind the plane.
    """
    radius = max(2, min(world.shape[:2])//8)
    supported = np.ones(observed.shape, bool)
    for dy, dx in ((0,1),(0,-1),(1,0),(-1,0)):
        seen = np.zeros_like(observed)
        for distance in range(1,radius+1):
            shifted = np.roll(observed, (dy*distance,dx*distance), (0,1))
            if dy > 0: shifted[:distance] = False
            if dy < 0: shifted[-distance:] = False
            if dx > 0: shifted[:,:distance] = False
            if dx < 0: shifted[:,-distance:] = False
            seen |= shifted
        supported &= seen
    ray = world-camera
    denominator = ray@normal
    factor = np.divide(np.dot(center-camera,normal),denominator,
                       out=np.full(denominator.shape,np.nan),where=abs(denominator)>1e-9)
    inferred = excluded & supported & np.isfinite(world).all(axis=-1) & (factor>1.01) & (factor<4)
    # Large contiguous missing areas remain unknown, even with surrounding evidence.
    if inferred.sum() > observed.sum()*.25:
        inferred[:] = False
    projected = camera+ray*factor[...,None]
    return inferred, projected


def fit_surfaces(points, excluded, common, *, max_planes=12, proposal_method='random_triples', occlusion_method='four_sided', reference_excluded=None):
    if proposal_method not in ('random_triples','stable_normals','stable_consistent_normals','global_stable_normals','reference_stable_normals'):
        raise ValueError('Unknown plane proposal method')
    if occlusion_method not in ('four_sided','local_plane_hull','local_plane_components','local_plane_optimal','local_plane_evidence','enclosed_plane_evidence'):
        raise ValueError('Unknown plane occlusion method')
    points = np.asarray(points, dtype=float)
    if points.ndim != 3 or points.shape[-1] != 3 or excluded.shape != points.shape[:2]:
        raise ValueError('Expected HxWx3 pointmap and matching exclusion mask')
    if proposal_method=='reference_stable_normals' and (reference_excluded is None or np.asarray(reference_excluded).shape!=excluded.shape):
        raise ValueError('Reference fitting requires a matching original exclusion mask')
    full_points, full_excluded = points, np.asarray(excluded,bool)
    # Bound CPU and exported mesh size independently of the input resolution.
    step = max(1, int(np.ceil(max(points.shape[:2])/160)))
    full_valid = np.isfinite(points).all(axis=-1) & (np.linalg.norm(points, axis=-1) > 1e-6)
    # Preserve evidence between retained grid sites. A missing depth sample
    # is never evidence for the bounded foreground-occlusion extension.
    safe_depth = minimum_filter(full_valid.astype(np.uint8), size=2*step+1, mode='nearest') > 0
    safe_observed = minimum_filter((full_valid & ~excluded).astype(np.uint8),
                                  size=2*step+1, mode='nearest') > 0
    safe_depth = safe_depth[::step, ::step]
    safe_observed = safe_observed[::step, ::step]
    points, excluded = points[::step, ::step], excluded[::step, ::step]
    valid = np.isfinite(points).all(axis=-1) & (np.linalg.norm(points, axis=-1) > 1e-6) & ~excluded
    world = trimesh.transform_points(points.reshape(-1, 3), common).reshape(points.shape)
    normals, reliable_normals = observed_normals(world, safe_observed & valid)
    available = valid.copy()
    if valid.sum() < 100:
        return [], {'reason': 'insufficient_background_points', 'valid_points': int(valid.sum())}
    cloud = world[valid]
    span = float(np.linalg.norm(np.quantile(cloud, .95, axis=0)-np.quantile(cloud, .05, axis=0)))
    tolerance = max(span*.008, 1e-6)
    camera = np.asarray(common)[:3, 3]
    rng = np.random.default_rng(42)
    if proposal_method in ('global_stable_normals','reference_stable_normals'):
        # Candidate geometry comes from shared depth before instance exclusion.
        # Background masks still decide which patches may actually be exported.
        if proposal_method=='reference_stable_normals':
            reference_valid=full_valid & ~np.asarray(reference_excluded,bool)
            global_available=reference_valid[::step,::step].copy()
            reference_safe=minimum_filter(reference_valid.astype(np.uint8),size=2*step+1,mode='nearest')>0
            global_normals,global_reliable=observed_normals(world,reference_safe[::step,::step]&global_available)
        else:
            global_available=full_valid[::step,::step]&safe_depth
            global_normals,global_reliable=observed_normals(world,global_available)
        global_cloud=world[global_available]
        if len(global_cloud)<100:
            return [],dict(reason='insufficient_reliable_shared_depth',proposal_method=proposal_method)
        global_tolerance=max(float(np.linalg.norm(np.quantile(global_cloud,.95,axis=0)-np.quantile(global_cloud,.05,axis=0)))*.008,1e-6)
    patches = []
    rejected_planes = []
    # Rejected/fragmented candidates also consume attempts. Allow smaller room
    # faces after the dominant walls without lowering any evidence threshold.
    attempts = 0
    for _ in range(max_planes):
        attempts += 1
        flat = world[available]
        if len(flat) < 100:
            break
        fit_evidence = {}
        if proposal_method in ('global_stable_normals','reference_stable_normals'):
            from .stable_plane_proposals import propose_plane
            proposal=propose_plane(world,global_available,global_normals,global_reliable,global_tolerance)
            if proposal is None:break
            center,normal,fit_evidence=proposal
            global_available[abs((world-center)@normal)<global_tolerance]=False
            fit_evidence.update(fitting_scope='original_background_before_mask_refinement' if proposal_method=='reference_stable_normals' else 'shared_depth_before_instance_exclusion',fitting_tolerance=global_tolerance)
        elif proposal_method in ('stable_normals','stable_consistent_normals'):
            from .stable_plane_proposals import propose_plane
            proposal = propose_plane(world, available, normals, reliable_normals, tolerance,
                normal_consistent=proposal_method=='stable_consistent_normals')
            if proposal is None:
                break
            center, normal, fit_evidence = proposal
        else:
            ids = rng.choice(len(flat), min(len(flat), 4000), replace=False)
            sample = flat[ids]
            best = None
            for _ in range(128):
                a, b, c = sample[rng.choice(len(sample), 3, replace=False)]
                normal = np.cross(b-a, c-a)
                length = np.linalg.norm(normal)
                if length < 1e-9:
                    continue
                normal /= length
                # Vertical or horizontal plane; arbitrary wall heading is permitted.
                if .18 < abs(normal[1]) < .96:
                    continue
                inside = abs((sample-a)@normal) < tolerance
                score = int(inside.sum())
                if best is None or score > best[0]:
                    best = (score, inside)
            if best is None or best[0] < max(80, len(sample)*.06):
                break
            inliers = sample[best[1]]
            center = inliers.mean(axis=0)
            _, _, vh = np.linalg.svd(inliers-center, full_matrices=False)
            normal = vh[-1]
        if np.dot(camera-center, normal) < 0:
            normal = -normal
        residual = abs((world-center)@normal)
        mask = available & (residual < tolerance)
        available[mask] = False
        if abs(normal[1]) >= .96:
            # Relative to the camera, not any object's semantic category.
            kind = 'floor' if center[1] < camera[1]-tolerance*4 else 'ceiling' if center[1] > camera[1]+tolerance*4 else None
        elif abs(normal[1]) <= .18:
            kind = 'wall'
        else:
            kind = None
        if kind is None or mask.sum() < max(100, valid.size*.015):
            continue
        local_agreement = abs(normals[mask & reliable_normals]@normal)
        median_agreement = float(np.median(local_agreement)) if len(local_agreement) else 0.
        if len(local_agreement) < 64 or median_agreement < np.cos(np.deg2rad(15)):
            rejected_planes.append(dict(proposed_kind=kind, reason='local_surface_normals_disagree_with_fitted_plane',
                observed_pixels=int(mask.sum()), normal_samples=len(local_agreement),
                median_normal_agreement=median_agreement))
            continue
        components, _ = label(mask, np.ones((3,3)))
        sizes = np.bincount(components.ravel())[1:]
        connected_fraction = float(sizes.max()/mask.sum()) if len(sizes) else 0.
        classification = 'normal_and_observed_plane_geometry'
        if kind in ('floor','ceiling') and connected_fraction < .5:
            # Repeated disconnected horizontal surfaces may be object tops.
            # Preserve their observations without calling them a room boundary
            # or allowing them to become an unverified support plane.
            kind = 'observed'
            classification = 'fragmented_horizontal_surface_room_classification_withheld'
        projected = world - ((world-center)@normal)[..., None]*normal
        extension_evidence = {}
        if kind == 'observed':
            inferred, extension = np.zeros_like(mask), world
        elif occlusion_method in ('local_plane_hull','local_plane_components','local_plane_optimal','local_plane_evidence','enclosed_plane_evidence'):
            from .plane_occlusion import locally_enclosed_points
            inferred, extension, extension_evidence = locally_enclosed_points(world, mask, excluded, camera, center, normal,
                component_budget=occlusion_method in ('local_plane_components','local_plane_optimal'),
                optimal_budget=occlusion_method=='local_plane_optimal',
                local_evidence_only=occlusion_method=='local_plane_evidence',
                enclosed_evidence_only=occlusion_method=='enclosed_plane_evidence')
        else:
            inferred, extension = enclosed_occlusion_points(world, mask, excluded, camera, center, normal)
        inferred &= safe_depth
        projected[inferred] = extension[inferred]
        # Fit from the measured samples, but export only cells whose original
        # pixels support them. Eroding the fit itself can discard a valid wall.
        mesh_mask = (mask & safe_observed) | inferred
        h, w = mask.shape
        # Certify observed triangles using their actual original-pixel footprint.
        # Require dense agreement with this plane, not merely its three corners.
        camera_normal=np.asarray(common)[:3,:3].T@normal
        camera_offset=np.dot(center-camera,normal)
        dense_plane_support=full_valid & ~full_excluded & (abs(full_points@camera_normal-camera_offset)<tolerance)
        observed_triangles=observed_grid_triangles(dense_plane_support,step).reshape(2,h-1,w-1)
        faces = []
        measured_faces=0;extended_faces=0
        # Only observed, adjacent triples. Do not bridge masked objects/windows.
        for dy, dx in ((0, 0),):
            for y in range(h-1):
                for x in range(w-1):
                    for side,coords in enumerate((((y,x),(y+1,x),(y,x+1)), ((y+1,x),(y+1,x+1),(y,x+1)))):
                        measured=observed_triangles[side,y,x] and all(mask[ij] for ij in coords)
                        extended=any(inferred[ij] for ij in coords) and all(mesh_mask[ij] for ij in coords)
                        if measured or extended:
                            observed = np.array([projected[ij] for ij in coords])
                            # Adjacent image pixels across a depth discontinuity
                            # must not become a long bridging triangle.
                            if np.max(np.linalg.norm(observed-observed[[1,2,0]], axis=1)) <= span*.04:
                                faces.append([iy*w+ix for iy,ix in coords])
                                if measured:measured_faces+=1
                                else:extended_faces+=1
        if len(faces) < 80:
            continue
        mesh = trimesh.Trimesh(vertices=projected.reshape(-1,3), faces=faces, process=False)
        mesh.remove_unreferenced_vertices()
        # Winding faces the observing camera; viewer uses a cutaway toggle too.
        flip = mesh.face_normals @ normal < 0
        mesh.faces[flip] = mesh.faces[flip, ::-1]
        mesh.visual.vertex_colors = {'floor':[156,166,177,255], 'wall':[193,202,212,255],
                                    'ceiling':[212,216,222,255], 'observed':[173,182,191,255]}[kind]
        patches.append((mesh, dict(kind=kind, normal=normal.tolist(), point=center.tolist(),
            plane_fit=fit_evidence,
            occlusion_evidence=extension_evidence,
            observed_pixels=int(mask.sum()), residual_p95=float(np.quantile(residual[mask], .95)),
            tolerance=tolerance, evidence='unmasked_shared_pointmap',
            normal_agreement_minimum=float(np.cos(np.deg2rad(15))),
            median_normal_agreement=median_agreement,
            largest_connected_fraction=connected_fraction, classification=classification,
            inferred_pixels=int(inferred.sum()),
            fully_observed_triangles=measured_faces,occlusion_extended_triangles=extended_faces,
            triangle_support='all_original_pixels_in_triangle_or_bounded_occlusion_extension',
            completion='bounded_foreground_occlusion_extension' if inferred.any() else 'observed_patches_only',
            confidence=dict(kind='evidence_not_probability', observed_fraction=float(mask.sum()/valid.sum()),
                            normalized_residual=float(np.quantile(residual[mask], .95)/tolerance)),
            bounds=mesh.bounds.tolist())))
    return patches, dict(valid_points=int(valid.sum()), normal_supported_points=int((valid & reliable_normals).sum()),
        rejected_planes=rejected_planes, tolerance=tolerance, seed=42 if proposal_method=='random_triples' else None,
        proposal_method=proposal_method,
        occlusion_method=occlusion_method,
        plane_search_budget=max_planes, plane_search_attempts=attempts,
        limitation='Monocular estimated scale; observed patches only; no hidden room completion; orientation evidence recorded in placement')


def observed_grid_triangles(support, step):
    """Certify every original pixel inside each sampled right triangle.

    Both triangles include their diagonal. Pixels outside a triangle do not
    invalidate it; a hole anywhere inside it does, even between grid vertices.
    """
    support=np.asarray(support,bool)
    if support.ndim!=2 or not isinstance(step,int) or step<1:
        raise ValueError('Expected a 2D support mask and positive integer step')
    rows=(support.shape[0]-1)//step;cols=(support.shape[1]-1)//step
    first=np.ones((rows,cols),bool);second=first.copy()
    for dy in range(step+1):
        for dx in range(step+1):
            sample=support[dy:dy+rows*step:step,dx:dx+cols*step:step]
            if dy+dx<=step:first &= sample
            if dy+dx>=step:second &= sample
    return np.concatenate([first.ravel(),second.ravel()])


def observed_context_mesh(points, mask, rgb, common, planes, *, plane_faces=None):
    """Triangulate measured neighbors only, excluding already exported planes."""
    step = max(1, int(np.ceil(max(mask.shape)/256)))
    valid=np.isfinite(points).all(-1)&(np.linalg.norm(points,axis=-1)>1e-6)
    safe=np.asarray(mask,bool)&valid
    observed_faces=observed_grid_triangles(safe,step)
    p, selected = points[::step, ::step], safe[::step, ::step].copy()
    world = trimesh.transform_points(p.reshape(-1, 3), common).reshape(p.shape)
    selected &= np.isfinite(world).all(-1) & (np.linalg.norm(p, axis=-1) > 1e-6)
    if plane_faces is not None and len(plane_faces)!=len(planes):
        raise ValueError('Expected finite triangles for every exported plane')
    for plane_index,plane in enumerate(planes):
        # A plane can have disconnected observed patches. Remove only points
        # inside its finite exported bounds, never its infinite extension.
        near = abs((world - plane['point']) @ plane['normal']) <= plane['tolerance']
        bounds = np.asarray(plane['bounds'])
        near &= np.all((world >= bounds[0] - plane['tolerance']) &
                       (world <= bounds[1] + plane['tolerance']), axis=-1)
        if plane_faces is not None:
            faces=np.asarray(plane_faces[plane_index])
            finite_mesh=trimesh.Trimesh(faces.reshape(-1,3),np.arange(len(faces)*3).reshape(-1,3),process=False)
            candidate=near&selected
            if candidate.any():
                from .scene_proximity import closest_points
                _,distance,_=closest_points(finite_mesh,world[candidate])
                near[:]=False
                near[candidate]=distance<=plane['tolerance']
        selected &= ~near
    h, w = selected.shape
    indices = np.arange(h*w).reshape(h, w)
    faces = np.concatenate([np.stack([indices[:-1, :-1], indices[1:, :-1], indices[:-1, 1:]], -1).reshape(-1, 3),
                            np.stack([indices[1:, :-1], indices[1:, 1:], indices[:-1, 1:]], -1).reshape(-1, 3)])
    faces = faces[selected.reshape(-1)[faces].all(-1)&observed_faces]
    if not len(faces):
        return None
    triangles = world.reshape(-1, 3)[faces]
    edge = np.linalg.norm(triangles - triangles[:, [1, 2, 0]], axis=-1)
    # Bound bridges across depth edges relative to measured neighbor spacing.
    tolerance = max(float(np.median(edge)) * 4, 1e-8)
    faces = faces[edge.max(-1) <= tolerance]
    if step>1 and len(faces):
        # Also see depth jumps hidden between retained grid sites.
        jumps=np.zeros(mask.shape,float)
        jumps[:-1,:]=np.maximum(jumps[:-1,:],np.linalg.norm(points[1:]-points[:-1],axis=-1))
        jumps[:,:-1]=np.maximum(jumps[:,:-1],np.linalg.norm(points[:,1:]-points[:,:-1],axis=-1))
        jumps=np.where(np.isfinite(jumps),jumps,np.inf)
        local=maximum_filter(jumps,size=2*step+1,mode='nearest')[::step,::step]
        faces=faces[(local.reshape(-1)[faces]<=tolerance).all(-1)]
    if len(faces) < 80:
        return None
    mesh = trimesh.Trimesh(vertices=world.reshape(-1, 3), faces=faces, process=False)
    mesh.visual.vertex_colors = rgb[::step, ::step].reshape(-1, 3)
    mesh.remove_unreferenced_vertices()
    return mesh


def restore_structure(run, scene, meta, placement, *, include_unclaimed=True,
                      proposal_method='random_triples',occlusion_method='four_sided'):
    from .scene_run import sha
    info = meta.get('pointmap', {})
    if not info:
        return dict(status='unavailable', reason='No shared pointmap in this saved run', surfaces=[])
    path = Path(run)/info['asset']
    if info.get('frame') != 'sam3d_pytorch3d_camera' or sha(path) != info['sha256']:
        raise ValueError('Pointmap frame or hash mismatch')
    with np.load(path, allow_pickle=False) as archive:
        points = archive['points']
    h, w = points.shape[:2]
    exclusion = np.zeros((h,w), bool)
    reference_exclusion=np.zeros((h,w),bool) if proposal_method=='reference_stable_normals' else None
    for obj in meta['objects']:
        if obj.get('mask') and obj.get('status') not in ('structural', 'duplicate'):
            mask = Image.open(Path(run)/obj['mask']).convert('L').resize((w,h), Image.Resampling.NEAREST)
            exclusion |= np.asarray(mask) > 0
            if reference_exclusion is not None:
                provenance=obj.get('mask_expansion',{})
                name=provenance.get('original_mask',obj['mask'])
                expected=provenance.get('original_sha256',obj.get('mask_sha256'))
                reference_path=(Path(run)/name).resolve()
                if Path(run).resolve() not in reference_path.parents or not expected or sha(reference_path)!=expected:
                    raise ValueError('Reference mask provenance mismatch')
                reference_mask=Image.open(reference_path).convert('L').resize((w,h),Image.Resampling.NEAREST)
                reference_exclusion |= np.asarray(reference_mask)>0
    # Pad the exclusion boundary by one sample to avoid mixed object pixels.
    padded = np.pad(exclusion, 1)
    exclusion = np.logical_or.reduce([padded[y:y+h,x:x+w] for y in range(3) for x in range(3)])
    if reference_exclusion is not None:
        padded=np.pad(reference_exclusion,1)
        reference_exclusion=np.logical_or.reduce([padded[y:y+h,x:x+w] for y in range(3) for x in range(3)])
    if placement.get('orientation_evidence', {}).get('accepted'):
        guarded=occlusion_method=='guarded_enclosed_plane_evidence'
        patches, diagnostics = fit_surfaces(points, exclusion, placement['common_transform'],
            proposal_method=proposal_method,occlusion_method='local_plane_evidence' if guarded else occlusion_method,reference_excluded=reference_exclusion)
        if guarded:
            from .scene_geometry import triangles
            from .scene_extension_guard import guard_plane_extension
            candidates,_=fit_surfaces(points,exclusion,placement['common_transform'],
                proposal_method=proposal_method,occlusion_method='enclosed_plane_evidence',reference_excluded=reference_exclusion)
            if len(patches)!=len(candidates):
                raise ValueError('Guarded extension changed baseline plane count')
            obstacles=[]
            for obj in meta['objects']:
                if obj.get('status')!='generated':continue
                faces=triangles(scene,obj['id'])
                if not len(faces):raise ValueError('Generated object missing from extension guard scene')
                obstacles.append(faces)
            guarded_patches=[]
            for (baseline,old),(candidate,record) in zip(patches,candidates):
                if old['kind']!=record['kind'] or not np.array_equal(old['normal'],record['normal']) or not np.array_equal(old['point'],record['point']):
                    raise ValueError('Guarded extension changed baseline plane fit')
                mesh,evidence=guard_plane_extension(baseline,candidate,obstacles,record['normal'],record['point'],
                    placement['contact_tolerance'],localize_conflicts=True)
                extended=len(mesh.faces)-old['fully_observed_triangles']
                guarded_patches.append((mesh,dict(record,extension_guard=evidence,
                    proposed_inferred_pixels=record['inferred_pixels'],inferred_pixels=None,
                    inferred_pixel_count_scope='not_recounted_after_triangle_conflict_filter',
                    occlusion_extended_triangles=extended,bounds=mesh.bounds.tolist(),
                    completion='guarded_foreground_occlusion_extension' if extended else 'observed_patches_only')))
            patches=guarded_patches
            diagnostics.update(occlusion_method=occlusion_method,
                extension_guard='finite_generated_body_boundary_and_closed_volume',
                limitation='Observed planes and guarded interior occlusion interpolation; unknown boundaries remain absent')
    else:
        patches, diagnostics = [], dict(reason='room_orientation_not_corroborated',
            limitation='Observed context may be retained; floor/wall/ceiling classification withheld')
    surfaces = []
    for index, (mesh, record) in enumerate(patches):
        node = f'structure_{index:02d}'
        scene.add_geometry(mesh, node_name=node, geom_name=node, parent_node_name=scene.graph.base_frame)
        surfaces.append(dict(node=node, **record))
    context = np.zeros((h, w), bool)
    for obj in meta['objects']:
        if obj.get('structural_evidence', {}).get('observed_context'):
            context |= np.asarray(Image.open(Path(run)/obj['mask']).convert('L').resize((w,h), Image.Resampling.NEAREST)) > 0
    if include_unclaimed:
        context |= np.isfinite(points).all(-1)&(np.linalg.norm(points,axis=-1)>1e-6)&~exclusion
    if context.any() and meta.get('input_image'):
        rgb = np.asarray(Image.open(Path(run)/meta['input_image']).convert('RGB').resize((w,h)))
        from .scene_geometry import triangles
        mesh = observed_context_mesh(points, context & ~exclusion, rgb, placement['common_transform'], surfaces,
            plane_faces=[triangles(scene,s['node']) for s in surfaces])
        if mesh is not None:
            node = 'structure_observed_context'
            scene.add_geometry(mesh, node_name=node, geom_name=node, parent_node_name=scene.graph.base_frame)
            surfaces.append(dict(node=node, kind='observed', bounds=mesh.bounds.tolist(),
                evidence='valid_unclaimed_shared_pointmap_neighbors' if include_unclaimed else 'shared_pointmap_neighbors_without_instance_silhouette',
                completion='observed_patches_only', confidence=dict(kind='unclassified_observed_surface'),
                unclaimed_background_included=include_unclaimed,
                candidate_pixels=int(np.count_nonzero(context & ~exclusion)),
                exported_vertices=len(mesh.vertices),exported_faces=len(mesh.faces),
                triangle_support='all_original_pixels_in_triangle_observed_and_unmasked',
                limitation='May include undetected objects; no room semantics or hidden completion; not an unverified support plane'))
    return dict(status='estimated' if surfaces else 'insufficient_evidence', surfaces=surfaces,
                source_sha256=info['sha256'], **diagnostics)
