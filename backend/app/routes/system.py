from __future__ import annotations

import importlib.util

from fastapi import APIRouter

from .. import __version__
from ..definitions import DEFINITIONS
from ..graph_io import GraphLoadError
from ..registry import get_registry, rescan
from ..services import experiments, notebooks
from ..services import graphs as graph_service
from ..services import models as model_service
from ..services.views import source_mask

router = APIRouter(tags=["system"])


def _torch_available() -> bool:
    return importlib.util.find_spec("torch") is not None


@router.get("/health", summary="Service status and artifact discovery result")
def health() -> dict:
    reg = get_registry()
    return {
        "status": "ok" if reg.outputs_root else "degraded",
        "version": __version__,
        "data_dir": str(reg.data_dir),
        "outputs_root": str(reg.outputs_root) if reg.outputs_root else None,
        "checkpoints_root": str(reg.checkpoints_root) if reg.checkpoints_root else None,
        "notebooks": {k: v.name for k, v in reg.notebooks.items()},
        "counts": reg.counts(),
        "optional_features": {"torch": _torch_available()},
        "warnings": reg.warnings,
    }


@router.post("/registry/rescan", summary="Re-scan the data directory for artifacts")
def registry_rescan() -> dict:
    graph_service.clear_cache()
    reg = rescan()
    return {"counts": reg.counts(), "warnings": reg.warnings}


@router.get("/definitions", summary="Metric definitions used across the app")
def definitions() -> list[dict]:
    return DEFINITIONS


@router.get("/overview", summary="Inventory of artifacts and per-set aggregates")
def overview() -> dict:
    reg = get_registry()
    graph_sets = []
    for set_id in sorted(reg.graph_sets):
        totals = {"nodes": 0, "edges": 0, "healed_edges": 0, "graphs_ok": 0, "graphs_failed": 0, "multi_component_graphs": 0}
        errors = []
        for image_id in reg.graph_sets[set_id]:
            try:
                lg = graph_service.get_graph(f"{set_id}-{image_id}")
            except GraphLoadError as exc:
                totals["graphs_failed"] += 1
                errors.append(f"{image_id}: {exc.message}")
                continue
            totals["graphs_ok"] += 1
            totals["nodes"] += len(lg.doc.nodes)
            totals["edges"] += len(lg.doc.edges)
            totals["healed_edges"] += sum(1 for e in lg.doc.edges if e.healed)
            _, sizes = graph_service.membership(lg, "healed")
            totals["multi_component_graphs"] += len(sizes) > 1
        src = source_mask(set_id)
        graph_sets.append({
            "set_id": set_id, "graphs": len(reg.graph_sets[set_id]), **totals,
            "source_mask_set": src["mask_set"], "source_verified": src["verified"], "provenance_note": src["note"],
            "has_analysis": set_id in reg.analysis_sets, "errors": errors[:20],
        })
    p1 = notebooks.parsed("phase1")
    model_rows = []
    for mid in model_service.list_model_ids(reg):
        d = model_service.describe(mid, reg)
        hist = model_service.training_history(mid)
        model_rows.append({
            "id": mid, "label": d["label"], "kind": d["kind"], "mask_count": d["mask_count"],
            "checkpoint_bytes": d["checkpoint"]["size_bytes"] if d["checkpoint"] else None,
            "best_val_iou": hist["best_epoch"]["val_iou"] if hist and hist["best_epoch"] else None,
            "params_reported": hist["params_reported"] if hist else None,
        })
    ids = reg.all_graph_ids()
    return {
        "counts": reg.counts(),
        "graph_sets": graph_sets,
        "models": model_rows,
        "experiments": experiments.list_experiments(),
        "default_graph_id": ids[0] if ids else None,
        "notebook_errors": (p1 or {}).get("errors", []),
        "warnings": reg.warnings,
    }
