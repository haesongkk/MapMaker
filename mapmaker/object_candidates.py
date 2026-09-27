"""Reuse the existing RAM tag filters; no image-specific inventories."""

import re

STOP_WORDS = {
    "room",
    "home",
    "indoor",
    "outdoor",
    "floor",
    "wall",
    "ceiling",
    "sky",
    "gray",
    "green",
    "brown",
    "white",
    "black",
    "red",
    "blue",
    "wood",
    "metal",
    "sitting",
    "standing",
    "lay",
    "photo",
    "picture",
    "image",
    "apartment",
    "living room",
    "furniture",
    "modern",
    "slide",
    "glass door",
    "carpet",
    "window",
    "flat",
}
SYNONYMS = {"sofa": "couch", "settee": "couch", "seat": "chair", "desk": "table"}


# General exclusions for an object-only scene, independent of the input image.
BACKGROUND_WORDS = {
    "wall",
    "walls",
    "floor",
    "flooring",
    "ceiling",
    "sky",
    "ground",
    "terrain",
    "background",
    "room",
    "landscape",
    "architecture",
    "window",
    "curtain",
}
EXCLUDED = {
    "balcony",
    "porch",
    "patio",
    "door",
    "stairs",
    "staircase",
    "lead to",
    "drawer",
    "tray",
    "interior",
    "interior design",
    "decoration",
    "decor",
    "wooden",
    "hardwood",
    "tile",
    "tiled",
    "pattern",
    "light",
    "lighting",
    "sunlight",
    "shadow",
    "reflection",
    "pillow",
    "cushion",
    "blanket",
    "napkin",
    "tableware",
}
ALIASES = {
    **SYNONYMS,
    "cocktail table": "coffee table",
    "dinning table": "dining table",
    "glass table": "table",
    "tv": "television",
    "television set": "television",
}

# RAM also predicts actions, appearance, scene types, and object parts.
NON_OBJECT_TAGS = set(
    "area attach balustrade beam beige blind bright build cabinetry clean comfort contain corner dark deck decorate den design doorway face fill hang hardwood headboard lead level make mat material mountain open out pad panorama peak plain rail relax residence sea shine side sit space sun sunny sunshine tan terrace velvet wide yellow".split()
)
NON_OBJECT_TAGS.update(
    {
        "city view",
        "living space",
        "home appliance",
        "table top",
        "window sill",
        "window screen",
        "window frame",
        "door frame",
        "screen door",
        "coffee",
        "entertainment center",
    }
)


# General RAM action/part/material tags are not independent reconstruction targets.
NON_OBJECT_TAGS.update(
    "appear bit bite break catch couple cut dip display eat half line miss place remove take tear treat type wrap peel stem topping frosting icing crumb backdrop surface".split()
)
EXCLUDED.update(
    {
        "cloth",
        "tablecloth",
        "paper",
        "paper towel",
        "paper plate",
        "wrapping paper",
        "tissue",
        "toilet paper",
        "sheet",
        "foil",
        "plastic",
        "wax",
        "strip",
        "cardboard",
        "close-up",
        "counter top",
        "food",
        "juice",
        "apple juice",
    }
)


def candidates(tags):
    accepted = set()
    rejected = []
    for raw in tags:
        tag = re.sub(r"\s+", " ", str(raw).strip().lower())
        name = ALIASES.get(tag, tag)
        if (
            tag
            in {
                "bedroom",
                "bathroom",
                "washroom",
                "restroom",
                "classroom",
                "playroom",
                "showroom",
                "storeroom",
                "boardroom",
            }
            or tag in STOP_WORDS
            or tag in EXCLUDED
            or tag in NON_OBJECT_TAGS
            or (tag.split() and tag.split()[-1] in BACKGROUND_WORDS)
            or len(name) < 3
        ):
            rejected.append(
                {"tag": raw, "reason": "background, appearance, or minor furnishing"}
            )
        else:
            accepted.add(name)
    return sorted(accepted), rejected
