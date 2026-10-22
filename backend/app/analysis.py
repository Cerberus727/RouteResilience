"""Network metrics and failure simulation (NetworkX).

All functions treat their input graph as read-only. Simulations always run on
`G.copy()`, and cached graphs are frozen, so any accidental mutation raises.

Metric definitions (see docs/ARCHITECTURE.md §5). Let N0 be the node count of
the *baseline* graph and d(i, j) the shortest path length using the edge
attribute `length` (pixels), with d = ∞ when i and j are disconnected or when
either node was removed.

* reachable_pairs           = Σ_C |C|(|C|-1)/2 over connected components C
* reachable_pair_fraction   = reachable_pairs / (N0(N0-1)/2)
* lcc_fraction              = |largest component| / N0
* avg_path_length           = mean d(i, j) over *reachable* pairs only (None if none)
* efficiency                = 1/(N0(N0-1)) · Σ_{i≠j} 1/d(i, j)   (1/∞ := 0), unit px⁻¹
* efficiency_retention      = efficiency_after / efficiency_baseline ∈ [0, 1]
* degradation               = 1 − efficiency_retention
Removing nodes or edges can never increase `efficiency` (each term can only shrink
or vanish, and the normalization stays at N0), so retention is bounded and monotone.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Iterable

import networkx as nx

WEIGHT = "length"


class GraphTooLargeError(Exception):
    pass


class InvalidTargetError(Exception):
    pass


@dataclass
class NetworkMetrics:
    nodes: int
    edges: int
    baseline_nodes: int
    components: int
    isolated_nodes: int
    lcc_size: int
    lcc_fraction: float | None
    reachable_pairs: int
    total_pairs: int
    reachable_pair_fraction: float | None
    avg_path_length: float | None
    efficiency: float | None
    density: float | None
    avg_degree: float | None
    total_length: float

    def to_dict(self) -> dict:
        return asdict(self)


def _pairs(n: int) -> int:
    return n * (n - 1) // 2


def component_membership(G: nx.Graph) -> tuple[dict[str, int], list[int]]:
    """Component index per node: 0 = largest. Ties broken by smallest node id so
    the numbering is deterministic across requests."""
    comps = sorted(nx.connected_components(G), key=lambda c: (-len(c), min(c)))
    membership = {node: idx for idx, comp in enumerate(comps) for node in comp}
    return membership, [len(c) for c in comps]


def compute_metrics(G: nx.Graph, baseline_nodes: int | None = None, max_nodes: int = 5000) -> NetworkMetrics:
    n = G.number_of_nodes()
    n0 = baseline_nodes if baseline_nodes is not None else n
    if n > max_nodes:
        raise GraphTooLargeError(f"Graph has {n} nodes; all-pairs metrics are limited to {max_nodes}.")
    _, sizes = component_membership(G)
    reachable = sum(_pairs(s) for s in sizes)
    total_pairs = _pairs(n0)

    path_sum = 0.0
    inv_sum = 0.0
    counted = 0
    for source, dists in nx.all_pairs_dijkstra_path_length(G, weight=WEIGHT):
        for target, d in dists.items():
            if target == source:
                continue
            counted += 1  # ordered pairs
            path_sum += d
            if d > 0:
                inv_sum += 1.0 / d
    return NetworkMetrics(
        nodes=n,
        edges=G.number_of_edges(),
        baseline_nodes=n0,
        components=len(sizes),
        isolated_nodes=sum(1 for s in sizes if s == 1),
        lcc_size=sizes[0] if sizes else 0,
        lcc_fraction=(sizes[0] / n0) if (sizes and n0) else None,
        reachable_pairs=reachable,
        total_pairs=total_pairs,
        reachable_pair_fraction=(reachable / total_pairs) if total_pairs else None,
        avg_path_length=(path_sum / counted) if counted else None,
        efficiency=(inv_sum / (n0 * (n0 - 1))) if n0 > 1 else None,
        density=nx.density(G) if n > 1 else None,
        avg_degree=(2 * G.number_of_edges() / n) if n else None,
        total_length=float(sum(d.get(WEIGHT, 0.0) for _, _, d in G.edges(data=True))),
    )


def relative_change(before: float | None, after: float | None) -> float | None:
    if before is None or after is None or before == 0:
        return None
    return (after - before) / before


def compare(baseline: NetworkMetrics, after: NetworkMetrics) -> dict:
    b, a = baseline.to_dict(), after.to_dict()
    fields = [
        "nodes", "edges", "components", "lcc_size", "lcc_fraction", "reachable_pairs",
        "reachable_pair_fraction", "avg_path_length", "efficiency",
    ]
    changes = {
        f: {"baseline": b[f], "after": a[f],
            "delta": (a[f] - b[f]) if (a[f] is not None and b[f] is not None) else None,
            "relative": relative_change(b[f], a[f])}
        for f in fields
    }
    retention = (after.efficiency / baseline.efficiency) if (baseline.efficiency and after.efficiency is not None) else None
    pair_retention = (
        after.reachable_pair_fraction / baseline.reachable_pair_fraction
        if (baseline.reachable_pair_fraction and after.reachable_pair_fraction is not None) else None
    )
    return {
        "changes": changes,
        "efficiency_retention": retention,
        "degradation": (1 - retention) if retention is not None else None,
        "pair_connectivity_retention": pair_retention,
    }


def betweenness(G: nx.Graph, scope: str = "full") -> dict[str, float]:
    """Length-weighted, normalized betweenness. scope='lcc' reproduces Phase III,
    which scored only the largest component (all other nodes then get 0)."""
    if G.number_of_nodes() < 2:
        return {n: 0.0 for n in G.nodes}
    if scope == "lcc":
        lcc = max(nx.connected_components(G), key=len)
        H = G.subgraph(lcc)
        bc = nx.betweenness_centrality(H, weight=WEIGHT, normalized=True) if len(lcc) > 1 else {}
        return {n: float(bc.get(n, 0.0)) for n in G.nodes}
    return {n: float(v) for n, v in nx.betweenness_centrality(G, weight=WEIGHT, normalized=True).items()}


def rank_nodes(G: nx.Graph, bc: dict[str, float]) -> list[str]:
    return sorted(G.nodes, key=lambda n: (-bc.get(n, 0.0), -G.degree(n), n))


def edge_lookup(G: nx.Graph) -> dict[str, tuple[str, str]]:
    return {d["id"]: (u, v) for u, v, d in G.edges(data=True)}


def remove_elements(G: nx.Graph, nodes: Iterable[str] = (), edges: Iterable[str] = ()) -> nx.Graph:
    """Return a mutable *copy* of G without the given nodes / edge IDs."""
    nodes, edges = list(nodes), list(edges)
    missing_nodes = [n for n in nodes if n not in G]
    lookup = edge_lookup(G)
    missing_edges = [e for e in edges if e not in lookup]
    if missing_nodes or missing_edges:
        parts = []
        if missing_nodes:
            parts.append(f"unknown node(s): {', '.join(missing_nodes[:10])}")
        if missing_edges:
            parts.append(f"unknown edge(s): {', '.join(missing_edges[:10])}")
        raise InvalidTargetError("; ".join(parts))
    H = G.copy()  # nx.Graph.copy() of a frozen graph is a new, unfrozen graph
    H.remove_edges_from([lookup[e] for e in edges if H.has_edge(*lookup[e])])
    H.remove_nodes_from(nodes)
    return H


def node_removal_impact(G: nx.Graph, node: str, baseline: NetworkMetrics, max_nodes: int) -> dict:
    after = compute_metrics(remove_elements(G, nodes=[node]), baseline.nodes, max_nodes)
    cmp = compare(baseline, after)
    return {
        "node": node,
        "components_after": after.components,
        "components_delta": after.components - baseline.components,
        "lcc_fraction_after": after.lcc_fraction,
        "reachable_pair_fraction_after": after.reachable_pair_fraction,
        "reachable_pairs_lost": baseline.reachable_pairs - after.reachable_pairs,
        "avg_path_length_after": after.avg_path_length,
        "efficiency_after": after.efficiency,
        "efficiency_retention": cmp["efficiency_retention"],
        "degradation": cmp["degradation"],
    }


def run_steps(
    G: nx.Graph,
    steps: list[tuple[str, str]] | None,
    baseline: NetworkMetrics,
    max_nodes: int,
    strategy: str | None = None,
    k: int = 0,
) -> tuple[list[dict], nx.Graph]:
    """Apply removals one at a time to a copy of G, recording metrics after each.

    steps: explicit [("node"|"edge", id), ...]; or
    strategy='betweenness_static'   -> top-k nodes by *baseline* betweenness,
    strategy='betweenness_adaptive' -> recompute betweenness on the damaged graph
                                       before every removal (k steps).
    """
    lookup = edge_lookup(G)
    if steps is not None:
        unknown = [i for kind, i in steps if (kind == "node" and i not in G) or (kind == "edge" and i not in lookup)]
        if unknown:
            raise InvalidTargetError(f"unknown id(s): {', '.join(unknown[:10])}")
    H = G.copy()  # never mutate G
    bc0 = betweenness(G) if strategy == "betweenness_static" else None
    if strategy == "betweenness_static":
        steps = [("node", n) for n in rank_nodes(G, bc0)[:k]]
    planned = steps if steps is not None else [("node", None)] * k  # adaptive: chosen per step
    records: list[dict] = []
    for idx, (kind, target) in enumerate(planned):
        score = None
        note = None
        if strategy == "betweenness_adaptive":
            if H.number_of_nodes() == 0:
                break
            bc = betweenness(H)
            target = rank_nodes(H, bc)[0]
            score = bc[target]
        elif strategy == "betweenness_static":
            score = bc0[target]
        if kind == "node":
            if target in H:
                H.remove_node(target)
            else:
                note = "already removed"
        else:
            u, v = lookup[target]
            if H.has_edge(u, v):
                H.remove_edge(u, v)
            else:
                note = "already removed (an endpoint was removed earlier)"
        m = compute_metrics(H, baseline.nodes, max_nodes)
        cmp = compare(baseline, m)
        records.append({
            "step": idx + 1,
            "kind": kind,
            "removed": target,
            "betweenness_at_removal": score,
            "note": note,
            "metrics": m.to_dict(),
            "efficiency_retention": cmp["efficiency_retention"],
            "pair_connectivity_retention": cmp["pair_connectivity_retention"],
        })
    return records, H


def finite_or_none(x: float | None) -> float | None:
    return x if (x is not None and math.isfinite(x)) else None
