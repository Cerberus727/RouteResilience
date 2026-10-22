"""Region lifecycle: build road networks from the index, cache them, run criticality analysis."""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import networkx as nx
import numpy as np

from ..config import get_settings
from .network import RoadNetwork, split_ways
from .osm_index import Extent, IndexError_, IndexManager, extents, places_in, query_ways, search_places


class RegionError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class AnalysisJob:
    state: str = "idle"  # idle | running | done | error
    progress: float = 0.0
    phase: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    result: dict | None = None


@dataclass
class Region:
    id: str
    bbox: list[float]
    network: RoadNetwork
    coverage: str  # "full" | "partial"
    built_seconds: float
    places: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    analysis: AnalysisJob = field(default_factory=AnalysisJob)
    lock: threading.Lock = field(default_factory=threading.Lock)


_index: IndexManager | None = None
_regions: OrderedDict[str, Region] = OrderedDict()
_lock = threading.Lock()
MAX_REGIONS = 4


def index_manager() -> IndexManager:
    global _index
    if _index is None:
        s = get_settings()
        _index = IndexManager(s.osm_pbf, s.cache_dir / "osm_roads.sqlite", s.cache_dir / "tmp")
    return _index


def reset_for_tests() -> None:
    global _index
    _index = None
    with _lock:
        _regions.clear()


def index_status() -> dict:
    m = index_manager()
    s = get_settings()
    out = {
        "pbf": {"path": str(m.pbf) if m.pbf else None, "exists": bool(m.pbf and m.pbf.is_file()),
                "size_mb": round(m.pbf.stat().st_size / 1e6, 1) if m.pbf and m.pbf.is_file() else None},
        "index_path": str(m.db_path),
        "index_exists": m.available(),
        "extents": [],
        "default_extent": Extent.parse(s.osm_extent).as_list(),
        "default_region": Extent.parse(s.default_region).as_list(),
        "job": m.job.snapshot(),
    }
    if m.available():
        try:
            con = m.connect()
            try:
                out["extents"] = extents(con)
            finally:
                con.close()
        except IndexError_ as exc:
            out["index_error"] = str(exc)
    return out


def coverage_for(bbox: Extent) -> str | None:
    """'full' if one indexed extent contains bbox, 'partial' if any overlaps, None otherwise."""
    st = index_status()
    exts = [Extent(*e["bbox"]) for e in st["extents"]]
    if any(e.contains(bbox) for e in exts):
        return "full"
    if any(e.intersects(bbox.min_lon, bbox.min_lat, bbox.max_lon, bbox.max_lat) for e in exts):
        return "partial"
    return None


def region_id_for(bbox: Extent) -> str:
    m = index_manager()
    stamp = f"{m.db_path.stat().st_mtime_ns}" if m.available() else "none"
    raw = ",".join(f"{v:.5f}" for v in bbox.as_list()) + "|" + stamp
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def load_region(bbox: Extent) -> Region:
    s = get_settings()
    if bbox.max_lon - bbox.min_lon > s.max_region_span_deg or bbox.max_lat - bbox.min_lat > s.max_region_span_deg:
        raise RegionError(413, "region_too_large", f"Region spans more than {s.max_region_span_deg}° — zoom in and load a smaller area.")
    m = index_manager()
    if not m.available():
        raise RegionError(409, "index_missing", "The OSM road index has not been built yet. Build it from the Region panel (one-time scan of the .pbf).")
    cov = coverage_for(bbox)
    if cov is None:
        raise RegionError(409, "not_indexed", "This area is outside every indexed extent. Index it first (Region panel → Index this view).")
    rid = region_id_for(bbox)
    with _lock:
        if rid in _regions:
            _regions.move_to_end(rid)
            return _regions[rid]
    t0 = time.time()
    con = m.connect()
    try:
        ways = query_ways(con, bbox)
        places = places_in(con, bbox)
    finally:
        con.close()
    if not ways:
        raise RegionError(404, "no_roads", "No drivable roads were found in this area.")
    segments = split_ways(ways)
    if len(segments) > s.max_region_segments:
        raise RegionError(413, "region_too_large", f"{len(segments):,} road segments exceed the limit of {s.max_region_segments:,}. Load a smaller area.")
    net = RoadNetwork(region_id=rid, bbox=bbox.as_list(), segments=segments)
    net.baseline()
    region = Region(id=rid, bbox=bbox.as_list(), network=net, coverage=cov, built_seconds=time.time() - t0, places=places)
    with _lock:
        _regions[rid] = region
        while len(_regions) > MAX_REGIONS:
            _regions.popitem(last=False)
    return region


def get_region(rid: str) -> Region:
    with _lock:
        r = _regions.get(rid)
    if r is None:
        raise RegionError(404, "region_not_loaded", f"Region '{rid}' is not loaded (it may have been evicted). Reload the area.")
    return r


def roads_geojson(region: Region) -> dict:
    feats = []
    for s in region.network.segments:
        t = s.tags
        feats.append({
            "type": "Feature",
            "id": region.network.seg_index[s.id],  # numeric id for MapLibre feature-state
            "geometry": {"type": "LineString", "coordinates": [[round(x, 7), round(y, 7)] for x, y in s.coords]},
            "properties": {"sid": s.id, "way": s.way_id, "hw": s.highway, "name": t.get("name") or t.get("ref") or "",
                           "ow": s.oneway, "len": round(s.length_m, 1)},
        })
    return {"type": "FeatureCollection", "features": feats}


def nodes_geojson(region: Region) -> dict:
    net = region.network
    deg = np.bincount(np.r_[[net.node_pos[s.u] for s in net.segments], [net.node_pos[s.v] for s in net.segments]], minlength=net.n)
    feats = []
    for i in np.flatnonzero(deg >= 3):
        feats.append({"type": "Feature", "id": int(i), "geometry": {"type": "Point", "coordinates": [round(float(c), 7) for c in net.node_lonlat[i]]},
                      "properties": {"nid": int(net.node_ids[i]), "deg": int(deg[i])}})
    return {"type": "FeatureCollection", "features": feats}


def undirected_structure(net: RoadNetwork) -> dict:
    """Articulation points and bridges of the undirected road graph. A bridge between two
    nodes joined by parallel segments is not a bridge, so pair multiplicity is checked."""
    G = nx.Graph()
    mult: dict[tuple[int, int], list[str]] = {}
    for s in net.segments:
        a, b = sorted((net.node_pos[s.u], net.node_pos[s.v]))
        mult.setdefault((a, b), []).append(s.id)
        G.add_edge(a, b)
    bridges = [mult[tuple(sorted(e))][0] for e in nx.bridges(G) if len(mult[tuple(sorted(e))]) == 1]
    arts = list(nx.articulation_points(G))
    return {"bridges": bridges, "articulation_nodes": [int(net.node_ids[i]) for i in arts], "articulation_idx": arts}


def start_analysis(region: Region) -> AnalysisJob:
    with region.lock:
        if region.analysis.state == "running":
            return region.analysis
        if region.analysis.state == "done":
            return region.analysis
        job = AnalysisJob(state="running", started_at=time.time(), phase="structure")
        region.analysis = job

    def run():
        net = region.network
        try:
            job.phase = "articulation points and bridges"
            struct = undirected_structure(net)
            job.progress = 0.05
            k = get_settings().betweenness_sources
            job.phase = f"sampled betweenness ({k} origins)"

            def prog(i, total):
                job.progress = 0.05 + 0.75 * i / total
            seg_load, node_load, paths = net.sampled_betweenness(k, prog)
            share = seg_load / paths if paths else seg_load
            node_share = node_load / paths if paths else node_load
            order = np.argsort(-share)
            top = [int(i) for i in order[:40] if share[i] > 0]
            job.phase = "single-failure impact of the top-ranked roads"
            impacts = {}
            for j, si in enumerate(top[:15]):
                ev = net.evaluate([net.segments[si].id], None, None, affected_cap=0)
                impacts[net.segments[si].id] = {
                    "cut_off_nodes": ev["network"]["cut_off_nodes"],
                    "affected_segments": ev["network"]["affected_segments"],
                    "strong_components": ev["network"]["strong_components"],
                    "efficiency_retention": ev["sampled"]["efficiency_retention"] if ev["sampled"] else None,
                    "reachable_fraction": ev["sampled"]["reachable_fraction"] if ev["sampled"] else None,
                }
                job.progress = 0.8 + 0.2 * (j + 1) / max(1, min(15, len(top)))
            bridge_set = set(struct["bridges"])
            node_order = np.argsort(-node_share)
            top_nodes = [int(i) for i in node_order[:25] if node_share[i] > 0]
            art_set = set(struct["articulation_idx"])
            job.result = {
                "method": {
                    "betweenness": f"Share of shortest (distance) paths from {k} randomly sampled origins (seed 11) to all reachable nodes "
                                   "that traverse each segment. Sampled estimate, directed graph, one-way rules respected.",
                    "paths_counted": int(paths),
                    "bridges": "Undirected bridge: removing the segment disconnects the undirected road graph (most are dead-end access roads).",
                    "articulation": "Undirected articulation point: removing the intersection disconnects the undirected road graph.",
                    "impact": "Single-failure impact recomputed on the full regional graph for each listed segment.",
                },
                "roads": [{
                    "rank": r + 1, "sid": net.segments[i].id, "name": net.segments[i].tags.get("name") or net.segments[i].tags.get("ref") or "",
                    "highway": net.segments[i].highway, "length_m": net.segments[i].length_m, "betweenness_share": float(share[i]),
                    "is_bridge": net.segments[i].id in bridge_set, "impact": impacts.get(net.segments[i].id),
                    "midpoint": list(net.segments[i].coords[len(net.segments[i].coords) // 2]),
                } for r, i in enumerate(top)],
                "intersections": [{
                    "rank": r + 1, "nid": int(net.node_ids[i]), "lonlat": net.node_lonlat[i].tolist(),
                    "betweenness_share": float(node_share[i]), "is_articulation": i in art_set,
                } for r, i in enumerate(top_nodes)],
                "segment_scores": {net.segments[i].id: round(float(share[i]), 6) for i in np.flatnonzero(share > 0)},
                "bridge_count": len(struct["bridges"]),
                "articulation_count": len(struct["articulation_nodes"]),
                "bridges": struct["bridges"],
            }
            job.state = "done"
            job.phase = "complete"
            job.progress = 1.0
        except Exception as exc:
            job.state = "error"
            job.error = f"{type(exc).__name__}: {exc}"
        finally:
            job.finished_at = time.time()

    threading.Thread(target=run, name=f"analysis-{region.id}", daemon=True).start()
    return job


def search(q: str, region: Region | None, limit: int = 10) -> list[dict]:
    q = q.strip()
    out: list[dict] = []
    if region is not None:
        seen: dict[str, dict] = {}
        ql = q.lower()
        for s in region.network.segments:
            name = s.tags.get("name") or ""
            if name and ql in name.lower():
                e = seen.setdefault(name, {"name": name, "kind": f"road ({s.highway})", "segments": [], "pts": [], "source": "loaded region"})
                e["segments"].append(s.id)
                e["pts"].extend(s.coords)
        for e in sorted(seen.values(), key=lambda e: (not e["name"].lower().startswith(ql), len(e["name"])))[:limit]:
            xs, ys = [p[0] for p in e["pts"]], [p[1] for p in e["pts"]]
            out.append({"name": e["name"], "kind": e["kind"], "lon": float(np.mean(xs)), "lat": float(np.mean(ys)),
                        "bbox": [min(xs), min(ys), max(xs), max(ys)], "segment_ids": e["segments"][:200], "source": e["source"]})
    m = index_manager()
    if m.available():
        con = m.connect()
        try:
            out += search_places(con, q, limit)
        finally:
            con.close()
    return out[: limit * 2]
