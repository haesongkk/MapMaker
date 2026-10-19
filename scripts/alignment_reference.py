"""Resolve the original alignment set, including subsequently excluded nodes."""


def alignment_objects(meta):
    generated = [o for o in meta['objects'] if o['status'] == 'generated']
    ids = meta['placement'].get('object_ids')
    if ids is None:
        return generated  # Older artifacts did not record the alignment set.
    objects = {o['id']: o for o in meta['objects']}
    if (not ids or len(objects) != len(meta['objects']) or len(set(ids)) != len(ids)
            or not set(ids).issubset(objects)
            or not {o['id'] for o in generated}.issubset(ids)):
        raise ValueError('Invalid original alignment object set')
    result = [objects[key] for key in ids]
    if any('original_matrix' not in o.get('placement', {}) for o in result):
        raise ValueError('Missing original alignment transform')
    return result
