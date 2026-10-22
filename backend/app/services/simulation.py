"""Failure simulation on copies of cached (frozen) graphs."""

from __future__ import annotations

from .. import analysis
from ..config import get_settings
from ..schemas import SimulationRequest
from . import graphs as graph_service
from .graphs import LoadedGraph
from .views import limits_check

STRATEGIES = {"betweenness_static", "betweenness_adaptive"}


def simulate(lg: LoadedGraph, req: SimulationRequest) -> dict:
    settings = get_settings()
    G = lg.graph(req.variant)
    baseline = graph_service.baseline_metrics(lg, req.variant)

    if req.strategy in STRATEGIES:
        if req.remove_nodes or req.remove_edges:
            raise analysis.InvalidTargetError("Give either explicit removals or a predefined strategy, not both.")
        k = min(req.k, G.number_of_nodes())
        limits_check(k, k)
        records, H = analysis.run_steps(G, None, baseline, settings.max_graph_nodes, strategy=req.strategy, k=k)
        mode = "sequential"
    else:
        total = len(req.remove_nodes) + len(req.remove_edges)
        if total == 0:
            raise analysis.InvalidTargetError("Select at least one node or edge to remove, or choose a predefined strategy.")
        if req.mode == "single":
            limits_check(total)
            H = analysis.remove_elements(G, req.remove_nodes, req.remove_edges)
            after = analysis.compute_metrics(H, baseline.nodes, settings.max_graph_nodes)
            cmp = analysis.compare(baseline, after)
            records = [{
                "step": 1, "kind": "batch", "removed": f"{len(req.remove_nodes)} node(s), {len(req.remove_edges)} edge(s)",
                "betweenness_at_removal": None, "note": None, "metrics": after.to_dict(),
                "efficiency_retention": cmp["efficiency_retention"],
                "pair_connectivity_retention": cmp["pair_connectivity_retention"],
            }]
        else:
            limits_check(total, total)
            steps = [("node", n) for n in req.remove_nodes] + [("edge", e) for e in req.remove_edges]
            records, H = analysis.run_steps(G, steps, baseline, settings.max_graph_nodes)
        mode = req.mode

    final = analysis.compute_metrics(H, baseline.nodes, settings.max_graph_nodes)
    membership, sizes = analysis.component_membership(H)
    removed_nodes = sorted(set(G.nodes) - set(H.nodes))
    removed_edges = sorted({d["id"] for _, _, d in G.edges(data=True)} - {d["id"] for _, _, d in H.edges(data=True)})
    return {
        "graph_id": lg.graph_id,
        "variant": req.variant,
        "mode": mode,
        "strategy": req.strategy,
        "request": req.model_dump(),
        "baseline": baseline.to_dict(),
        "final": final.to_dict(),
        "comparison": analysis.compare(baseline, final),
        "steps": records,
        "removed_nodes": removed_nodes,
        "removed_edges": removed_edges,
        "final_membership": membership,
        "final_component_sizes": sizes,
        "computed_by": "app (NetworkX on a copy of the stored graph)",
        "disconnected_pairs": "excluded from avg_path_length; contribute 0 to efficiency",
    }
