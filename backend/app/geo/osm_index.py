"""OSM PBF → on-disk spatial index of drivable roads (SQLite + R*Tree).

The Southern-zone PBF is ~560 MB, far too large to load per request. We scan it
once per *index extent* (a configurable bounding box, Chennai by default) and keep
every drivable way that touches the extent, with its full geometry and node IDs.
Regional graphs are then built from fast bounding-box queries on this index.

Node locations are resolved with a disk-backed osmium location index
(`sparse_file_array`), so memory use stays low even for the full file.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from array import array
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 2

# Motor-vehicle road classes. Footways, paths, cycleways, steps, tracks and
# construction/proposed ways are excluded from the routing network.
DRIVABLE = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
    "residential", "living_street", "service", "road",
}
EXCLUDED_SERVICE = {"parking_aisle", "driveway", "drive-through"}
KEPT_TAGS = ("name", "ref", "oneway", "junction", "lanes", "maxspeed", "bridge", "tunnel", "surface", "access", "service")
PLACE_KINDS = {"city", "town", "suburb", "neighbourhood", "quarter", "village", "hamlet", "locality"}


class IndexError_(Exception):
    pass


@dataclass
class Extent:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    @classmethod
    def parse(cls, text: str) -> "Extent":
        try:
            a, b, c, d = (float(x) for x in text.split(","))
        except ValueError as exc:
            raise IndexError_(f"Bounding box must be 'min_lon,min_lat,max_lon,max_lat', got {text!r}") from exc
        e = cls(a, b, c, d)
        e.validate()
        return e

    def validate(self) -> None:
        if not (-180 <= self.min_lon < self.max_lon <= 180 and -90 <= self.min_lat < self.max_lat <= 90):
            raise IndexError_(f"Invalid bounding box {self.as_list()} (need min < max, lon in ±180, lat in ±90).")

    def as_list(self) -> list[float]:
        return [self.min_lon, self.min_lat, self.max_lon, self.max_lat]

    def intersects(self, minx: float, miny: float, maxx: float, maxy: float) -> bool:
        return not (maxx < self.min_lon or minx > self.max_lon or maxy < self.min_lat or miny > self.max_lat)

    def contains(self, other: "Extent") -> bool:
        return (self.min_lon <= other.min_lon and self.min_lat <= other.min_lat
                and self.max_lon >= other.max_lon and self.max_lat >= other.max_lat)


@dataclass
class IndexJob:
    state: str = "idle"  # idle | running | done | error
    extent: list[float] | None = None
    started_at: float | None = None
    finished_at: float | None = None
    phase: str = ""
    ways_seen: int = 0
    roads_kept: int = 0
    places_kept: int = 0
    error: str | None = None
    log: list[str] = field(default_factory=list)

    def snapshot(self) -> dict:
        elapsed = ((self.finished_at or time.time()) - self.started_at) if self.started_at else None
        return {"state": self.state, "extent": self.extent, "phase": self.phase, "ways_seen": self.ways_seen,
                "roads_kept": self.roads_kept, "places_kept": self.places_kept, "elapsed_s": elapsed,
                "error": self.error, "log": self.log[-20:]}


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path), check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS extents (id INTEGER PRIMARY KEY AUTOINCREMENT, min_lon REAL, min_lat REAL,
            max_lon REAL, max_lat REAL, built_at TEXT, source TEXT, roads INTEGER, places INTEGER, seconds REAL);
        CREATE TABLE IF NOT EXISTS ways (id INTEGER PRIMARY KEY, highway TEXT NOT NULL, tags TEXT NOT NULL,
            node_ids BLOB NOT NULL, coords BLOB NOT NULL);
        CREATE VIRTUAL TABLE IF NOT EXISTS ways_rtree USING rtree(id, min_lon, max_lon, min_lat, max_lat);
        CREATE TABLE IF NOT EXISTS places (id INTEGER PRIMARY KEY, name TEXT, kind TEXT, lon REAL, lat REAL);
        CREATE INDEX IF NOT EXISTS places_name ON places(name);
        """
    )
    row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if row is None:
        con.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        con.commit()
    elif int(row[0]) != SCHEMA_VERSION:
        raise IndexError_(f"Road index {db_path.name} has schema v{row[0]}, expected v{SCHEMA_VERSION}. Delete it and rebuild.")
    return con


def build_index(pbf: Path, db_path: Path, extent: Extent, job: IndexJob, tmp_dir: Path, cleanup: bool = True) -> None:
    """Scan the PBF once and store drivable ways that touch `extent`. Runs in a worker thread."""
    import osmium  # optional dependency; imported lazily so the API starts without it

    if not pbf.is_file():
        raise IndexError_(f"OSM file not found: {pbf}")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    loc_file = tmp_dir / "node_locations.bin"
    loc_file.unlink(missing_ok=True)
    t0 = time.time()
    job.phase = "reading nodes and ways (node locations are indexed on disk)"
    job.log.append(f"Scanning {pbf.name} ({pbf.stat().st_size / 1e6:.0f} MB) for extent {extent.as_list()}")

    con = connect(db_path)
    fp = locations = obj = None
    ways_rows: list[tuple] = []
    rtree_rows: list[tuple] = []
    place_rows: list[tuple] = []
    try:
        locations = osmium.index.create_map(f"sparse_file_array,{loc_file}")
        fp = (osmium.FileProcessor(str(pbf))
              .with_locations(locations)
              .with_filter(osmium.filter.KeyFilter("highway", "place")))
        for obj in fp:
            if obj.is_way():
                job.ways_seen += 1
                tags = obj.tags
                hw = tags.get("highway")
                if hw not in DRIVABLE or tags.get("service") in EXCLUDED_SERVICE or tags.get("access") in ("no", "private"):
                    continue
                lons, lats, ids = array("d"), array("d"), array("q")
                ok = True
                for n in obj.nodes:
                    loc = n.location
                    if not loc.valid():
                        ok = False
                        break
                    lons.append(loc.lon)
                    lats.append(loc.lat)
                    ids.append(n.ref)
                if not ok or len(ids) < 2:
                    continue
                minx, maxx, miny, maxy = min(lons), max(lons), min(lats), max(lats)
                if not extent.intersects(minx, miny, maxx, maxy):
                    continue
                coords = array("d")
                for x, y in zip(lons, lats):
                    coords.append(x)
                    coords.append(y)
                kept = {k: tags.get(k) for k in KEPT_TAGS if tags.get(k) is not None}
                ways_rows.append((obj.id, hw, json.dumps(kept, ensure_ascii=False), ids.tobytes(), coords.tobytes()))
                rtree_rows.append((obj.id, minx, maxx, miny, maxy))
                job.roads_kept += 1
                if len(ways_rows) >= 5000:
                    _flush(con, ways_rows, rtree_rows)
                    job.phase = f"reading ways — {job.roads_kept:,} drivable ways in extent so far"
            elif obj.is_node():
                kind = obj.tags.get("place")
                name = obj.tags.get("name")
                if kind in PLACE_KINDS and name and obj.location.valid():
                    lon, lat = obj.location.lon, obj.location.lat
                    if extent.min_lon <= lon <= extent.max_lon and extent.min_lat <= lat <= extent.max_lat:
                        place_rows.append((obj.id, name, kind, lon, lat))
                        job.places_kept += 1
        _flush(con, ways_rows, rtree_rows)
        con.executemany("INSERT OR REPLACE INTO places VALUES (?,?,?,?,?)", place_rows)
        seconds = time.time() - t0
        con.execute(
            "INSERT INTO extents (min_lon,min_lat,max_lon,max_lat,built_at,source,roads,places,seconds) VALUES (?,?,?,?,datetime('now'),?,?,?,?)",
            (*extent.as_list(), f"{pbf.name}|{pbf.stat().st_size}|{int(pbf.stat().st_mtime)}", job.roads_kept, job.places_kept, seconds),
        )
        con.commit()
        job.log.append(f"Indexed {job.roads_kept:,} drivable ways and {job.places_kept:,} places in {seconds:.0f} s")
    finally:
        con.close()
        # Release the memory-mapped location index before deleting it (Windows keeps mapped files locked).
        if cleanup:
            fp = locations = obj = None  # noqa: F841
            _remove_temp(loc_file, job)


def _remove_temp(loc_file: Path, job: IndexJob) -> None:
    import gc

    gc.collect()
    try:
        loc_file.unlink(missing_ok=True)
    except OSError as exc:
        job.log.append(f"Could not delete temporary file {loc_file.name}: {exc} (safe to delete manually)")


def _child(pbf: str, db: str, extent: list[float], tmp_dir: str, q) -> None:
    """Worker-process entry point: scan the PBF and stream job snapshots to the parent."""
    job = IndexJob(state="running", extent=extent, started_at=time.time(), phase="starting")
    stop = threading.Event()

    def pump():
        while not stop.is_set():
            q.put(job.snapshot())
            stop.wait(1.0)

    threading.Thread(target=pump, daemon=True).start()
    try:
        build_index(Path(pbf), Path(db), Extent(*extent), job, Path(tmp_dir), cleanup=False)
        job.state, job.phase = "done", "complete"
    except Exception as exc:  # reported to the parent
        job.state, job.phase, job.error = "error", "failed", f"{type(exc).__name__}: {exc}"
    finally:
        stop.set()
        job.finished_at = time.time()
        q.put(job.snapshot())


def run_isolated(pbf: Path, db_path: Path, extent: Extent, job: IndexJob, tmp_dir: Path) -> None:
    """Run `build_index` in a separate process.

    Isolation keeps the API responsive (the scan is Python-callback heavy and would hold the GIL), and the
    OS releases the memory-mapped node-location file when the process exits, so the parent can delete it
    (Windows refuses to delete a file that is still mapped)."""
    import multiprocessing as mp
    import queue as queue_mod

    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    proc = ctx.Process(target=_child, args=(str(pbf), str(db_path), extent.as_list(), str(tmp_dir), q), daemon=True, name="osm-index")
    proc.start()
    final = None
    while proc.is_alive() or not q.empty():
        try:
            snap = q.get(timeout=0.5)
        except queue_mod.Empty:
            continue
        for k in ("phase", "ways_seen", "roads_kept", "places_kept", "log", "error"):
            setattr(job, k, snap[k])
        if snap["state"] in ("done", "error"):
            final = snap
    proc.join()
    _remove_temp(tmp_dir / "node_locations.bin", job)
    if final is None:
        raise IndexError_(f"Index worker exited unexpectedly (exit code {proc.exitcode}).")
    if final["state"] == "error":
        raise IndexError_(final["error"] or "Index build failed.")


def _flush(con: sqlite3.Connection, ways_rows: list, rtree_rows: list) -> None:
    if not ways_rows:
        return
    ids = [(r[0],) for r in rtree_rows]
    con.executemany("DELETE FROM ways_rtree WHERE id=?", ids)
    con.executemany("INSERT OR REPLACE INTO ways VALUES (?,?,?,?,?)", ways_rows)
    con.executemany("INSERT INTO ways_rtree VALUES (?,?,?,?,?)", rtree_rows)
    con.commit()
    ways_rows.clear()
    rtree_rows.clear()


@dataclass
class WayRecord:
    id: int
    highway: str
    tags: dict
    node_ids: list[int]
    coords: list[tuple[float, float]]


def query_ways(con: sqlite3.Connection, bbox: Extent) -> list[WayRecord]:
    rows = con.execute(
        "SELECT w.id, w.highway, w.tags, w.node_ids, w.coords FROM ways_rtree r JOIN ways w ON w.id = r.id "
        "WHERE r.max_lon >= ? AND r.min_lon <= ? AND r.max_lat >= ? AND r.min_lat <= ? ORDER BY w.id",
        (bbox.min_lon, bbox.max_lon, bbox.min_lat, bbox.max_lat),
    ).fetchall()
    out = []
    for wid, hw, tags, nids, coords in rows:
        ids = array("q")
        ids.frombytes(nids)
        c = array("d")
        c.frombytes(coords)
        out.append(WayRecord(wid, hw, json.loads(tags), list(ids), list(zip(c[0::2], c[1::2]))))
    return out


def extents(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute("SELECT id,min_lon,min_lat,max_lon,max_lat,built_at,source,roads,places,seconds FROM extents ORDER BY id").fetchall()
    return [{"id": r[0], "bbox": [r[1], r[2], r[3], r[4]], "built_at": r[5], "source": r[6], "roads": r[7], "places": r[8], "seconds": r[9]} for r in rows]


def search_places(con: sqlite3.Connection, q: str, limit: int = 8) -> list[dict]:
    rows = con.execute("SELECT name, kind, lon, lat FROM places WHERE name LIKE ? ORDER BY length(name) LIMIT ?", (f"%{q}%", limit)).fetchall()
    return [{"name": n, "kind": k, "lon": lon, "lat": lat, "source": "OSM place node"} for n, k, lon, lat in rows]


def places_in(con: sqlite3.Connection, bbox: "Extent", limit: int = 6) -> list[dict]:
    order = "CASE kind WHEN 'city' THEN 0 WHEN 'town' THEN 1 WHEN 'suburb' THEN 2 WHEN 'quarter' THEN 3 WHEN 'neighbourhood' THEN 4 ELSE 5 END"
    rows = con.execute(
        f"SELECT name, kind, lon, lat FROM places WHERE lon BETWEEN ? AND ? AND lat BETWEEN ? AND ? ORDER BY {order}, name LIMIT ?",
        (bbox.min_lon, bbox.max_lon, bbox.min_lat, bbox.max_lat, limit),
    ).fetchall()
    return [{"name": n, "kind": k, "lon": lon, "lat": lat} for n, k, lon, lat in rows]


class IndexManager:
    """Owns the index DB path and the single background build job."""

    def __init__(self, pbf: Path | None, db_path: Path, tmp_dir: Path):
        self.pbf = pbf
        self.db_path = db_path
        self.tmp_dir = tmp_dir
        self.job = IndexJob()
        self._lock = threading.Lock()

    def available(self) -> bool:
        return self.db_path.is_file()

    def connect(self) -> sqlite3.Connection:
        return connect(self.db_path)

    def start(self, extent: Extent) -> IndexJob:
        with self._lock:
            if self.job.state == "running":
                raise IndexError_("An index build is already running.")
            if self.pbf is None or not self.pbf.is_file():
                raise IndexError_("No OSM .pbf file configured or found (set ROUTERESILIENCE_OSM_PBF).")
            try:
                import osmium  # noqa: F401
            except ImportError as exc:
                raise IndexError_("pyosmium is not installed (pip install osmium).") from exc
            self.job = IndexJob(state="running", extent=extent.as_list(), started_at=time.time(), phase="starting")
            job = self.job

        def run():
            try:
                run_isolated(self.pbf, self.db_path, extent, job, self.tmp_dir)
                job.state = "done"
                job.phase = "complete"
            except Exception as exc:  # reported through the status endpoint
                job.state = "error"
                job.error = f"{type(exc).__name__}: {exc}"
                job.phase = "failed"
            finally:
                job.finished_at = time.time()

        threading.Thread(target=run, name="osm-index", daemon=True).start()
        return job
