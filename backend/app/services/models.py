"""Model catalog: combines what the Phase I notebook documents with what exists on disk."""

from __future__ import annotations

from ..registry import Registry, get_registry
from . import notebooks

# Taken from the Phase I MODEL_CONFIGS table and the audit (checkpoint key layouts).
KNOWN_MODELS: dict[str, dict] = {
    "deeplabv3": {
        "label": "DeepLabV3+",
        "detail": "ResNet-34 encoder, ASPP rates (12, 24, 36), output stride 16, 512x512 input (Phase I config).",
        "mask_set": "deeplab",
        "figure_tag": "deeplabv3",
    },
    "denseddsspp": {
        "label": "DenseDSSPP",
        "detail": "Xception-style backbone, dense depthwise-separable ASPP, SE block, DeepLabV3+-style decoder "
                  "(inferred from checkpoint keys; no source code in the repository).",
        "mask_set": "denseddsspp",
        "figure_tag": "denseddsspp_deeplab",
    },
    "unext": {
        "label": "UNeXt",
        "detail": "Lightweight convolutional / tokenized-MLP U-Net (external UNeXt-pytorch repository).",
        "mask_set": "unext",
        "figure_tag": "unext",
    },
}
POSTPROCESS = {
    "sam_repaired": {
        "label": "SAM mask repair",
        "detail": "Post-processing of DeepLabV3+ masks with facebook/sam-vit-base point prompts + morphological closing (Phase I, optional cell).",
    }
}


class ModelNotFoundError(Exception):
    pass


def _mask_set_for(model_id: str, reg: Registry) -> str | None:
    spec = KNOWN_MODELS.get(model_id)
    if spec and spec["mask_set"] in reg.mask_sets:
        return spec["mask_set"]
    return model_id if model_id in reg.mask_sets else None


def list_model_ids(reg: Registry | None = None) -> list[str]:
    reg = reg or get_registry()
    ids: list[str] = []
    for mid, spec in KNOWN_MODELS.items():
        if mid in reg.checkpoints or spec["mask_set"] in reg.mask_sets:
            ids.append(mid)
    mapped_masks = {KNOWN_MODELS[m]["mask_set"] for m in ids if m in KNOWN_MODELS}
    for key in sorted(reg.checkpoints):
        if key not in ids:
            ids.append(key)
    for mset in sorted(reg.mask_sets):
        if mset not in mapped_masks and mset not in ids:
            ids.append(mset)
    return ids


def describe(model_id: str, reg: Registry | None = None) -> dict:
    reg = reg or get_registry()
    if model_id not in list_model_ids(reg):
        raise ModelNotFoundError(f"Unknown model '{model_id}'.")
    spec = KNOWN_MODELS.get(model_id) or POSTPROCESS.get(model_id)
    kind = "segmentation" if model_id in KNOWN_MODELS else ("postprocess" if model_id in POSTPROCESS else "unknown")
    if model_id in reg.checkpoints and kind == "unknown":
        kind = "segmentation"
    mask_set = _mask_set_for(model_id, reg)
    ckpt = reg.checkpoints.get(model_id)
    tag = (KNOWN_MODELS.get(model_id) or {}).get("figure_tag", model_id)
    pred_fig = f"predictions_{tag}" if f"predictions_{tag}" in reg.figures else None
    curve_fig = f"training_curves_{tag}" if f"training_curves_{tag}" in reg.figures else None
    p1 = notebooks.parsed("phase1") or {}
    has_history = bool(p1.get("training")) and p1.get("model_name") == model_id
    notes: list[str] = []
    if kind == "segmentation" and not curve_fig and not has_history:
        notes.append("No training curves were saved for this model.")
    if model_id == "deeplabv3" and not curve_fig and has_history:
        notes.append("training_curves_deeplabv3.png was never written (Phase I curves cell raised NameError); "
                     "the curves shown here are parsed from the training log instead.")
    if kind == "unknown":
        notes.append("Not described by the Phase I notebook; shown because matching artifacts exist.")
    return {
        "id": model_id,
        "label": (spec or {}).get("label", model_id),
        "kind": kind,
        "detail": (spec or {}).get("detail"),
        "checkpoint": {"file": ckpt.name, "size_bytes": ckpt.stat().st_size} if ckpt else None,
        "mask_set": mask_set,
        "mask_count": len(reg.mask_sets.get(mask_set, {})) if mask_set else 0,
        "figures": {"predictions": pred_fig, "training_curves": curve_fig},
        "has_training_history": has_history,
        "notes": notes,
    }


def training_history(model_id: str) -> dict | None:
    p1 = notebooks.parsed("phase1") or {}
    if p1.get("model_name") != model_id or not p1.get("training"):
        return None
    t = p1["training"]
    best = max(t["epochs"], key=lambda e: e["val_iou"]) if t["epochs"] else None
    return {
        "provenance": "historical",
        "source": f"{p1['source']} · cell {t['cell']} output",
        "epochs": t["epochs"],
        "best_epoch": best,
        "best_val_iou_reported": t["best_val_iou_reported"],
        "params_reported": p1.get("params"),
        "split": p1.get("split"),
        "img_size": p1.get("img_size"),
        "metric_note": "IoU is the per-batch mean at threshold 0.5, averaged over batches (Phase I calculate_metrics).",
    }
