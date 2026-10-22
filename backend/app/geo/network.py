"""Road graph for a region, routing, failure simulation and resilience metrics.

Graph model
-----------
* OSM ways are split into **segments** at every node shared by two or more ways
  (junctions), at way endpoints, and where a way revisits a node. Segment ID =
  ``"<way_id>:<k>"`` (k = 0-based position in the way), which is stable for the same
  OSM data, so map features and graph edges share the same identifiers.
* Graph nodes are segment endpoints (intersections, dead ends).
* Directed edges: a two-way segment gives u→v and v→u, a one-way segment only its
  allowed direction (``oneway=yes/-1``, roundabouts, motorways / motorway links per OSM
  conventions). Parallel segments between the same nodes stay distinct segments.
* Edge weight = great-circle length of the segment polyline in metres. No travel
  times are available, so routing is **shortest distance**, not fastest time.

Routing and metrics run on a SciPy CSR matrix built from the *active* (non-failed)
directed edges. Parallel edges are reduced to their **minimum** length before the
matrix is built (SciPy would otherwise sum duplicates). The segment that realizes
each hop is recorded so routes can be mapped back to segment IDs.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree

from .osm_index import WayRecord

EARTH_R = 6371008.8
MIN_EDGE_M = 0.01  # guards zero-length segments (duplicate coordinates)


def haversine(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def polyline_length(coords: list[tuple[float, float]]) -> float:
    return sum(haversine(*coords[i], *coords[i + 1]) for i in range(len(coords) - 1))


def oneway_direction(highway: str, tags: dict) -> int:
    """+1 = forward only, -1 = backward only, 0 = both directions."""
    ow = str(tags.get("oneway", "")).lower()
    if ow in ("yes", "true", "1"):
        return 1
    if ow in ("-1", "reverse"):
        return -1
    if ow in ("no", "false", "0", "reversible", "alternating"):
        return 0  # reversible/alternating: direction varies over time; treated as two-way
    if tags.get("junction") in ("roundabout", "circular"):
        return 1
    if highway in ("motorway", "motorway_link"):
        return 1
    return 0


@dataclass
class Segment:
    id: str
    way_id: int
    k: int
    u: int  # OSM node id
    v: int
    coords: list[tuple[float, float]]
    length_m: float
    highway: str
    oneway: int
    tags: dict


def split_ways(ways: list[WayRecord]) -> list[Segment]:
    shared = Counter()
    for w in ways:
        shared.update(set(w.node_ids))
    segments: list[Segment] = []
    for w in ways:
        ids = w.node_ids
        n = len(ids)
        seen: Counter = Counter(ids)
        cut = [0] + [i for i in range(1, n - 1) if shared[ids[i]] >= 2 or seen[ids[i]] >= 2] + [n - 1]
        # A piece that starts and ends on the same node (closed loop) is split in the middle.
        pieces: list[tuple[int, int]] = []
        for a, b in zip(cut, cut[1:]):
            if b <= a:
                continue
            if ids[a] == ids[b] and b - a >= 2:
                m = (a + b) // 2
                pieces += [(a, m), (m, b)]
            elif ids[a] != ids[b]:
                pieces.append((a, b))
        ow = oneway_direction(w.highway, w.tags)
        for k, (a, b) in enumerate(pieces):
            coords = w.coords[a: b + 1]
            segments.append(Segment(
                id=f"{w.id}:{k}", way_id=w.id, k=k, u=ids[a], v=ids[b], coords=coords,
                length_m=max(MIN_EDGE_M, polyline_length(coords)), highway=w.highway, oneway=ow, tags=w.tags,
            ))
    return segments


class UnknownSegmentError(Exception):
    pass


@dataclass
class RoadNetwork:
    region_id: str
    bbox: list[float]
    segments: list[Segment]
    seg_index: dict[str, int] = field(init=False)
    node_ids: np.ndarray = field(init=False)  # index -> OSM node id
    node_lonlat: np.ndarray = field(init=False)  # (n, 2)
    node_pos: dict[int, int] = field(init=False)  # OSM node id -> index
    e_src: np.ndarray = field(init=False)
    e_dst: np.ndarray = field(init=False)
    e_len: np.ndarray = field(init=False)
    e_seg: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.seg_index = {s.id: i for i, s in enumerate(self.segments)}
        coords: dict[int, tuple[float, float]] = {}
        for s in self.segments:
            coords.setdefault(s.u, s.coords[0])
            coords.setdefault(s.v, s.coords[-1])
        self.node_ids = np.array(sorted(coords), dtype=np.int64)
        self.node_pos = {int(n): i for i, n in enumerate(self.node_ids)}
        self.node_lonlat = np.array([coords[int(n)] for n in self.node_ids], dtype=np.float64).reshape(-1, 2)
        src, dst, ln, sg = [], [], [], []
        for i, s in enumerate(self.segments):
            u, v = self.node_pos[s.u], self.node_pos[s.v]
            if s.oneway in (0, 1):
                src.append(u); dst.append(v); ln.append(s.length_m); sg.append(i)
            if s.oneway in (0, -1):
                src.append(v); dst.append(u); ln.append(s.length_m); sg.append(i)
        self.e_src = np.array(src, dtype=np.int64)
        self.e_dst = np.array(dst, dtype=np.int64)
        self.e_len = np.array(ln, dtype=np.float64)
        self.e_seg = np.array(sg, dtype=np.int64)
        lat0 = math.radians(float(self.node_lonlat[:, 1].mean())) if len(self.node_lonlat) else 0.0
        self._kx = 111_320.0 * math.cos(lat0)
        self._ky = 110_540.0
        self._kdtree = cKDTree(np.c_[self.node_lonlat[:, 0] * self._kx, self.node_lonlat[:, 1] * self._ky]) if len(self.node_lonlat) else None
        self._baseline: dict | None = None

    # ------------------------------------------------------------------ basics
    @property
    def n(self) -> int:
        return len(self.node_ids)

    def check_ids(self, segment_ids: list[str]) -> list[int]:
        unknown = [s for s in segment_ids if s not in self.seg_index]
        if unknown:
            raise UnknownSegmentError(f"Unknown segment id(s) for this region: {', '.join(unknown[:10])}")
        return [self.seg_index[s] for s in segment_ids]

    def active_edges(self, failed: set[int]) -> np.ndarray:
        if not failed:
            return np.ones(len(self.e_seg), dtype=bool)
        return ~np.isin(self.e_seg, np.fromiter(failed, dtype=np.int64))

    def csr(self, active: np.ndarray) -> tuple[csr_matrix, np.ndarray, np.ndarray]:
        """CSR over active edges with parallel edges reduced to the shortest one.
        Returns (matrix, sorted pair keys, segment index realizing each pair)."""
        s, d, ln, sg = self.e_src[active], self.e_dst[active], self.e_len[active], self.e_seg[active]
        order = np.lexsort((ln, d, s))
        s, d, ln, sg = s[order], d[order], ln[order], sg[order]
        first = np.ones(len(s), dtype=bool)
        if len(s):
            first[1:] = (s[1:] != s[:-1]) | (d[1:] != d[:-1])
        s, d, ln, sg = s[first], d[first], ln[first], sg[first]
        mat = csr_matrix((ln, (s, d)), shape=(self.n, self.n))
        keys = s * self.n + d  # sorted because of lexsort on (s, d)
        return mat, keys, sg

    def snap(self, lon: float, lat: float, restrict: np.ndarray | None = None) -> tuple[int, float]:
        """Nearest graph node (optionally restricted to a boolean node mask). Returns (index, metres)."""
        if self._kdtree is None:
            raise UnknownSegmentError("Region has no road nodes.")
        q = (lon * self._kx, lat * self._ky)
        k = 1 if restrict is None else min(64, self.n)
        dists, idx = self._kdtree.query(q, k=k)
        dists, idx = np.atleast_1d(dists), np.atleast_1d(idx)
        for dd, ii in zip(dists, idx):
            if restrict is None or restrict[ii]:
                return int(ii), float(haversine(lon, lat, *self.node_lonlat[ii]))
        if restrict is not None:  # fall back to brute force over allowed nodes
            cand = np.flatnonzero(restrict)
            xy = np.c_[self.node_lonlat[cand, 0] * self._kx, self.node_lonlat[cand, 1] * self._ky]
            j = int(np.argmin(((xy - q) ** 2).sum(1)))
            ii = int(cand[j])
            return ii, float(haversine(lon, lat, *self.node_lonlat[ii]))
        raise UnknownSegmentError("No snappable node.")

    # --------------------------------------------------------------- structure
    def components(self, mat: csr_matrix) -> dict:
        nw, wl = connected_components(mat, directed=True, connection="weak")
        ns, sl = connected_components(mat, directed=True, connection="strong")
        return {"weak_n": int(nw), "weak_labels": wl, "strong_n": int(ns), "strong_labels": sl}

    def baseline(self) -> dict:
        """Cached intact-network state used as the reference for every comparison."""
        if self._baseline is None:
            mat, keys, sg = self.csr(self.active_edges(set()))
            comp = self.components(mat)
            sl = comp["strong_labels"]
            main_label = int(np.bincount(sl).argmax()) if self.n else 0
            main_mask = sl == main_label
            rng = np.random.default_rng(7)
            main_idx = np.flatnonzero(main_mask)
            k = int(min(24, len(main_idx)))
            t = int(min(400, len(main_idx)))
            sources = np.sort(rng.choice(main_idx, size=k, replace=False)) if k else np.array([], dtype=np.int64)
            targets = np.sort(rng.choice(main_idx, size=t, replace=False)) if t else np.array([], dtype=np.int64)
            dist = dijkstra(mat, directed=True, indices=sources)[:, targets] if k else np.zeros((0, 0))
            self._baseline = {"mat": mat, "keys": keys, "seg": sg, "comp": comp, "main_mask": main_mask,
                              "sources": sources, "targets": targets, "dist": dist}
        return self._baseline

    def summary(self) -> dict:
        b = self.baseline()
        comp = b["comp"]
        undirected_deg = np.bincount(np.r_[[self.node_pos[s.u] for s in self.segments], [self.node_pos[s.v] for s in self.segments]], minlength=self.n)
        classes = Counter(s.highway for s in self.segments)
        return {
            "segments": len(self.segments),
            "nodes": self.n,
            "directed_edges": int(len(self.e_seg)),
            "total_km": float(sum(s.length_m for s in self.segments) / 1000),
            "oneway_segments": sum(1 for s in self.segments if s.oneway != 0),
            "weak_components": comp["weak_n"],
            "strong_components": comp["strong_n"],
            "main_scc_nodes": int(b["main_mask"].sum()),
            "main_scc_share": float(b["main_mask"].mean()) if self.n else None,
            "intersections": int((undirected_deg >= 3).sum()),
            "dead_ends": int((undirected_deg == 1).sum()),
            "highway_classes": dict(classes.most_common()),
        }

    # ---------------------------------------------------------------- routing
    def _path(self, pred: np.ndarray, keys: np.ndarray, sg: np.ndarray, o: int, d: int) -> list[int] | None:
        if o == d:
            return []
        if pred[d] < 0:
            return None
        nodes = [d]
        while nodes[-1] != o:
            p = int(pred[nodes[-1]])
            if p < 0:
                return None
            nodes.append(p)
        nodes.reverse()
        pair = np.array(nodes[:-1], dtype=np.int64) * self.n + np.array(nodes[1:], dtype=np.int64)
        pos = np.searchsorted(keys, pair)
        return [int(x) for x in sg[pos]]

    def route_geometry(self, seg_seq: list[int], o: int) -> list[list[float]]:
        """Concatenate segment polylines in travel direction."""
        coords: list[list[float]] = []
        cur = int(self.node_ids[o])
        for si in seg_seq:
            s = self.segments[si]
            pts = s.coords if s.u == cur else list(reversed(s.coords))
            cur = s.v if s.u == cur else s.u
            if coords:
                pts = pts[1:]
            coords.extend([[round(x, 7), round(y, 7)] for x, y in pts])
        return coords

    def route(self, mat, keys, sg, o: int, d: int) -> dict:
        dist, pred = dijkstra(mat, directed=True, indices=o, return_predecessors=True)
        seq = self._path(pred, keys, sg, o, d)
        reach = int(np.isfinite(dist).sum()) - 1
        if seq is None:
            return {"available": False, "length_m": None, "segments": [], "coords": [], "reachable_nodes": reach, "_dist": dist}
        return {"available": True, "length_m": float(dist[d]), "segments": [self.segments[i].id for i in seq],
                "coords": self.route_geometry(seq, o), "reachable_nodes": reach, "_dist": dist}

    # ------------------------------------------------------------- evaluation
    def evaluate(self, failed_ids: list[str], origin: tuple[float, float] | None, destination: tuple[float, float] | None,
                 affected_cap: int = 50_000) -> dict:
        failed = set(self.check_ids(failed_ids))
        b = self.baseline()
        mat, keys, sg = (b["mat"], b["keys"], b["seg"]) if not failed else self.csr(self.active_edges(failed))
        comp = b["comp"] if not failed else self.components(mat)

        # Mutual reachability with the main network (largest strongly connected component of the intact graph).
        base_main = b["main_mask"]
        sl = comp["strong_labels"]
        overlap = np.bincount(sl[base_main], minlength=comp["strong_n"])
        cur_label = int(overlap.argmax()) if base_main.any() else 0
        cur_main = sl == cur_label
        cut_off = base_main & ~cur_main
        cut_nodes = set(np.flatnonzero(cut_off).tolist())
        affected = [s.id for i, s in enumerate(self.segments)
                    if i not in failed and (self.node_pos[s.u] in cut_nodes or self.node_pos[s.v] in cut_nodes)]

        # Sampled origin–destination pairs (fixed seed) — an estimate, not an exhaustive all-pairs measure.
        src, tgt, d0 = b["sources"], b["targets"], b["dist"]
        if len(src):
            d1 = d0 if not failed else dijkstra(mat, directed=True, indices=src)[:, tgt]
            valid = src[:, None] != tgt[None, :]
            fin0, fin1 = np.isfinite(d0) & valid, np.isfinite(d1) & valid
            inv0 = np.where(fin0 & (d0 > 0), 1.0 / np.where(d0 > 0, d0, 1), 0.0).sum()
            inv1 = np.where(fin1 & (d1 > 0), 1.0 / np.where(d1 > 0, d1, 1), 0.0).sum()
            both = fin0 & fin1
            sampled = {
                "sources": int(len(src)), "targets": int(len(tgt)), "pairs": int(valid.sum()),
                "reachable_fraction_baseline": float(fin0.sum() / valid.sum()),
                "reachable_fraction": float(fin1.sum() / valid.sum()),
                "pairs_disconnected": int((fin0 & ~fin1).sum()),
                "mean_detour_pct": float(((d1[both] / d0[both]) - 1).mean() * 100) if both.any() else None,
                "max_detour_pct": float(((d1[both] / d0[both]) - 1).max() * 100) if both.any() else None,
                "efficiency_retention": float(inv1 / inv0) if inv0 > 0 else None,
            }
        else:
            sampled = None

        out: dict = {
            "failed": [self.segments[i].id for i in sorted(failed)],
            "network": {
                "segments_total": len(self.segments),
                "segments_failed": len(failed),
                "weak_components": comp["weak_n"],
                "strong_components": comp["strong_n"],
                "baseline_weak_components": b["comp"]["weak_n"],
                "baseline_strong_components": b["comp"]["strong_n"],
                "main_nodes_baseline": int(base_main.sum()),
                "main_nodes": int((base_main & cur_main).sum()),
                "cut_off_nodes": int(cut_off.sum()),
                "affected_segments": len(affected),
                "affected_km": float(sum(self.segments[self.seg_index[a]].length_m for a in affected) / 1000),
                "affected_segment_ids": affected[:affected_cap],
                "affected_truncated": len(affected) > affected_cap,
            },
            "sampled": sampled,
            "route": None,
        }

        if origin and destination:
            o, o_m = self.snap(*origin, restrict=base_main)
            d, d_m = self.snap(*destination, restrict=base_main)
            base_route = self.route(b["mat"], b["keys"], b["seg"], o, d)
            cur_route = base_route if not failed else self.route(mat, keys, sg, o, d)
            lost = np.isfinite(base_route["_dist"]) & ~np.isfinite(cur_route["_dist"])
            lost_nodes = set(np.flatnonzero(lost).tolist())
            lost_segs = [s.id for i, s in enumerate(self.segments)
                         if i not in failed and self.node_pos[s.u] in lost_nodes and self.node_pos[s.v] in lost_nodes]
            for r in (base_route, cur_route):
                r.pop("_dist", None)
            detour = (cur_route["length_m"] - base_route["length_m"]) if (cur_route["available"] and base_route["available"]) else None
            out["route"] = {
                "origin": {"node": int(self.node_ids[o]), "lonlat": self.node_lonlat[o].tolist(), "snap_m": o_m},
                "destination": {"node": int(self.node_ids[d]), "lonlat": self.node_lonlat[d].tolist(), "snap_m": d_m},
                "baseline": base_route,
                "current": cur_route,
                "uses_failed_segment": bool(failed and any(self.seg_index[s] in failed for s in base_route["segments"])),
                "detour_m": detour,
                "detour_pct": (detour / base_route["length_m"] * 100) if detour is not None and base_route["length_m"] else None,
                "reachable_from_origin_baseline": base_route["reachable_nodes"],
                "reachable_from_origin": cur_route["reachable_nodes"],
                "unreachable_from_origin_segment_ids": lost_segs[:affected_cap],
                "weight": "distance (m, great-circle segment length); no travel-time data",
            }
        return out

    # ----------------------------------------------------------- criticality
    def sampled_betweenness(self, k: int, progress=None) -> tuple[np.ndarray, np.ndarray, int]:
        """Brandes-style accumulation over shortest-path trees from `k` sampled sources.

        Returns (segment load, node load, number of source→target paths counted). With
        real-valued lengths ties are practically absent, so one predecessor tree per source
        gives the shortest paths."""
        b = self.baseline()
        mat, keys, sg = b["mat"], b["keys"], b["seg"]
        rng = np.random.default_rng(11)
        main_idx = np.flatnonzero(b["main_mask"])
        k = int(min(k, len(main_idx)))
        sources = rng.choice(main_idx, size=k, replace=False) if k else []
        seg_load = np.zeros(len(self.segments))
        node_load = np.zeros(self.n)
        paths = 0
        for j, s in enumerate(sources):
            dist, pred = dijkstra(mat, directed=True, indices=int(s), return_predecessors=True)
            reach = np.flatnonzero(np.isfinite(dist))
            order = reach[np.argsort(-dist[reach], kind="stable")]
            delta = np.zeros(self.n)
            p_arr = pred[order]
            pair = p_arr.astype(np.int64) * self.n + order
            valid = p_arr >= 0
            seg_of = np.full(len(order), -1, dtype=np.int64)
            seg_of[valid] = sg[np.searchsorted(keys, pair[valid])]
            for w, p, si in zip(order.tolist(), p_arr.tolist(), seg_of.tolist()):
                if p < 0:
                    continue
                flow = 1.0 + delta[w]
                delta[p] += flow
                seg_load[si] += flow
            delta[int(s)] = 0.0
            node_load += delta
            paths += len(reach) - 1
            if progress:
                progress(j + 1, k)
        return seg_load, node_load, paths
