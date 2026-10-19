"""Bounded multiscale detection views; independent of image content and labels."""


def analysis_boxes(width, height):
    if max(width, height) <= 768:
        return []
    boxes = []
    for size, positions in ((.6, [(0, 0), (.4, 0), (0, .4), (.4, .4), (.2, .2)]),
                            (.35, [(x, y) for y in (0., .325, .65) for x in (0., .325, .65)])):
        for x, y in positions:
            box = (round(x * width), round(y * height),
                   min(width, round((x + size) * width)),
                   min(height, round((y + size) * height)))
            if min(box[2] - box[0], box[3] - box[1]) >= 128 and box not in boxes:
                boxes.append(box)
    return boxes


def rank_candidates(prompts, tags_by_view, full_view, aliases, limit=None, local_slots=8):
    """Reserve proposal slots for localized detections, not a category allowlist.

    Labels are detector prompts only. Geometry selection and correction remain
    unchanged when identical masks/meshes have different display names.
    """
    normalized = {key: {aliases.get(tag, tag) for tag in tags} for key, tags in tags_by_view.items()}
    votes = {name: sum(name in tags for tags in normalized.values()) for name in prompts}
    ranked = sorted(prompts, key=lambda name: (-votes[name], name))
    local = [name for name in ranked if name not in normalized.get(full_view, set())]
    selected = local[:local_slots if limit is None else min(local_slots, limit)]
    selected.extend(name for name in ranked if name not in selected)
    if limit is None:
        return selected, votes, []
    return selected[:limit], votes, selected[limit:]
