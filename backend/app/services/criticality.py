"""Critical-junction ranking with recomputed removal impact."""

from __future__ import annotations

from .. import analysis
from ..config import get_settings
from ..graph_io import Variant
from . import experiments
from . import graphs as graph_service
from .graphs import LoadedGraph
from .views import positions

INTERPRETATION = (
    "Betweenness measures how many length-weighted shortest paths pass through a junction in this extracted graph. "
    "It is a structural indicator, not a probability that the junction fails in the real world, and it inherits "
    "every error of the segmentation and healing steps."
)


def critical_nodes(lg: LoadedGraph, variant: Variant, top_k: int, scope: str, impact_k: int) -> dict:
    settings = get_settings()
    G = lg.graph(variant)
    bc = graph_service.betweenness(lg, variant, scope)
    ranked = analysis.rank_nodes(G, bc)
    mem, sizes = graph_service.membership(lg, variant)
    pos, _ = positions(lg)
    baseline = graph_service.baseline_metrics(lg, variant)
    rows = []
    for i, n in enumerate(ranked[:top_k]):
        row = {
            "id": n, "rank": i + 1, "betweenness": bc.get(n, 0.0), "degree": G.degree(n),
            "component": mem[n], "component_size": sizes[mem[n]], "x": pos[n][0], "y": pos[n][1],
            "neighbors": sorted(G.neighbors(n)),
        }
        if i < impact_k:
            row["impact"] = analysis.node_removal_impact(G, n, baseline, settings.max_graph_nodes)
        rows.append(row)
    hist = experiments.read_analysis(lg.set_id, lg.image_id) if variant == "healed" else None
    return {
        "graph_id": lg.graph_id,
        "variant": variant,
        "scope": scope,
        "baseline": baseline.to_dict(),
        "nodes": rows,
        "total_nodes": G.number_of_nodes(),
        "nonzero_betweenness": sum(1 for v in bc.values() if v > 0),
        "notebook": hist,
        "notebook_note": "Phase III scored only the largest component; use scope=lcc to reproduce its numbers." if hist else None,
        "interpretation": INTERPRETATION,
    }


def node_detail(lg: LoadedGraph, node_id: str, variant: Variant) -> dict | None:
    G = lg.graph(variant)
    if node_id not in G:
        return None
    settings = get_settings()
    bc = graph_service.betweenness(lg, variant, "full")
    ranked = analysis.rank_nodes(G, bc)
    mem, sizes = graph_service.membership(lg, variant)
    pos, layout = positions(lg)
    rec = lg.doc.node_index[node_id]
    neighbors = []
    for nb in sorted(G.neighbors(node_id)):
        data = G.edges[node_id, nb]
        neighbors.append({"id": nb, "edge_id": data["id"], "length": data["length"], "healed": data["healed"], "degree": G.degree(nb)})
    baseline = graph_service.baseline_metrics(lg, variant)
    hist = experiments.read_analysis(lg.set_id, lg.image_id) if variant == "healed" else None
    gk = next((g for g in (hist or {}).get("gatekeepers", []) if g.get("id") == node_id), None)
    abl = next((a for a in (hist or {}).get("ablation_study", []) if a.get("removed_node") == node_id), None)
    return {
        "graph_id": lg.graph_id,
        "variant": variant,
        "id": node_id,
        "x": pos[node_id][0], "y": pos[node_id][1], "layout": layout,
        "degree": G.degree(node_id),
        "file_degree": rec.file_degree,
        "attributes": rec.extra,
        "component": mem[node_id], "component_size": sizes[mem[node_id]],
        "betweenness": bc.get(node_id, 0.0),
        "rank": ranked.index(node_id) + 1,
        "neighbors": neighbors,
        "impact": analysis.node_removal_impact(G, node_id, baseline, settings.max_graph_nodes),
        "notebook_gatekeeper": gk,
        "notebook_ablation": abl,
    }
