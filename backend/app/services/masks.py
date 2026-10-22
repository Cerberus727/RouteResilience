"""Recomputed statistics for predicted road masks (binary PNGs)."""

from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError
from scipy import ndimage

_lock = threading.Lock()
EIGHT_CONNECTED = np.ones((3, 3), dtype=bool)  # matches cv2.connectedComponents default used in Phase I


class MaskReadError(Exception):
    pass


def _read_binary(path: Path) -> np.ndarray:
    try:
        with Image.open(path) as im:
            arr = np.asarray(im.convert("L"))
    except (OSError, UnidentifiedImageError) as exc:
        raise MaskReadError(f"Cannot read mask {path.name}: {exc}") from exc
    return arr > 127


@lru_cache(maxsize=256)
def _stats_cached(path_str: str, mtime_ns: int) -> dict:
    mask = _read_binary(Path(path_str))
    labels, n = ndimage.label(mask, structure=EIGHT_CONNECTED)
    road = int(mask.sum())
    largest = int(np.bincount(labels.ravel())[1:].max()) if n else 0
    return {
        "width": int(mask.shape[1]),
        "height": int(mask.shape[0]),
        "road_pixels": road,
        "road_fraction": road / mask.size,
        "components": int(n),
        "largest_component_fraction": (largest / road) if road else None,
    }


def mask_stats(path: Path) -> dict:
    with _lock:
        return dict(_stats_cached(str(path), path.stat().st_mtime_ns))


def mask_size(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as im:
            return im.size
    except (OSError, UnidentifiedImageError):
        return None


def compare_masks(before: Path, after: Path) -> dict:
    a, b = _read_binary(before), _read_binary(after)
    if a.shape != b.shape:
        raise MaskReadError(f"Mask sizes differ: {a.shape} vs {b.shape}")
    return {
        "pixels_added": int((b & ~a).sum()),
        "pixels_removed": int((a & ~b).sum()),
        "net_pixel_change": int(b.sum()) - int(a.sum()),
    }
