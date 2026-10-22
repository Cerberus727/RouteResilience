"""Experiment history assembled from real artifacts and notebook logs."""

from __future__ import annotations

import csv
import json

from ..graph_io import GraphLoadError
from ..registry import get_registry
from . import graphs as graph_service
from . import masks as mask_service
from . import models as model_service
from . import notebooks


class ExperimentNotFoundError(Exception):
    pass


def _num(v: str):
    try:
        f = float(v)
        return int(f) if f.is_integer() and "." not in v else f
    except (TypeError, ValueError):
        return v


def _graph_set_rows(set_id: str) -> tuple[list[dict], list[str]]:
    reg = get_registry()
    rows, errors = [], []
    for image_id in sorted(reg.graph_sets.get(set_id, {}), key=lambda s: (len(s), s)):
        gid = f"{set_id}-{image_id}"
        try:
            lg = graph_service.get_graph(gid)
        except GraphLoadError as exc:
            errors.append(f"{gid}: {exc.message}")
            continue
        st = lg.doc.file_stats or {}
        mem, sizes = graph_service.membership(lg, "healed")
        healed = sum(1 for e in lg.doc.edges if e.healed)
        rows.append({
            "graph_id": gid, "image_id": image_id,
            "nodes": len(lg.doc.nodes), "edges": len(lg.doc.edges), "healed_edges": healed,
            "components": len(sizes),
            "conn_before_file": st.get("connectivity_before"), "conn_after_file": st.get("connectivity_after"),
            "bridges_added_file": st.get("bridges_added"),
        })
    return rows, errors


def _criticality_rows(set_id: str) -> list[dict]:
    path = get_registry().analysis_csv.get(set_id)
    if not path:
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [{k: _num(v) for k, v in row.items()} for row in csv.DictReader(f)]


def _sam_rows() -> tuple[list[dict], str | None]:
    reg = get_registry()
    p1 = notebooks.parsed("phase1") or {}
    sam = p1.get("sam_repair") or {}
    base_set = (sam.get("input_mask_dir") or "").removeprefix("masks_") or None
    repaired = reg.mask_sets.get("sam_repaired", {})
    base = reg.mask_sets.get(base_set, {}) if base_set else {}
    rows = []
    logged = {r["image_id"]: r for r in sam.get("rows", [])}
    for iid in sorted(repaired):
        row: dict = {"image_id": iid, "logged_in_notebook": iid in logged}
        try:
            after = mask_service.mask_stats(repaired[iid])
            row.update(components_after=after["components"], largest_frac_after=after["largest_component_fraction"])
            if iid in base:
                before = mask_service.mask_stats(base[iid])
                row.update(components_before=before["components"], largest_frac_before=before["largest_component_fraction"],
                           **mask_service.compare_masks(base[iid], repaired[iid]))
        except mask_service.MaskReadError as exc:
            row["error"] = str(exc)
        if iid in logged:
            row["notebook"] = logged[iid]
        rows.append(row)
    return rows, base_set


def list_experiments() -> list[dict]:
    reg = get_registry()
    out: list[dict] = []
    p1 = notebooks.parsed("phase1")
    p2 = notebooks.parsed("phase2")

    for mid in model_service.list_model_ids(reg):
        hist = model_service.training_history(mid)
        if hist:
            out.append({
                "id": f"training-{mid}", "kind": "training", "phase": "Phase I",
                "title": f"{model_service.describe(mid, reg)['label']} training run",
                "provenance": "historical", "source": hist["source"],
                "summary": {"epochs": len(hist["epochs"]), "best_val_iou": hist["best_epoch"]["val_iou"] if hist["best_epoch"] else None,
                            "best_epoch": hist["best_epoch"]["epoch"] if hist["best_epoch"] else None},
            })

    if "sam_repaired" in reg.mask_sets:
        logged = len(((p1 or {}).get("sam_repair") or {}).get("rows", []))
        out.append({
            "id": "sam-repair", "kind": "mask_repair", "phase": "Phase I",
            "title": "SAM mask repair", "provenance": "mixed",
            "source": f"masks_sam_repaired ({len(reg.mask_sets['sam_repaired'])} masks); notebook log for {logged} tiles",
            "summary": {"repaired_masks": len(reg.mask_sets["sam_repaired"]), "logged_tiles": logged},
        })

    for set_id in sorted(reg.graph_sets):
        prov = notebooks.graph_set_provenance(set_id)
        files = reg.graph_sets[set_id]
        out.append({
            "id": f"graphs-{set_id}", "kind": "graph_extraction", "phase": "Phase II",
            "title": f"Graph extraction + healing — graphs_{set_id}", "provenance": "historical",
            "source": f"graphs_{set_id}/ ({len(files)} files)",
            "summary": {"graphs": len(files), "source_mask_set": prov["source_mask_set"], "source_verified": prov["verified"]},
            "warning": prov["note"],
        })

    if p2 and p2.get("synthetic"):
        rows = p2["synthetic"]["rows"]
        out.append({
            "id": "synthetic-occlusion", "kind": "synthetic_occlusion", "phase": "Phase II",
            "title": "Synthetic occlusion test (30 px gap)", "provenance": "historical",
            "source": f"{p2['source']} · cell {p2['synthetic']['cell']} output",
            "summary": {"tiles_logged": len(rows)},
        })
    if p2 and p2.get("sweep"):
        out.append({
            "id": "healing-sweep", "kind": "healing_sweep", "phase": "Phase II",
            "title": "Healing sweep over predicted masks", "provenance": "historical",
            "source": f"{p2['source']} · cell {p2['sweep']['cell']} output", "summary": dict(p2["sweep"]),
        })

    for set_id in sorted(reg.analysis_sets):
        out.append({
            "id": f"criticality-{set_id}", "kind": "criticality", "phase": "Phase III",
            "title": f"Betweenness + top-5 ablation — analysis_{set_id}", "provenance": "historical",
            "source": f"analysis_{set_id}/ ({len(reg.analysis_sets[set_id])} files)"
                      + (f" + {reg.analysis_csv[set_id].name}" if set_id in reg.analysis_csv else ""),
            "summary": {"analyses": len(reg.analysis_sets[set_id])},
            "warning": "The stored 'resilience index' is L_baseline / L_perturbed. It rises when a removal fragments "
                       "the network, so it is not a degradation measure. See docs/ARTIFACT_AUDIT.md §2.",
        })
    return out


def get_experiment(exp_id: str) -> dict:
    meta = next((e for e in list_experiments() if e["id"] == exp_id), None)
    if meta is None:
        raise ExperimentNotFoundError(f"Unknown experiment '{exp_id}'.")
    detail = dict(meta)
    kind = meta["kind"]
    if kind == "training":
        detail["history"] = model_service.training_history(exp_id.removeprefix("training-"))
    elif kind == "mask_repair":
        rows, base = _sam_rows()
        detail["baseline_mask_set"] = base
        detail["rows"] = rows
        detail["row_note"] = ("components/largest_frac/pixel counts are recomputed by the app from the mask PNGs "
                              "(8-connected labeling). 'notebook' holds the values printed in Phase I.")
    elif kind == "graph_extraction":
        rows, errors = _graph_set_rows(exp_id.removeprefix("graphs-"))
        detail["rows"], detail["errors"] = rows, errors
        detail["row_note"] = "nodes/edges/healed_edges/components are recomputed from the JSON; *_file values are the stored stats."
    elif kind == "synthetic_occlusion":
        detail["rows"] = notebooks.parsed("phase2")["synthetic"]["rows"]
    elif kind == "healing_sweep":
        detail["rows"] = []
    elif kind == "criticality":
        set_id = exp_id.removeprefix("criticality-")
        detail["rows"] = _criticality_rows(set_id)
        detail["row_note"] = "Values from the Phase III CSV. Node/edge counts refer to the largest component only."
    return detail


def read_analysis(set_id: str, image_id: str) -> dict | None:
    """Phase III criticality JSON for one graph (historical), or None."""
    path = get_registry().analysis_sets.get(set_id, {}).get(image_id)
    if not path:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": f"{path.name} is unreadable: {exc}"}
    return {
        "source": f"analysis_{set_id}/{path.name}",
        "gatekeepers": data.get("gatekeepers", []),
        "metrics": data.get("metrics", {}),
        "ablation_study": data.get("ablation_study", []),
    }
