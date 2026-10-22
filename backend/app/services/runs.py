"""Saved simulation runs.

A run is stored as the *inputs* (region bbox, origin/destination, ordered failure and
recovery actions) together with metrics that the backend **recomputes** for every
step at save time. Values sent by the browser are never stored as results.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..config import get_settings
from ..geo import service as geo
from ..geo.osm_index import Extent

_lock = threading.Lock()
RUN_ID = re.compile(r"^run-\d{8}T\d{6}Z-[0-9a-f]{6}$")
LIMITATIONS = [
    "Routing minimizes great-circle distance along OSM road geometry; no travel times, traffic, turn restrictions or road capacity are modelled.",
    "One-way rules follow OSM tags (oneway, roundabouts, motorways/links). Access restrictions other than access=no/private are not modelled.",
    "The network is the drivable OSM ways intersecting the region bounding box; roads outside it (and their alternate routes) are not included.",
    "Sampled network metrics use fixed random origin/target samples (seed 7) and are estimates, not exhaustive all-pairs values.",
    "Betweenness-based criticality is a structural indicator, not a measure of traffic volume or real-world importance.",
    "No repair times, costs, or traffic impacts are estimated; recovery steps simply restore the segment in the graph.",
]


class RunError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _dir() -> Path:
    d = get_settings().state_dir / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _step_metrics(ev: dict) -> dict:
    n, s, r = ev["network"], ev["sampled"] or {}, ev["route"]
    return {
        "failed_count": n["segments_failed"],
        "strong_components": n["strong_components"],
        "weak_components": n["weak_components"],
        "cut_off_nodes": n["cut_off_nodes"],
        "affected_segments": n["affected_segments"],
        "affected_km": n["affected_km"],
        "sampled_reachable_fraction": s.get("reachable_fraction"),
        "sampled_efficiency_retention": s.get("efficiency_retention"),
        "sampled_mean_detour_pct": s.get("mean_detour_pct"),
        "route_available": r["current"]["available"] if r else None,
        "route_length_m": r["current"]["length_m"] if r else None,
        "baseline_route_length_m": r["baseline"]["length_m"] if r else None,
        "detour_m": r["detour_m"] if r else None,
        "detour_pct": r["detour_pct"] if r else None,
        "reachable_from_origin": r["reachable_from_origin"] if r else None,
    }


def save_run(name: str, bbox: list[float], origin: list[float] | None, destination: list[float] | None, actions: list[dict]) -> dict:
    region = geo.load_region(Extent(*bbox))
    net = region.network
    failed: list[str] = []
    steps = []
    o = tuple(origin) if origin else None
    d = tuple(destination) if destination else None
    base = net.evaluate([], o, d, affected_cap=0)
    steps.append({"step": 0, "action": "baseline", "segment_id": None, "failed": [], "metrics": _step_metrics(base)})
    for i, a in enumerate(actions, start=1):
        kind, sid = a["action"], a.get("segment_id")
        if kind == "fail":
            if sid in failed:
                raise RunError(422, f"Step {i}: segment {sid} is already failed.")
            failed.append(sid)
        elif kind == "restore":
            if sid not in failed:
                raise RunError(422, f"Step {i}: segment {sid} is not failed.")
            failed.remove(sid)
        elif kind == "reset":
            failed = []
        ev = net.evaluate(list(failed), o, d, affected_cap=0)
        seg = net.segments[net.seg_index[sid]] if sid else None
        steps.append({"step": i, "action": kind, "segment_id": sid,
                      "segment_name": (seg.tags.get("name") or seg.tags.get("ref") or seg.highway) if seg else None,
                      "failed": list(failed), "metrics": _step_metrics(ev)})
    now = datetime.now(timezone.utc)
    run = {
        "id": f"run-{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}",
        "name": name.strip()[:120] or "Untitled run",
        "created_at": now.isoformat(timespec="seconds"),
        "region": {"bbox": region.bbox, "region_id": region.id, "segments": len(net.segments), "nodes": net.n,
                   "coverage": region.coverage, "source": str(get_settings().osm_pbf.name if get_settings().osm_pbf else "")},
        "origin": list(origin) if origin else None,
        "destination": list(destination) if destination else None,
        "routing_weight": "distance (m)",
        "steps": steps,
        "limitations": LIMITATIONS,
        "provenance": "All step metrics were recomputed by the backend from the stored actions at save time.",
    }
    with _lock:
        p = _dir() / f"{run['id']}.json"
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(run, f, indent=2)
        os.replace(tmp, p)
    return run


def list_runs() -> list[dict]:
    out = []
    for p in sorted(_dir().glob("run-*.json"), reverse=True):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            out.append({"id": p.stem, "name": "(unreadable run file)", "error": True})
            continue
        last = r["steps"][-1]["metrics"] if r.get("steps") else {}
        out.append({"id": r["id"], "name": r["name"], "created_at": r["created_at"], "bbox": r["region"]["bbox"],
                    "steps": len(r["steps"]) - 1, "final_failed": last.get("failed_count"),
                    "final_efficiency_retention": last.get("sampled_efficiency_retention")})
    return out


def get_run(run_id: str) -> dict:
    if not RUN_ID.match(run_id):
        raise RunError(400, "Invalid run id.")
    p = _dir() / f"{run_id}.json"
    if not p.is_file():
        raise RunError(404, f"Run {run_id} not found.")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RunError(422, f"Run file is corrupt: {exc}") from exc


def delete_run(run_id: str) -> None:
    get_run(run_id)
    (_dir() / f"{run_id}.json").unlink()


CSV_FIELDS = ["step", "action", "segment_id", "segment_name", "failed_count", "strong_components", "weak_components",
              "cut_off_nodes", "affected_segments", "affected_km", "sampled_reachable_fraction", "sampled_efficiency_retention",
              "sampled_mean_detour_pct", "route_available", "baseline_route_length_m", "route_length_m", "detour_m", "detour_pct",
              "reachable_from_origin"]


def run_csv(run: dict) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    for s in run["steps"]:
        w.writerow({**{k: ("" if v is None else v) for k, v in s["metrics"].items()}, "step": s["step"], "action": s["action"],
                    "segment_id": s.get("segment_id") or "", "segment_name": s.get("segment_name") or ""})
    return buf.getvalue()


def _f(v, unit="", digits=1):
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:,.{digits}f}{unit}"
    return f"{v:,}{unit}" if isinstance(v, int) else f"{v}{unit}"


def run_markdown(run: dict) -> str:
    b = run["region"]["bbox"]
    lines = [
        f"# RouteResilience simulation report — {run['name']}", "",
        f"Run `{run['id']}`, saved {run['created_at']}. {run['provenance']}", "",
        "## Parameters", "",
        f"* Region bbox (lon/lat): {b[0]:.5f}, {b[1]:.5f} → {b[2]:.5f}, {b[3]:.5f} ({run['region']['coverage']} index coverage)",
        f"* Network: {run['region']['segments']:,} road segments, {run['region']['nodes']:,} nodes, source `{run['region']['source']}`",
        f"* Origin: {run['origin'] or 'not set'} · Destination: {run['destination'] or 'not set'}",
        f"* Routing weight: {run['routing_weight']}", "",
        "## Failure and recovery sequence", "",
        "| Step | Action | Segment | Failed | Strong comp. | Cut-off nodes | Sampled reachability | Sampled efficiency | Route | Detour |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in run["steps"]:
        m = s["metrics"]
        route = "n/a" if m["route_available"] is None else (_f(m["route_length_m"], " m", 0) if m["route_available"] else "**no route**")
        det = "n/a" if m["detour_m"] is None else f"{m['detour_m']:+,.0f} m ({m['detour_pct']:+.1f}%)"
        seg = f"{s.get('segment_name') or ''} `{s['segment_id']}`" if s.get("segment_id") else "—"
        rf = m["sampled_reachable_fraction"]
        ef = m["sampled_efficiency_retention"]
        lines.append(f"| {s['step']} | {s['action']} | {seg} | {m['failed_count']} | {m['strong_components']} | {m['cut_off_nodes']} | "
                     f"{'n/a' if rf is None else f'{rf * 100:.1f}%'} | {'n/a' if ef is None else f'{ef * 100:.1f}%'} | {route} | {det} |")
    lines += ["", "## Metric definitions", "",
              "* **Cut-off nodes**: nodes of the intact network's largest strongly connected component that can no longer reach, and be reached from, the main network.",
              "* **Sampled reachability**: share of sampled origin→target pairs (24 origins × 400 targets, seed 7) that still have a route.",
              "* **Sampled efficiency**: Σ 1/d over the sampled pairs relative to the intact network (1/∞ = 0).",
              "* **Detour**: current shortest-route length minus the intact-network route length between the snapped origin and destination.",
              "", "## Limitations", ""]
    lines += [f"* {x}" for x in run["limitations"]]
    return "\n".join(lines) + "\n"
