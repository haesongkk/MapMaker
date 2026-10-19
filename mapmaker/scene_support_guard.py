"""Preserve initially measured foot contacts in both directions of a pose edit."""
import copy
import numpy as np
import trimesh

from .scene_geometry import support_translation


def _initial_contacts(faces, object_ids, floor_ids, moving_id, contact_tolerance):
    moving = faces[moving_id]
    contacts = []
    for other in list(object_ids)+list(floor_ids):
        if other == moving_id:
            continue
        fixed = faces[other]
        pairs = [(moving_id, other, moving, fixed)]
        if other in object_ids:
            pairs.append((other, moving_id, fixed, moving))
        for prop, support, before_prop, before_support in pairs:
            vertices = before_prop.reshape(-1, 3)
            lower, upper = vertices.min(0), vertices.max(0)
            support_lower, support_upper = before_support.min((0, 1)), before_support.max((0, 1))
            if (np.any(upper[[0, 2]] < support_lower[[0, 2]])
                    or np.any(lower[[0, 2]] > support_upper[[0, 2]])
                    or support_lower[1] >= (lower[1]+upper[1])/2):
                continue
            extent, size = upper-lower, support_upper-support_lower
            limit = min(.2*max(float(np.min(size[[0, 2]])), float(extent[1]), 1e-6),
                        .8*max(float(np.max(extent)), 1e-6))
            tolerance = max(contact_tolerance, float(extent[1])*.02)
            delta, initial = support_translation(vertices, before_support, limit, tolerance)
            if delta is None or abs(delta[1]) > tolerance:
                continue
            contacts.append((prop, support, limit, tolerance, delta, initial))
    return contacts


def support_preservation(faces, object_ids, floor_ids, moving_id, transform, contact_tolerance,
                         *, initial_cache=None):
    """Check both directions of initially measured support for this candidate.

    The optional cache belongs to one immutable scene state. Replace arrays (or
    discard the cache) whenever geometry changes; in-place mutation is forbidden
    while reusing it. Candidate final contacts are always recomputed.
    Empty checks do not prove the scene's true physical support relationships.
    """
    key = (moving_id, tuple(object_ids), tuple(floor_ids), contact_tolerance,
           tuple((name, id(faces[name])) for name in list(object_ids)+list(floor_ids)))
    if initial_cache is None or initial_cache.get('key') != key:
        contacts = _initial_contacts(faces, object_ids, floor_ids, moving_id, contact_tolerance)
        if initial_cache is not None:
            initial_cache.clear()
            # Retain arrays so an object ID cannot be reused while this cache lives.
            initial_cache.update(key=key, contacts=contacts, arrays=tuple(faces.values()))
    else:
        contacts = initial_cache['contacts']
    moving = faces[moving_id]
    end = trimesh.transform_points(moving.reshape(-1, 3), transform).reshape(-1, 3, 3)
    records = []
    for prop, support, limit, tolerance, delta, initial in contacts:
        after_prop = end if prop == moving_id else faces[prop]
        after_support = end if support == moving_id else faces[support]
        after, final = support_translation(after_prop.reshape(-1, 3), after_support, limit, tolerance)
        records.append(dict(object_id=prop, support_id=support,
            before_delta=delta.tolist(), after_delta=None if after is None else after.tolist(),
            before=copy.deepcopy(initial), after=final,
            preserved=bool(after is not None and abs(after[1]) <= tolerance)))
    return dict(accepted=all(r['preserved'] for r in records), checks=records,
                scope='initially_measured_geometric_support_proxy_not_true_mass_center')
