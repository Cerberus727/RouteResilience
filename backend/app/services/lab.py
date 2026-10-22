"""Segmentation lab: DeepGlobe samples + inference with compatible Phase I checkpoints.

* Phase I split reproduced exactly: ids with both `_sat.jpg` and `_mask.png` in
  `train/`, sorted, `random.seed(42)`, `random.shuffle`, first 80 % = training subset.
  Metrics on training-subset tiles are in-sample and labelled as such.
* Preprocessing mirrors Phase I `get_val_transforms`: bilinear resize to 512×512,
  ImageNet normalization; sigmoid > 0.5; nearest-neighbour resize back to the tile size.
* Only checkpoints whose architecture strict-loads are used (see services/checkpoints.py).
"""

from __future__ import annotations

import io
import random
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from ..config import get_settings
from ..registry import SAFE_ID, get_registry
from . import checkpoints

PHASE1_IMG_SIZE = 512
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class LabError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True)
class Sample:
    image_id: str
    folder: str  # train | valid | test
    sat: Path
    mask: Path | None
    phase1_subset: str | None  # "train" | "val" (Phase I split) or None for valid/test folders


@lru_cache(maxsize=2)
def _dataset(root_str: str, mtime: float) -> tuple[dict[str, Sample], dict]:
    root = Path(root_str)
    samples: dict[str, Sample] = {}
    train = root / "train"
    sat_ids = {p.name[:-8] for p in train.glob("*_sat.jpg")} if train.is_dir() else set()
    mask_ids = {p.name[:-9] for p in train.glob("*_mask.png")} if train.is_dir() else set()
    paired = sorted(sat_ids & mask_ids)
    shuffled = list(paired)
    random.seed(42)
    random.shuffle(shuffled)
    split = int(0.8 * len(shuffled))
    val_ids = shuffled[split:]
    subset = {i: "train" for i in shuffled[:split]} | {i: "val" for i in val_ids}
    for i in sat_ids:
        if SAFE_ID.match(i):
            samples[i] = Sample(i, "train", train / f"{i}_sat.jpg", train / f"{i}_mask.png" if i in mask_ids else None, subset.get(i))
    for folder in ("valid", "test"):
        d = root / folder
        if d.is_dir():
            for p in d.glob("*_sat.jpg"):
                i = p.name[:-8]
                if SAFE_ID.match(i) and i not in samples:
                    samples[i] = Sample(i, folder, p, None, None)
    # Cross-check the reproduction against the 44 masks Phase I actually wrote (val_ids[:40] + 4 demo tiles).
    saved = set(get_registry().mask_sets.get("deeplab", {}))
    expected = set(val_ids[:40]) | {"493626", "477671", "422265", "194764"}
    check = {"phase1_saved_masks": len(saved), "matches_val_ids_first40_plus_demo": bool(saved) and saved == expected}
    info = {"root": str(root), "paired_train": len(paired), "phase1_train": split, "phase1_val": len(val_ids),
            "valid_images": sum(1 for s in samples.values() if s.folder == "valid"),
            "test_images": sum(1 for s in samples.values() if s.folder == "test"), "split_check": check}
    return samples, info


def dataset() -> tuple[dict[str, Sample], dict]:
    root = get_settings().deepglobe_dir
    if root is None or not root.is_dir():
        raise LabError(404, "dataset_missing", f"DeepGlobe folder not found ({root}). Set ROUTERESILIENCE_DEEPGLOBE_DIR.")
    return _dataset(str(root), root.stat().st_mtime)


def get_sample(image_id: str) -> Sample:
    if not SAFE_ID.match(image_id):
        raise LabError(400, "invalid_id", "Invalid image id.")
    s = dataset()[0].get(image_id)
    if s is None:
        raise LabError(404, "sample_missing", f"No DeepGlobe image '{image_id}'.")
    return s


def list_samples(subset: str, offset: int, limit: int, q: str | None) -> dict:
    samples, info = dataset()
    saved = get_registry().mask_sets.get("deeplab", {})
    items = list(samples.values())
    if subset == "phase1_val":
        items = [s for s in items if s.phase1_subset == "val"]
    elif subset == "phase1_train":
        items = [s for s in items if s.phase1_subset == "train"]
    elif subset in ("valid", "test"):
        items = [s for s in items if s.folder == subset]
    elif subset == "phase1_saved":
        items = [s for s in items if s.image_id in saved]
    if q:
        items = [s for s in items if q in s.image_id]
    items.sort(key=lambda s: (s.image_id not in saved, len(s.image_id), s.image_id))
    page = items[offset: offset + limit]
    return {"total": len(items), "offset": offset, "limit": limit, "dataset": info, "items": [
        {"image_id": s.image_id, "folder": s.folder, "phase1_subset": s.phase1_subset, "has_ground_truth": s.mask is not None,
         "has_phase1_mask": s.image_id in saved} for s in page]}


def models() -> list[dict]:
    reg = get_registry()
    out = []
    for key, path in sorted(reg.checkpoints.items()):
        compat = checkpoints.compatibility(path)
        out.append({"model_id": key, "checkpoint": path.name, "loadable": compat["loadable"], "family": compat["family"],
                    "diagnostic": compat["diagnostic"]})
    return out


# ------------------------------------------------------------------- inference
_results: OrderedDict[str, dict] = OrderedDict()
_res_lock = threading.Lock()
_infer_lock = threading.Lock()


def _png(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _binary(path: Path, size: tuple[int, int]) -> np.ndarray:
    with Image.open(path) as im:
        a = np.asarray(im.convert("RGB"))[:, :, 0] > 127  # Phase I: red channel > 127
    if a.shape != (size[1], size[0]):
        a = np.asarray(Image.fromarray(a.astype(np.uint8) * 255).resize(size, Image.NEAREST)) > 127
    return a


def confusion(pred: np.ndarray, gt: np.ndarray) -> dict:
    tp = int((pred & gt).sum()); fp = int((pred & ~gt).sum()); fn = int((~pred & gt).sum()); tn = int((~pred & ~gt).sum())
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "iou": tp / (tp + fp + fn) if (tp + fp + fn) else None,
        "dice": 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else None,
        "precision": tp / (tp + fp) if (tp + fp) else None,
        "recall": tp / (tp + fn) if (tp + fn) else None,
    }


def infer(model_id: str, image_id: str) -> dict:
    sample = get_sample(image_id)
    path = get_registry().checkpoints.get(model_id) if SAFE_ID.match(model_id) else None
    if path is None:
        raise LabError(404, "model_missing", f"No checkpoint for model '{model_id}'.")
    compat = checkpoints.compatibility(path)
    if not compat["loadable"]:
        raise LabError(409, "checkpoint_incompatible", compat["diagnostic"] or "Checkpoint cannot be loaded.")
    import torch
    import torch.nn.functional as F

    model = checkpoints._get_model(path, compat["family"])
    try:
        with Image.open(sample.sat) as im:
            rgb = np.asarray(im.convert("RGB"))
    except OSError as exc:
        raise LabError(422, "image_unreadable", f"Cannot read {sample.sat.name}: {exc}") from exc
    h, w = rgb.shape[:2]
    t = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).float()
    t = F.interpolate(t, size=(PHASE1_IMG_SIZE, PHASE1_IMG_SIZE), mode="bilinear", align_corners=False)
    t = (t / 255.0 - torch.from_numpy(MEAN)[:, None, None]) / torch.from_numpy(STD)[:, None, None]
    with _infer_lock, torch.no_grad():
        t0 = time.perf_counter()
        logits = model(t)
        latency = (time.perf_counter() - t0) * 1000
    prob = torch.sigmoid(logits)[0, 0].numpy()
    pred512 = (prob > 0.5).astype(np.uint8) * 255
    pred = np.asarray(Image.fromarray(pred512).resize((w, h), Image.NEAREST)) > 127

    overlay = np.zeros((h, w, 4), dtype=np.uint8)
    overlay[pred] = (34, 211, 238, 255)
    images = {"mask": _png(pred.astype(np.uint8) * 255), "overlay": _png(overlay)}
    result: dict = {
        "model_id": model_id, "image_id": image_id, "folder": sample.folder, "phase1_subset": sample.phase1_subset,
        "size": [w, h], "input_size": PHASE1_IMG_SIZE, "threshold": 0.5, "latency_ms": latency, "device": "cpu",
        "road_fraction": float(pred.mean()), "mean_road_probability": float(prob[prob > 0.5].mean()) if (prob > 0.5).any() else None,
        "metrics": None, "phase1_agreement": None,
    }
    if sample.mask is not None:
        gt = _binary(sample.mask, (w, h))
        m = confusion(pred, gt)
        m["evaluation"] = ("held-out (Phase I validation subset)" if sample.phase1_subset == "val"
                           else "in-sample (tile was in the Phase I training subset — optimistic)")
        result["metrics"] = m
        err = np.zeros((h, w, 4), dtype=np.uint8)
        err[pred & gt] = (34, 197, 94, 255)
        err[pred & ~gt] = (239, 68, 68, 255)
        err[~pred & gt] = (245, 158, 11, 255)
        images["errors"] = _png(err)
        images["ground_truth"] = _png(gt.astype(np.uint8) * 255)
    saved = get_registry().mask_sets.get("deeplab", {}).get(image_id) if model_id == "deeplabv3" else None
    if saved is not None:
        a = confusion(pred, _binary(saved, (w, h)))
        result["phase1_agreement"] = {"iou_with_saved_mask": a["iou"], "pixels_differing": a["fp"] + a["fn"],
                                      "note": "Agreement between this inference and the mask written by the Phase I notebook (checks preprocessing fidelity)."}
    rid = secrets.token_hex(6)
    result["result_id"] = rid
    result["urls"] = {k: f"/api/lab/results/{rid}/{k}.png" for k in images}
    with _res_lock:
        _results[rid] = {"meta": result, "images": images}
        while len(_results) > 24:
            _results.popitem(last=False)
    return result


def result_image(rid: str, kind: str) -> bytes:
    with _res_lock:
        r = _results.get(rid)
    if r is None or kind not in r["images"]:
        raise LabError(404, "result_missing", "Inference result expired or not found; run inference again.")
    return r["images"][kind]
