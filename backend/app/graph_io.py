"""Graph schema adapter.

Turns Phase II graph JSON (and NetworkX node-link JSON) into a validated,
immutable `GraphDoc`. Node and edge IDs are kept exactly as stored so that
results always line up with the exported analysis files.

Coordinate convention in the output: every point is `(x, y)` in image-pixel space
(x = column, y = row). Phase II stores edge polylines as `[row, col]`; the adapter
detects the order from the endpoint nodes and converts it.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import networkx as nx

Point = tuple[float, float]
Variant = Literal["healed", "original"]


class GraphLoadError(Exception):
    """Raised when a graph file cannot be turned into a usable graph."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class NodeRec:
    id: str
    x: float | None
    y: float | None
    file_degree: int | None
    extra: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)


@dataclass(frozen=True)
class EdgeRec:
    id: str
    source: str
    target: str
    length: float
    length_source: str  # "length" | "weight" | "coords" | "euclidean" | "default"
    healed: bool | None  # None = provenance not recorded
    coords: tuple[Point, ...]
    extra: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)


@dataclass(frozen=True)
class GraphDoc:
    image_id: str
    model_tag: str | None
    schema: str  # "phase2" | "node_link"
    nodes: tuple[NodeRec, ...]
    edges: tuple[EdgeRec, ...]
    file_stats: dict[str, Any] | None
    healing_provenance: str  # "recorded" | "partial" | "unavailable"
    coords_order: str  # "row_col" | "xy" | "none" | "ambiguous"
    has_positions: bool
    warnings: tuple[str, ...]

    @property
    def node_index(self) -> dict[str, NodeRec]:
        return {n.id: n for n in self.nodes}

    @property
    def edge_index(self) -> dict[str, EdgeRec]:
        return {e.id: e for e in self.edges}


# --------------------------------------------------------------------------
def _num(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _detect_coords_order(raw_edges: list[dict], pos: dict[str, tuple[float | None, float | None]]) -> str:
    """Vote on [row, col] vs [x, y] using polyline endpoints vs node positions."""
    row_col = xy = 0
    for e in raw_edges:
        coords = e.get("coords") or e.get("pts")
        if not isinstance(coords, list) or len(coords) < 1:
            continue
        ends = []
        for key in ("source", "target"):
            p = pos.get(str(e.get(key)))
            if p and p[0] is not None and p[1] is not None:
                ends.append(p)
        if not ends:
            continue
        for pt in (coords[0], coords[-1]):
            if not (isinstance(pt, (list, tuple)) and len(pt) >= 2):
                continue
            a, b = _num(pt[0]), _num(pt[1])
            for x, y in ends:
                if (a, b) == (y, x) and (a, b) != (x, y):
                    row_col += 1
                elif (a, b) == (x, y) and (a, b) != (y, x):
                    xy += 1
    if row_col == 0 and xy == 0:
        return "none" if not any((e.get("coords") or e.get("pts")) for e in raw_edges) else "ambiguous"
    if row_col and xy:
        return "row_col" if row_col >= 4 * xy else ("xy" if xy >= 4 * row_col else "ambiguous")
    return "row_col" if row_col else "xy"


def _polyline_length(coords: tuple[Point, ...]) -> float:
    return sum(math.dist(coords[i], coords[i + 1]) for i in range(len(coords) - 1))


def parse_graph_dict(data: Any, fallback_image_id: str = "") -> GraphDoc:
    if not isinstance(data, dict):
        raise GraphLoadError("invalid_schema", "Graph file must contain a JSON object.")
    raw_nodes = data.get("nodes")
    edge_key = "edges" if "edges" in data else ("links" if "links" in data else None)
    if not isinstance(raw_nodes, list) or edge_key is None or not isinstance(data.get(edge_key), list):
        raise GraphLoadError("invalid_schema", "Graph JSON needs a 'nodes' list and an 'edges' (or 'links') list.")
    raw_edges: list[dict] = data[edge_key]
    schema = "phase2" if edge_key == "edges" and "stats" in data else "node_link" if edge_key == "links" else "phase2"
    warnings: list[str] = []

    nodes: list[NodeRec] = []
    seen: set[str] = set()
    for i, n in enumerate(raw_nodes):
        if not isinstance(n, dict) or "id" not in n:
            raise GraphLoadError("invalid_schema", f"Node #{i} has no 'id'.")
        nid = str(n["id"])
        if nid in seen:
            raise GraphLoadError("invalid_schema", f"Duplicate node id '{nid}'.")
        seen.add(nid)
        x, y = _num(n.get("x")), _num(n.get("y"))
        if (x is None or y is None) and isinstance(n.get("pixel"), (list, tuple)) and len(n["pixel"]) >= 2:
            y, x = _num(n["pixel"][0]), _num(n["pixel"][1])  # Phase II internal (row, col)
        deg = n.get("degree")
        extra = {k: v for k, v in n.items() if k not in {"id", "x", "y", "degree", "pixel"}}
        nodes.append(NodeRec(nid, x, y, int(deg) if isinstance(deg, (int, float)) else None, extra))

    has_positions = bool(nodes) and all(n.x is not None and n.y is not None for n in nodes)
    if nodes and not has_positions:
        warnings.append("Some nodes have no pixel position; a schematic layout is used instead.")
    pos = {n.id: (n.x, n.y) for n in nodes}
    order = _detect_coords_order(raw_edges, pos)
    if order == "ambiguous":
        warnings.append("Edge polyline coordinate order could not be determined; polylines are drawn as stored ([x, y]).")

    edges: list[EdgeRec] = []
    seen_pairs: dict[frozenset, str] = {}
    seen_ids: set[str] = set()
    healed_known = 0
    for i, e in enumerate(raw_edges):
        if not isinstance(e, dict) or "source" not in e or "target" not in e:
            raise GraphLoadError("invalid_schema", f"Edge #{i} needs 'source' and 'target'.")
        s, t = str(e["source"]), str(e["target"])
        eid = str(e.get("id", f"e{s}_{t}"))
        if s not in seen or t not in seen:
            warnings.append(f"Edge {eid} references a missing node and was skipped.")
            continue
        if s == t:
            warnings.append(f"Self-loop {eid} was skipped.")
            continue
        pair = frozenset((s, t))
        if pair in seen_pairs:
            warnings.append(f"Parallel edge {eid} duplicates {seen_pairs[pair]} and was skipped (simple-graph analysis).")
            continue
        if eid in seen_ids:
            new_id = f"{eid}#{i}"
            warnings.append(f"Duplicate edge id {eid}; renamed to {new_id}.")
            eid = new_id
        seen_ids.add(eid)
        seen_pairs[pair] = eid

        raw_coords = e.get("coords") if isinstance(e.get("coords"), list) else (e.get("pts") if isinstance(e.get("pts"), list) else [])
        pts: list[Point] = []
        for pt in raw_coords:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                a, b = _num(pt[0]), _num(pt[1])
                if a is not None and b is not None:
                    pts.append((b, a) if order == "row_col" else (a, b))
        coords = tuple(pts)

        length, src = None, "default"
        for key in ("length", "weight"):
            v = _num(e.get(key))
            if v is not None and v > 0:
                length, src = v, key
                break
        if length is None:
            if len(coords) >= 2 and _polyline_length(coords) > 0:
                length, src = _polyline_length(coords), "coords"
            elif pos[s][0] is not None and pos[t][0] is not None and math.dist(pos[s], pos[t]) > 0:  # type: ignore[arg-type]
                length, src = math.dist(pos[s], pos[t]), "euclidean"  # type: ignore[arg-type]
            else:
                length, src = 1.0, "default"
            warnings.append(f"Edge {eid} has no positive length/weight; using {src} length {length:.2f}.")

        healed_raw = e.get("healed")
        healed = bool(healed_raw) if isinstance(healed_raw, (bool, int)) else None
        if healed is not None:
            healed_known += 1
        extra = {k: v for k, v in e.items() if k not in {"id", "source", "target", "length", "weight", "healed", "coords", "pts"}}
        edges.append(EdgeRec(eid, s, t, float(length), src, healed, coords, extra))

    if not edges:
        provenance = "unavailable"
    elif healed_known == len(edges):
        provenance = "recorded"
    elif healed_known == 0:
        provenance = "unavailable"
    else:
        provenance = "partial"
        warnings.append(f"Healing flag recorded on only {healed_known}/{len(edges)} edges.")

    image_id = str(data.get("image_id") or fallback_image_id)
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else None
    model = data.get("model")
    return GraphDoc(
        image_id=image_id,
        model_tag=str(model) if model is not None else None,
        schema=schema,
        nodes=tuple(nodes),
        edges=tuple(edges),
        file_stats=stats,
        healing_provenance=provenance,
        coords_order=order,
        has_positions=has_positions,
        warnings=tuple(warnings),
    )


def load_graph_file(path: Path, fallback_image_id: str = "") -> GraphDoc:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as exc:
        raise GraphLoadError("not_found", f"Graph file not found: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise GraphLoadError("invalid_json", f"{path.name} is not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}") from exc
    except UnicodeDecodeError as exc:
        raise GraphLoadError("invalid_json", f"{path.name} is not UTF-8 text.") from exc
    return parse_graph_dict(data, fallback_image_id)


def to_networkx(doc: GraphDoc, variant: Variant = "healed") -> nx.Graph:
    """Build a *frozen* NetworkX graph. Mutating it raises `NetworkXError`, so cached
    graphs cannot be changed by simulations, which must work on `G.copy()`.

    variant="original" drops edges flagged healed=True (the pre-healing graph).
    """
    G = nx.Graph(image_id=doc.image_id, variant=variant)
    for n in doc.nodes:
        G.add_node(n.id, x=n.x, y=n.y)
    for e in doc.edges:
        if variant == "original" and e.healed:
            continue
        G.add_edge(e.source, e.target, id=e.id, length=e.length, healed=e.healed)
    return nx.freeze(G)


def schematic_layout(doc: GraphDoc) -> dict[str, Point]:
    """Deterministic layout for graphs without pixel positions (explicitly labeled in the UI)."""
    G = nx.Graph()
    G.add_nodes_from(n.id for n in doc.nodes)
    G.add_edges_from((e.source, e.target) for e in doc.edges)
    layout = nx.spring_layout(G, seed=0) if G.number_of_nodes() else {}
    return {k: (float(v[0] * 450 + 512), float(v[1] * 450 + 512)) for k, v in layout.items()}


def simplify_polyline(points: tuple[Point, ...], tolerance: float) -> list[Point]:
    """Ramer–Douglas–Peucker simplification (iterative). Endpoints always kept."""
    n = len(points)
    if tolerance <= 0 or n <= 2:
        return list(points)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        lo, hi = stack.pop()
        (x1, y1), (x2, y2) = points[lo], points[hi]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy)
        best, idx = -1.0, -1
        for i in range(lo + 1, hi):
            px, py = points[i]
            d = abs(dy * px - dx * py + x2 * y1 - y2 * x1) / norm if norm else math.hypot(px - x1, py - y1)
            if d > best:
                best, idx = d, i
        if best > tolerance and idx > 0:
            keep[idx] = True
            stack.append((lo, idx))
            stack.append((idx, hi))
    return [p for p, k in zip(points, keep) if k]
