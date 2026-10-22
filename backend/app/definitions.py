"""Metric definitions, served to the UI and embedded in reports."""

DEFINITIONS: list[dict[str, str]] = [
    {"key": "nodes", "name": "Nodes / edges", "formula": "|V|, |E|",
     "text": "Nodes are skeleton junctions and endpoints (pixels with degree ≠ 2 in the road skeleton); edges are traced road segments or healing bridges."},
    {"key": "components", "name": "Connected components", "formula": "number of connected components of G",
     "text": "Isolated nodes count as components."},
    {"key": "lcc_fraction", "name": "Largest component fraction", "formula": "|LCC| / N₀",
     "text": "N₀ is the node count of the baseline (unperturbed) graph, so removed nodes count against the fraction."},
    {"key": "reachable_pair_fraction", "name": "Reachable pair fraction", "formula": "Σ_C |C|(|C|−1)/2  ÷  N₀(N₀−1)/2",
     "text": "Share of the baseline's unordered node pairs that are still connected by some path. Pairs involving a removed node are unreachable."},
    {"key": "avg_path_length", "name": "Average shortest path (reachable pairs)", "formula": "mean d(i,j) over pairs with d < ∞",
     "text": "d is the shortest-path length in pixels along edge lengths. Disconnected pairs are EXCLUDED, never treated as finite. "
             "Fragmentation can therefore lower this value, so read it together with reachable pair fraction."},
    {"key": "efficiency", "name": "Global efficiency (length-weighted)", "formula": "E = 1/(N₀(N₀−1)) · Σ_{i≠j} 1/d(i,j),  1/∞ := 0",
     "text": "Unit px⁻¹. Disconnected pairs contribute 0. Removing nodes or edges can never raise E."},
    {"key": "efficiency_retention", "name": "Resilience score (efficiency retention)", "formula": "ρ = E_after / E_baseline ∈ [0, 1];  degradation = 1 − ρ",
     "text": "The app's normalized resilience metric. It is 1 when the perturbation has no effect and 0 when no pair can reach another."},
    {"key": "pair_connectivity_retention", "name": "Pair connectivity retention", "formula": "reachable_pair_fraction_after / reachable_pair_fraction_baseline",
     "text": "Topology-only counterpart of ρ (ignores path lengths)."},
    {"key": "betweenness", "name": "Betweenness centrality", "formula": "c_B(v) = Σ_{s≠v≠t} σ_st(v)/σ_st, normalized by (n−1)(n−2)/2",
     "text": "Shortest paths weighted by edge length (NetworkX, normalized=True). Scope 'full' scores the whole graph; scope 'lcc' "
             "scores only the largest component (Phase III behaviour). Betweenness is a STRUCTURAL indicator of how many shortest "
             "paths pass through a junction. It is not a probability of real-world failure."},
    {"key": "density", "name": "Density", "formula": "2|E| / (|V|(|V|−1))",
     "text": "Road networks are sparse and near-planar, so density is always small. Compare it only between graphs of similar size."},
    {"key": "legacy_resilience_index", "name": "Phase III 'resilience index' (historical)", "formula": "R = L_baseline / L_perturbed",
     "text": "Shown for reference only. R rises when a removal fragments the graph (fewer, shorter reachable paths) and is 0 for 2-node graphs, "
             "so it is not a degradation measure. Use efficiency retention instead."},
]
