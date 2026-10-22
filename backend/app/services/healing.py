"""Healing review: compares the pre-healing graph with the stored healed graph."""

from __future__ import annotations

from .. import analysis
from ..registry import get_registry
from . import graphs as graph_service
from . import masks as mask_service
from . import reviews
from .graphs import LoadedGraph
from .views import source_mask


def artifact_version(lg: LoadedGraph) -> str:
    return f"{lg.version[0]}:{lg.version[1]}"


def healing_summary(lg: LoadedGraph) -> dict:
    reg = get_registry()
    prov = lg.doc.healing_provenance
    m_orig = graph_service.baseline_metrics(lg, "original")
    m_heal = graph_service.baseline_metrics(lg, "healed")
    review_map = reviews.get_reviews(lg.graph_id) if prov != "unavailable" else {}
    version = artifact_version(lg)
    healed = []
    if prov != "unavailable":
        for e in lg.doc.edges:
            if not e.healed:
                continue
            r = review_map.get(e.id)
            healed.append({
                "id": e.id, "source": e.source, "target": e.target, "length": e.length,
                "coords": [list(p) for p in e.coords],
                "review": r["decision"] if r else None,
                "review_note": r.get("note") if r else None,
                "review_updated_at": r.get("updated_at") if r else None,
                "review_stale": bool(r and r.get("artifact_version") != version),
            })
    # Stats of the graph with only approved bridges (if any decisions exist)
    approved_ids = {e["id"] for e in healed if e["review"] == "approved"}
    rejected_ids = {e["id"] for e in healed if e["review"] == "rejected"}
    m_reviewed = None
    if rejected_ids:
        H = analysis.remove_elements(lg.healed, edges=sorted(rejected_ids))
        m_reviewed = analysis.compute_metrics(H, m_heal.nodes).to_dict()

    src = source_mask(lg.set_id)
    masks: dict = {"source": None, "sam_repaired": None, "note": None}
    src_path = reg.mask_sets.get(src["mask_set"], {}).get(lg.image_id) if src["mask_set"] else None
    if src_path:
        masks["source"] = {"mask_set": src["mask_set"], "url": f"/api/masks/{src['mask_set']}/{lg.image_id}.png",
                           "stats": _safe_stats(src_path), "verified": src["verified"]}
    sam_path = reg.mask_sets.get("sam_repaired", {}).get(lg.image_id)
    if sam_path:
        masks["sam_repaired"] = {"mask_set": "sam_repaired", "url": f"/api/masks/sam_repaired/{lg.image_id}.png", "stats": _safe_stats(sam_path)}
        if src_path:
            try:
                masks["diff"] = mask_service.compare_masks(src_path, sam_path)
            except mask_service.MaskReadError as exc:
                masks["diff"] = {"error": str(exc)}
        masks["note"] = ("The SAM-repaired mask exists for this tile, but no graph was built from it. The graph-level "
                         "comparison below uses the healing bridges recorded in the graph file.")
    else:
        masks["note"] = "No SAM-repaired mask exists for this tile."

    return {
        "graph_id": lg.graph_id,
        "healing_provenance": prov,
        "provenance_note": {
            "recorded": "Every edge carries a 'healed' flag written by Phase II heal_graph(); the pre-healing graph is the stored graph minus those edges.",
            "partial": "Only some edges carry a 'healed' flag; the comparison covers the flagged edges only.",
            "unavailable": "This graph file does not record which edges were added by healing. No bridge list can be shown, and none is inferred.",
        }[prov],
        "healed_edges": healed,
        "counts": {
            "edges": len(lg.doc.edges),
            "healed_edges": len(healed),
            "approved": len(approved_ids),
            "rejected": len(rejected_ids),
            "unreviewed": len(healed) - len(approved_ids) - len(rejected_ids),
        },
        "metrics_original": m_orig.to_dict(),
        "metrics_healed": m_heal.to_dict(),
        "metrics_reviewed": m_reviewed,
        "comparison": analysis.compare(m_orig, m_heal),
        "file_stats": lg.doc.file_stats,
        "masks": masks,
        "healing_rule": "Phase II heal_graph(): bridge endpoint pairs within 40 px whose directions differ by ≤ 35°; "
                        "weight = distance + 0.5·angle; one bridge per endpoint; the component check is disabled, so loops can be added.",
        "caveat": "More connectivity after healing does not mean the graph is more accurate. Each bridge is a hypothesis.",
        "artifact_version": version,
    }


def _safe_stats(path):
    try:
        return mask_service.mask_stats(path)
    except mask_service.MaskReadError as exc:
        return {"error": str(exc)}
