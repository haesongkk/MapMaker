from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_image(source: Path, target: Path, max_side: int = 1536) -> dict:
    image = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
    original = image.size
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    return {"source": str(source.resolve()), "source_mtime_ns": source.stat().st_mtime_ns,
            "original_size": original, "size": image.size,
            "scale_x": image.width / original[0], "scale_y": image.height / original[1]}


def camera_matrix(intrinsics: np.ndarray, width: int, height: int) -> np.ndarray:
    k = np.asarray(intrinsics, dtype=np.float64).copy()
    # MoGe returns normalized focal length and principal point.
    k[0, :] *= width
    k[1, :] *= height
    return k


def image_to_points(depth: np.ndarray, k: np.ndarray) -> np.ndarray:
    h, w = depth.shape
    v, u = np.mgrid[:h, :w]
    safe_depth = np.where(np.isfinite(depth) & (depth > 0), depth, np.nan)
    return np.stack(((u - k[0, 2]) * safe_depth / k[0, 0],
                     (v - k[1, 2]) * safe_depth / k[1, 1], safe_depth), axis=-1)
