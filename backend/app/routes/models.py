from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from ..registry import SAFE_ID, get_registry
from ..services import checkpoints, masks
from ..services import models as model_service
from .files import figure_url

router = APIRouter(tags=["models"])

EVALUATION_UNAVAILABLE = {
    "ground_truth_available": False,
    "reason": "No ground-truth masks (or satellite tiles) exist in the repository. The DeepGlobe download lived in "
              "temporary Colab storage. IoU, Dice, precision and recall therefore cannot be computed for any sample.",
}


def _model_or_404(model_id: str) -> dict:
    if not SAFE_ID.match(model_id):
        raise HTTPException(400, "Invalid model id.")
    try:
        return model_service.describe(model_id)
    except model_service.ModelNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/models", summary="Available segmentation models and post-processing mask sets")
def list_models() -> list[dict]:
    out = []
    for mid in model_service.list_model_ids():
        d = model_service.describe(mid)
        d["figure_urls"] = {k: figure_url(v) for k, v in d["figures"].items()}
        out.append(d)
    return out


@router.get("/models/{model_id}", summary="One model's catalog entry")
def get_model(model_id: str) -> dict:
    d = _model_or_404(model_id)
    d["figure_urls"] = {k: figure_url(v) for k, v in d["figures"].items()}
    return d


@router.get("/models/{model_id}/samples", summary="Sample tiles that have a predicted mask for this model")
def model_samples(model_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                  q: str | None = Query(None, max_length=32, pattern=r"^[A-Za-z0-9_]*$")) -> dict:
    d = _model_or_404(model_id)
    reg = get_registry()
    mset = d["mask_set"]
    ids = sorted(reg.mask_sets.get(mset, {}), key=lambda s: (len(s), s)) if mset else []
    if q:
        ids = [i for i in ids if q in i]
    page = ids[offset: offset + limit]
    items = []
    for iid in page:
        items.append({
            "image_id": iid,
            "mask_url": f"/api/masks/{mset}/{iid}.png",
            "other_mask_sets": sorted(s for s, files in reg.mask_sets.items() if s != mset and iid in files),
            "graph_ids": [f"{s}-{iid}" for s in sorted(reg.graph_sets) if iid in reg.graph_sets[s]],
        })
    return {"model_id": model_id, "mask_set": mset, "total": len(ids), "offset": offset, "limit": limit, "items": items}


@router.get("/models/{model_id}/metrics", summary="Historical training metrics and evaluation availability")
def model_metrics(model_id: str) -> dict:
    d = _model_or_404(model_id)
    return {
        "model_id": model_id,
        "training_history": model_service.training_history(model_id),
        "training_curves_figure": figure_url(d["figures"]["training_curves"]),
        "predictions_figure": figure_url(d["figures"]["predictions"]),
        "evaluation": EVALUATION_UNAVAILABLE,
        "notes": d["notes"],
    }


@router.get("/models/{model_id}/checkpoint", summary="Inspect the checkpoint and test architecture compatibility")
async def model_checkpoint(model_id: str) -> dict:
    d = _model_or_404(model_id)
    path = get_registry().checkpoints.get(model_id)
    if path is None:
        return {"model_id": model_id, "available": False, "diagnostic": "No checkpoint file for this model."}
    info = await run_in_threadpool(checkpoints.inspect_checkpoint, path)
    compat = await run_in_threadpool(checkpoints.compatibility, path)
    return {"model_id": model_id, "available": True, "label": d["label"], "inspection": info, "compatibility": compat,
            "provenance": "measured by the app from the checkpoint file"}


@router.post("/models/{model_id}/benchmark", summary="CPU latency on a synthetic 512x512 input (only if the architecture loads)")
async def model_benchmark(model_id: str) -> dict:
    _model_or_404(model_id)
    path = get_registry().checkpoints.get(model_id)
    if path is None:
        raise HTTPException(404, "No checkpoint file for this model.")
    result = await run_in_threadpool(checkpoints.benchmark, path)
    return {"model_id": model_id, **result, "provenance": "measured by the app (synthetic input; speed only, not accuracy)"}


@router.get("/samples/{image_id}", summary="All artifacts available for one tile, across models")
def sample_detail(image_id: str) -> dict:
    if not SAFE_ID.match(image_id):
        raise HTTPException(400, "Invalid image id.")
    reg = get_registry()
    mask_rows = []
    model_by_mask = {model_service.describe(m)["mask_set"]: m for m in model_service.list_model_ids()}
    for mset in sorted(reg.mask_sets):
        path = reg.mask_sets[mset].get(image_id)
        if not path:
            continue
        try:
            stats = masks.mask_stats(path)
        except masks.MaskReadError as exc:
            stats = {"error": str(exc)}
        mask_rows.append({"mask_set": mset, "model_id": model_by_mask.get(mset), "url": f"/api/masks/{mset}/{image_id}.png",
                          "stats": stats})
    if not mask_rows and not any(image_id in g for g in reg.graph_sets.values()):
        raise HTTPException(404, f"No artifacts for tile '{image_id}'.")
    figs = [{"figure_id": f.figure_id, "kind": f.kind, "title": f.title, "url": figure_url(f.figure_id)}
            for f in reg.figures.values() if f.image_id == image_id]
    return {
        "image_id": image_id,
        "masks": mask_rows,
        "graph_ids": [f"{s}-{image_id}" for s in sorted(reg.graph_sets) if image_id in reg.graph_sets[s]],
        "figures": sorted(figs, key=lambda f: f["kind"]),
        "satellite_available": False,
        "ground_truth_available": False,
        "evaluation": EVALUATION_UNAVAILABLE,
        "stats_provenance": "mask statistics recomputed by the app (8-connected components on the binarized PNG)",
    }
