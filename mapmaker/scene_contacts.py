"""Name-independent conservative contact inference."""
import numpy as np
from .scene_geometry import triangles, surface_height, sampled_penetration, wall_contact, support_translation, HorizontalSurface


def improve_contacts(scene, objects, placement, structure=None, source_guard=None):
    from .scene_placement import object_vertices, bounds_of, update_transform
    ordered = sorted(objects, key=lambda o: (bounds_of(object_vertices(scene, o['id']))[0,1],
        *bounds_of(object_vertices(scene, o['id'])).flatten()))
    current_bounds = {o['id']: bounds_of(object_vertices(scene, o['id'])) for o in ordered}
    bounds = lambda o: current_bounds[o['id']]
    initial = {oid: value.copy() for oid, value in current_bounds.items()}
    changes = []
    rejections = []
    mesh_indices = {}
    collision_queries = []
    support_body_checks = []
    source_checks = []

    def source_allows(obj, delta, candidate, stage):
        if source_guard is None:
            return True
        evidence=source_guard(obj,delta)
        source_checks.append(dict(object_id=obj['id'],candidate_id=candidate,**evidence))
        if not evidence['accepted']:
            reject(obj,candidate,stage,evidence['reason'])
            return False
        return True

    def reject(obj, candidate, stage, reason, **evidence):
        rejections.append(dict(object_id=obj['id'], candidate_id=candidate,
                               stage=stage, reason=reason, **evidence))

    def move(obj, delta, reason, **details):
        matrix = np.array(scene.graph[obj['id']][0], copy=True)
        matrix[:3, 3] += delta
        scene.graph.update(frame_from=scene.graph.base_frame, frame_to=obj['id'], matrix=matrix)
        update_transform(obj, matrix)
        current_bounds[obj['id']] = current_bounds[obj['id']] + delta
        mesh_indices.pop(obj['id'], None)
        b = bounds(obj)
        obj['placement'].update(world_bounds_after=b.tolist(), world_center=b.mean(axis=0).tolist(),
            world_bottom_center=[float(b[:, 0].mean()), float(b[0, 1]), float(b[:, 2].mean())])
        record = dict(object_id=obj['id'], reason=reason, translation=np.asarray(delta).tolist(), **details)
        obj['placement'].setdefault('contacts', []).append(record)
        changes.append(record)

    # No displacement based solely on AABB overlap. It may be a valid interlock.
    supports = list(ordered)
    room_surfaces = list((structure or {}).get('surfaces', []))
    structural = [s for s in room_surfaces if s['kind'] in ('floor', 'wall', 'ceiling')]
    # An observed patch can contain a real shelf even when room-plane
    # classification abstains. Query its finite triangles, never an invented
    # horizontal plane or the enclosing bounds. Preserve body collision checks.
    observed_supports = [s for s in room_surfaces if s['kind'] == 'observed'
        and s.get('evidence') == 'valid_unclaimed_shared_pointmap_neighbors'
        and s.get('triangle_support') == 'all_original_pixels_in_triangle_observed_and_unmasked']
    body_support_ids = {o['id'] for o in supports} | {s['node'] for s in observed_supports}
    support_faces = {o['id']: triangles(scene, o['id']) for o in supports}
    for surface in room_surfaces:
        support_faces[surface['node']] = triangles(scene, surface['node'])

    def blocked_by_third(obj, delta, ignored):
        swept = bounds(obj) + np.stack([np.minimum(delta, 0), np.maximum(delta, 0)])
        for third in ordered:
            if third['id'] in ignored:
                continue
            if not np.all(np.minimum(swept[1], bounds(third)[1]) -
                          np.maximum(swept[0], bounds(third)[0]) > 1e-5):
                continue
            try:
                from .scene_collision import MeshIndex
                if third['id'] not in mesh_indices:
                    mesh_indices[third['id']] = MeshIndex(support_faces[third['id']])
                measured_surface = third.get('geometry_source') == 'observed_mask_residual'
                collision = mesh_indices[third['id']].swept_collision(support_faces[obj['id']], delta,
                    check_containment=not measured_surface)
            except ImportError:
                collision = None
            collision_queries.append(dict(object_id=obj['id'], other_id=third['id'],
                result='unknown' if collision is None else 'intersection' if collision else 'clear',
                method='finite_triangle_sweep_and_explicit_surface_or_solid_representation'))
            if collision is not False:
                return 'third_object_collision_unknown' if collision is None else 'third_object_mesh_collision'
        return None

    def blocked_by_room(obj, vertices, delta, ignored=None):
        swept = bounds(obj) + np.stack([np.minimum(delta, 0), np.maximum(delta, 0)])
        for surface in room_surfaces:
            sid = surface['node']
            if sid == ignored:
                continue
            faces = support_faces[sid]
            if np.any(swept[1] < faces.min((0, 1))) or np.any(swept[0] > faces.max((0, 1))):
                continue
            if surface['kind'] in ('floor', 'wall', 'ceiling'):
                n, p = np.asarray(surface['normal']), np.asarray(surface['point'])
                before, after = (vertices-p)@n, (vertices+delta-p)@n
                if after.min() >= min(before.min(), 0.)-placement['contact_tolerance']:
                    continue
            try:
                from .scene_collision import MeshIndex
                if sid not in mesh_indices:
                    mesh_indices[sid] = MeshIndex(support_faces[sid])
                hit = mesh_indices[sid].swept_collision(support_faces[obj['id']], delta, check_containment=False)
            except ImportError:
                hit = None
            collision_queries.append(dict(object_id=obj['id'], other_id=sid,
                result='unknown' if hit is None else 'intersection' if hit else 'clear',
                method='finite_room_triangle_sweep'))
            if hit is not False:
                return True
        return False
    # Resolve only shallow, confirmed intersections of peers at the same base
    # height. Stacked objects are handled by support inference, not separation.
    used = {o['id']: 0. for o in ordered}
    for i, a in enumerate(ordered):
        for b in ordered[i+1:]:
            ba, bb = bounds(a), bounds(b)
            depth = np.minimum(ba[1],bb[1])-np.maximum(ba[0],bb[0])
            if np.any(depth <= placement['contact_tolerance']) or abs(ba[0,1]-bb[0,1]) > placement['contact_tolerance']:
                continue
            target, other = sorted((a,b),key=lambda o:(float(np.prod(bounds(o)[1]-bounds(o)[0])),*bounds(o).flatten()))
            bt,bo = bounds(target),bounds(other)
            axis = min((0,2),key=lambda k:depth[k])
            sign = 1 if bt[:,axis].mean() >= bo[:,axis].mean() else -1
            distance = (bo[1,axis]-bt[0,axis] if sign>0 else bt[1,axis]-bo[0,axis])+1e-6
            budget = .08*min((initial[target['id']][1]-initial[target['id']][0])[[0,2]])
            if distance > budget-used[target['id']]:
                reject(target, other['id'], 'separation', 'movement_budget_exceeded', requested=float(distance), remaining=float(budget-used[target['id']]))
                continue
            confirmed = sampled_penetration(support_faces[target['id']],support_faces[other['id']],placement['contact_tolerance'])
            unknown = confirmed is None
            if not confirmed:
                confirmed = sampled_penetration(support_faces[other['id']],support_faces[target['id']],placement['contact_tolerance'])
            if not confirmed:
                reject(target, other['id'], 'separation', 'penetration_unknown' if unknown or confirmed is None else 'no_inside_samples')
                continue
            delta=np.zeros(3);delta[axis]=sign*distance
            blocker = blocked_by_third(target, delta, (target['id'], other['id']))
            if blocker:
                reject(target, other['id'], 'separation', blocker)
                continue
            vertices=object_vertices(scene,target['id'])
            if blocked_by_room(target, vertices, delta):
                reject(target, other['id'], 'separation', 'room_plane_crossing')
                continue
            if not source_allows(target,delta,other['id'],'separation'):
                continue
            move(target,delta,'bounded_mesh_penetration',other_id=other['id'])
            used[target['id']]+=distance
            support_faces[target['id']]=triangles(scene,target['id'])
    surface_queries = {key: HorizontalSurface(faces) for key, faces in support_faces.items()}
    relations = []
    unresolved = []
    for prop in ordered:
        pb = bounds(prop); center = pb.mean(axis=0)
        candidates = []
        vertices = object_vertices(scene, prop['id'])
        extent = pb[1]-pb[0]
        bottom = vertices[vertices[:, 1] <= pb[0, 1] + max(extent[1]*.1, 1e-6)]
        foot_bounds = bounds_of(bottom)
        footprint = foot_bounds[1, [0, 2]]-foot_bounds[0, [0, 2]]
        foot_center = foot_bounds.mean(axis=0)[[0, 2]]
        for support in supports + [{'id': s['node'], 'surface': s}
                for s in [s for s in structural if s['kind'] == 'floor'] + observed_supports]:
            if support['id'] == prop['id']:
                continue
            sb = np.asarray(support['surface']['bounds']) if 'surface' in support else bounds(support)
            size = sb[1]-sb[0]
            # A tall enclosure can contain a low shelf. Its bounds center is
            # not the height of the contacted surface; query the triangles.
            if sb[0, 1] >= center[1]:
                reject(prop, support['id'], 'support', 'support_entirely_above_center')
                continue
            limit = min(.2 * max(float(np.min(size[[0, 2]])), float(extent[1]), 1e-6),
                        .8 * max(float(np.max(extent)), 1e-6))
            delta, evidence = support_translation(vertices, support_faces[support['id']],
                limit, max(placement['contact_tolerance'], float(extent[1])*.02), surface=surface_queries[support['id']])
            if delta is None:
                reason = evidence.pop('reason')
                reject(prop, support['id'], 'support', reason, **evidence)
                continue
            if center[1] <= pb[0, 1]+delta[1]:
                reject(prop, support['id'], 'support', 'center_below_support')
                continue
            candidates.append((abs(float(delta[1])), support['id'], delta, 'horizontal_contact'))
        for surface in structural:
            if surface['kind'] not in ('wall','ceiling'):
                continue
            delta = wall_contact(vertices, support_faces[surface['node']], surface['normal'], surface['point'])
            if delta is not None:
                candidates.append((float(np.linalg.norm(delta)), surface['node'], delta, surface['kind']+'_contact'))
            else:
                reject(prop, surface['node'], surface['kind'], surface['kind']+'_contact_evidence_insufficient')
        candidates.sort(key=lambda c: c[0])
        ambiguity = max(float(np.max(extent))*.05, 1e-6)
        if not candidates or (len(candidates)>1 and candidates[1][0]-candidates[0][0] < ambiguity):
            reject(prop, None, 'selection', 'no_supported_candidate' if not candidates else 'ambiguous_candidates')
            unresolved.append(prop['id'])
            continue
        _, sid, delta, relation = candidates[0]
        # Foot contact alone cannot certify that the body clears an enclosure's
        # other shelves. Reject newly introduced measured body penetration.
        if sid in body_support_ids and np.linalg.norm(delta) > 1e-9:
            try:
                from .scene_collision import MeshIndex
                if sid not in mesh_indices:
                    mesh_indices[sid] = MeshIndex(support_faces[sid])
                before_inside = mesh_indices[sid].penetration_samples(support_faces[prop['id']], placement['contact_tolerance'])
                after_inside = mesh_indices[sid].penetration_samples(support_faces[prop['id']] + delta, placement['contact_tolerance'])
                support_body_checks.append(dict(object_id=prop['id'],support_id=sid,
                    before_inside=before_inside,after_inside=after_inside,
                    status='sampled_closed_volume' if before_inside is not None and after_inside is not None else 'open_or_unknown_volume'))
                if after_inside is not None and before_inside is not None and after_inside > before_inside:
                    reject(prop, sid, 'support', 'increased_support_body_penetration', before=before_inside, after=after_inside)
                    unresolved.append(prop['id'])
                    continue
            except ImportError:
                support_body_checks.append(dict(object_id=prop['id'],support_id=sid,status='spatial_dependency_unavailable'))
                pass
            # Open support meshes have no reliable inside/outside volume. Their
            # upper shelves and side walls can still intersect the moving body.
            # Geometry wholly below the final lowest point is the intended
            # support/penetration-repair region; test every remaining triangle.
            final_bottom=float(pb[0,1]+delta[1])
            support_mesh=support_faces[sid]
            boundary_epsilon=max(float(np.linalg.norm(pb[1]-pb[0]))*1e-9,1e-12)
            obstacles=support_mesh[support_mesh[:,:,1].max(axis=1)>
                final_bottom+boundary_epsilon]
            hit=False
            if len(obstacles):
                try:
                    from .scene_collision import MeshIndex
                    hit=MeshIndex(obstacles).swept_collision(support_faces[prop['id']],delta,
                                                           check_containment=False)
                except ImportError:
                    hit=None
            support_body_checks.append(dict(object_id=prop['id'],support_id=sid,
                status='finite_support_body_sweep',obstacle_triangles=len(obstacles),
                result='unknown' if hit is None else 'intersection' if hit else 'clear'))
            if hit is True and delta[1] < 0:
                # Sparse footprint queries can overshoot a rough mesh surface.
                # Find its first actual foot contact without weakening collision
                # tests or moving farther than the original contact tolerance.
                refined, evidence = mesh_indices[sid].first_foot_contact(
                    support_faces[prop['id']], delta, placement['contact_tolerance'])
                support_body_checks.append(dict(object_id=prop['id'],support_id=sid,
                    status='finite_contact_refinement', **evidence))
                if refined is not None:
                    delta = refined
                    hit = False  # Full support mesh sweep certified this prefix.
            if hit is not False:
                reject(prop,sid,'support','support_body_collision_unknown' if hit is None else 'support_body_mesh_collision')
                unresolved.append(prop['id'])
                continue
        blocker = blocked_by_third(prop, delta, (prop['id'], sid))
        if blocker:
            reject(prop, sid, 'support', blocker)
            unresolved.append(prop['id'])
            continue
        # Do not cross another room plane while snapping to the chosen surface.
        if blocked_by_room(prop, vertices, delta, ignored=sid):
            reject(prop, sid, 'support', 'room_plane_crossing')
            unresolved.append(prop['id'])
            continue
        if not source_allows(prop,delta,sid,'support'):
            unresolved.append(prop['id'])
            continue
        move(prop, delta, 'supported_on_surface', support_id=sid)
        support_faces[prop['id']] = triangles(scene, prop['id'])
        surface_queries[prop['id']] = HorizontalSurface(support_faces[prop['id']])
        relations.append(dict(object_id=prop['id'], support_id=sid, type=relation))
    overlaps = []
    for i, a in enumerate(ordered):
        for b in ordered[i+1:]:
            ba, bb = bounds(a), bounds(b)
            depth = np.minimum(ba[1], bb[1])-np.maximum(ba[0], bb[0])
            if np.all(depth > 1e-5):
                overlaps.append({'objects': [a['id'], b['id']], 'aabb_depth': depth.tolist(),
                    'sampled_inside_counts': [sampled_penetration(support_faces[a['id']], support_faces[b['id']], placement['contact_tolerance']),
                                              sampled_penetration(support_faces[b['id']], support_faces[a['id']], placement['contact_tolerance'])]})
    placement['contacts'] = {'method': 'label_free_mesh_surface_support',
        'source_guard_enabled': source_guard is not None, 'source_checks': source_checks,
        'collision_queries': collision_queries,
        'support_body_checks': support_body_checks,
        'rejections': rejections,
        'rejection_counts': {reason: sum(r['reason'] == reason for r in rejections) for reason in sorted({r['reason'] for r in rejections})},
        'uses_object_names': False, 'relations': relations, 'changes': changes, 'unresolved_props': unresolved, 'remaining_aabb_overlaps': overlaps,
        'limitation': 'Positive winding samples indicate penetration in closed meshes; zero/unknown does not prove clear. Ambiguous contacts unchanged. No AABB-only separation.'}
    placement['minimum_y_after'] = min(bounds(o)[0, 1] for o in ordered)
    offsets = np.array([bounds(o)[0, 1] for o in ordered])
    tolerance = placement['contact_tolerance']
    placement['metrics']['after'] = dict(object_count=len(ordered),
        floating_count=int(np.sum(offsets > tolerance)), penetrating_count=int(np.sum(offsets < -tolerance)),
        mean_absolute_contact_error=float(np.mean(abs(offsets))))
    return placement
