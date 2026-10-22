"""Builds API payloads from loaded graphs (shared by routes, exports and reports)."""

from __future__ import annotations

from collections import Counter

from .. import analysis
from ..config import get_settings
from ..graph_io import Variant, schematic_layout, simplify_polyline
from ..registry import get_registry
from . import graphs as graph_service
from . import masks as mask_service
from . import notebooks, reviews
from .graphs import LoadedGraph
from .models import KNOWN_MODELS

MAX_POINTS_PER_GRAPH = 60_000


def source_mask(set_id: str) -> dict:
    """Which mask set a graph set was built from, and how sure we are."""
    reg = get_registry()
    prov = notebooks.graph_set_provenance(set_id)
    if prov["verified"] and prov["source_mask_set"] in reg.mask_sets:
        return {"mask_set": prov["source_mask_set"], "verified": True, "note": prov["note"]}
    spec = KNOWN_MODELS.get(set_id)
    if spec and spec["mask_set"] in reg.mask_sets:
        return {
            "mask_set": spec["mask_set"], "verified": False,
            "note": f"Assumed from the Phase I mapping {set_id} → masks_{spec['mask_set']}; "
                    "the run that wrote this graph set is not logged in the notebooks.",
        }
    if set_id in reg.mask_sets:
        return {"mask_set": set_id, "verified": False, "note": "Assumed from the folder name; not verified against a notebook log."}
    return {"mask_set": None, "verified": False, "note": "No source mask set could be identified."}


def underlay_for(lg: LoadedGraph) -> dict | None:
    src = source_mask(lg.set_id)
    mset = src["mask_set"]
    path = get_registry().mask_sets.get(mset, {}).get(lg.image_id) if mset else None
    if not path:
        return None
    size = mask_service.mask_size(path)
    if not size:
        return None
    return {
        "kind": "mask",
        "mask_set": mset,
        "url": f"/api/masks/{mset}/{lg.image_id}.png",
        "width": size[0],
        "height": size[1],
        "verified": src["verified"],
        "label": f"Predicted road mask (masks_{mset}). Pixel coordinates; no georeferencing available.",
    }


def positions(lg: LoadedGraph) -> tuple[dict[str, tuple[float, float]], str]:
    if lg.doc.has_positions:
        return {n.id: (float(n.x), float(n.y)) for n in lg.doc.nodes}, "pixel"
    return schematic_layout(lg.doc), "schematic"


def node_rows(lg: LoadedGraph, variant: Variant, scope: str = "full") -> list[dict]:
    G = lg.graph(variant)
    bc = graph_service.betweenness(lg, variant, scope)
    rank = {n: i + 1 for i, n in enumerate(analysis.rank_nodes(G, bc))}
    mem, _ = graph_service.membership(lg, variant)
    pos, _ = positions(lg)
    return [
        {"id": n, "x": pos[n][0], "y": pos[n][1], "degree": G.degree(n), "component": mem[n],
         "betweenness": bc.get(n, 0.0), "rank": rank[n]}
        for n in G.nodes
    ]


def edge_rows(lg: LoadedGraph, variant: Variant, include_coords: bool, simplify: float) -> list[dict]:
    review_map = reviews.get_reviews(lg.graph_id) if lg.doc.healing_provenance != "unavailable" else {}
    rows, budget = [], MAX_POINTS_PER_GRAPH
    for e in lg.doc.edges:
        if variant == "original" and e.healed:
            continue
        row = {"id": e.id, "source": e.source, "target": e.target, "length": e.length,
               "length_source": e.length_source, "healed": e.healed,
               "review": (review_map.get(e.id) or {}).get("decision")}
        if include_coords and e.coords:
            pts = simplify_polyline(e.coords, simplify)
            if len(pts) > budget:  # hard cap on payload; endpoints still present via nodes
                pts = [pts[0], pts[-1]]
            budget -= len(pts)
            row["coords"] = [(round(x, 1), round(y, 1)) for x, y in pts]
        rows.append(row)
    return rows


def frame_for(lg: LoadedGraph, underlay: dict | None) -> dict:
    if underlay:
        return {"width": underlay["width"], "height": underlay["height"], "source": "mask"}
    pos, _ = positions(lg)
    xs = [p[0] for p in pos.values()] or [0]
    ys = [p[1] for p in pos.values()] or [0]
    return {"width": max(xs) + 20, "height": max(ys) + 20, "source": "bounding_box"}


def graph_detail(lg: LoadedGraph, variant: Variant, include_coords: bool = True, simplify: float = 1.0) -> dict:
    G = lg.graph(variant)
    metrics = graph_service.baseline_metrics(lg, variant)
    _, sizes = graph_service.membership(lg, variant)
    degs = Counter(dict(G.degree()).values())
    max_deg = max(degs) if degs else 0
    underlay = underlay_for(lg) if lg.doc.has_positions else None
    _, layout = positions(lg)
    src = source_mask(lg.set_id)
    return {
        "graph_id": lg.graph_id,
        "set_id": lg.set_id,
        "image_id": lg.image_id,
        "variant": variant,
        "schema_name": lg.doc.schema,
        "model_tag": lg.doc.model_tag,
        "frame": frame_for(lg, underlay),
        "layout": layout,
        "healing_provenance": lg.doc.healing_provenance,
        "coords_order": lg.doc.coords_order,
        "nodes": node_rows(lg, variant),
        "edges": edge_rows(lg, variant, include_coords, simplify),
        "metrics": metrics.to_dict(),
        "component_sizes": sizes,
        "degree_histogram": [degs.get(d, 0) for d in range(max_deg + 1)],
        "file_stats": lg.doc.file_stats,
        "provenance": {
            "file": f"graphs_{lg.set_id}/{lg.path.name}",
            "source_mask_set": src["mask_set"],
            "source_verified": src["verified"],
            "note": src["note"],
            "computed_by": "app (NetworkX, recomputed on request)",
        },
        "warnings": list(lg.doc.warnings),
        "underlay": underlay,
    }


def limits_check(n_removals: int, steps: int | None = None) -> None:
    s = get_settings()
    if n_removals > s.max_removals:
        raise analysis.InvalidTargetError(f"At most {s.max_removals} removals per request (got {n_removals}).")
    if steps is not None and steps > s.max_sequential_steps:
        raise analysis.InvalidTargetError(f"At most {s.max_sequential_steps} sequential steps per request (got {steps}).")
