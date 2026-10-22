"""Command-line road-index builder.

    python -m app.geo.cli index                       # default extent (ROUTERESILIENCE_OSM_EXTENT)
    python -m app.geo.cli index --bbox 80.15,12.95,80.32,13.16
    python -m app.geo.cli status
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

from ..config import get_settings
from .osm_index import Extent, IndexError_, IndexJob, connect, extents, run_isolated


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.geo.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    ix = sub.add_parser("index", help="scan the .pbf and index drivable roads inside a bounding box")
    ix.add_argument("--bbox", help="min_lon,min_lat,max_lon,max_lat (default: ROUTERESILIENCE_OSM_EXTENT)")
    sub.add_parser("status", help="show indexed extents")
    a = p.parse_args(argv)
    s = get_settings()
    db = s.cache_dir / "osm_roads.sqlite"
    if a.cmd == "status":
        if not db.is_file():
            print(f"No index at {db}")
            return 1
        for e in extents(connect(db)):
            print(f"extent {e['bbox']}  roads={e['roads']:,}  places={e['places']}  built={e['built_at']}  ({e['seconds']:.0f} s)")
        return 0
    if s.osm_pbf is None or not s.osm_pbf.is_file():
        print("No .osm.pbf found; set ROUTERESILIENCE_OSM_PBF.", file=sys.stderr)
        return 2
    try:
        extent = Extent.parse(a.bbox or s.osm_extent)
    except IndexError_ as exc:
        print(exc, file=sys.stderr)
        return 2
    job = IndexJob(state="running", extent=extent.as_list(), started_at=time.time())
    err: list[BaseException] = []
    t = threading.Thread(target=lambda: _run(s, db, extent, job, err), daemon=True)
    t.start()
    print(f"Indexing {s.osm_pbf.name} for {extent.as_list()} → {db}")
    while t.is_alive():
        print(f"\r  {job.phase[:60]:<60} ways scanned {job.ways_seen:>10,}  kept {job.roads_kept:>8,}  {time.time() - job.started_at:6.0f} s", end="", flush=True)
        t.join(1.0)
    print()
    if err:
        print(f"FAILED: {err[0]}", file=sys.stderr)
        return 1
    print("\n".join(job.log))
    return 0


def _run(s, db, extent, job, err):
    try:
        run_isolated(s.osm_pbf, db, extent, job, s.cache_dir / "tmp")
    except BaseException as exc:  # reported by main()
        err.append(exc)


if __name__ == "__main__":
    raise SystemExit(main())
