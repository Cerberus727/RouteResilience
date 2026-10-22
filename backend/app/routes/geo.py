from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..geo import service
from ..geo.network import UnknownSegmentError
from ..geo.osm_index import Extent, IndexError_

router = APIRouter(prefix="/geo", tags=["geo"])
SEG_PATTERN = r"^\d{1,15}:\d{1,5}$"


class BBoxBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4, description="[min_lon, min_lat, max_lon, max_lat]")

    def extent(self, default: str) -> Extent:
        try:
            e = Extent(*self.bbox) if self.bbox else Extent.parse(default)
            e.validate()
        except IndexError_ as exc:
            raise HTTPException(422, str(exc)) from exc
        return e


class LonLat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)


class EvaluateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    failed: list[str] = Field(default_factory=list, max_length=500)
    origin: LonLat | None = None
    destination: LonLat | None = None

    @field_validator("failed")
    @classmethod
    def _ids(cls, v: list[str]) -> list[str]:
        import re

        bad = [x for x in v if not re.match(SEG_PATTERN, x)]
        if bad:
            raise ValueError(f"invalid segment id(s): {bad[:5]}")
        if len(set(v)) != len(v):
            raise ValueError("duplicate segment ids")
        return v


def _region(rid: str) -> service.Region:
    if not rid.isalnum() or len(rid) > 32:
        raise HTTPException(400, "Invalid region id.")
    return service.get_region(rid)


def _region_payload(r: service.Region) -> dict:
    return {"region_id": r.id, "bbox": r.bbox, "coverage": r.coverage, "built_seconds": r.built_seconds,
            "summary": r.network.summary(), "analysis_state": r.analysis.state, "places": r.places}


@router.get("/status", summary="OSM source, road index and index-build job status")
def status() -> dict:
    return service.index_status()


@router.post("/index", summary="Build/extend the road index for a bounding box (one PBF scan, runs in background)")
def build_index(body: BBoxBody) -> dict:
    from ..config import get_settings

    e = body.extent(get_settings().osm_extent)
    if e.max_lon - e.min_lon > 3 or e.max_lat - e.min_lat > 3:
        raise HTTPException(413, "Index extents are limited to 3°×3° per build.")
    try:
        job = service.index_manager().start(e)
    except IndexError_ as exc:
        raise HTTPException(409, str(exc)) from exc
    return job.snapshot()


@router.post("/regions", summary="Load the road network inside a bounding box")
async def load_region(body: BBoxBody) -> dict:
    from ..config import get_settings

    e = body.extent(get_settings().default_region)
    r = await run_in_threadpool(service.load_region, e)
    return _region_payload(r)


@router.get("/regions/{rid}", summary="Loaded region metadata and network summary")
def region(rid: str) -> dict:
    return _region_payload(_region(rid))


@router.get("/regions/{rid}/roads", summary="Road segments as GeoJSON (feature id = numeric index, sid = segment id)")
async def roads(rid: str):
    r = _region(rid)
    return JSONResponse(await run_in_threadpool(service.roads_geojson, r), headers={"Cache-Control": "private, max-age=600"})


@router.get("/regions/{rid}/intersections", summary="Intersections (≥3 incident segments) as GeoJSON")
async def intersections(rid: str):
    r = _region(rid)
    return JSONResponse(await run_in_threadpool(service.nodes_geojson, r), headers={"Cache-Control": "private, max-age=600"})


@router.get("/regions/{rid}/segments/{sid}", summary="Segment attributes, endpoints and neighbours")
def segment(rid: str, sid: str) -> dict:
    r = _region(rid)
    net = r.network
    if sid not in net.seg_index:
        raise HTTPException(404, f"Segment {sid} is not in this region.")
    s = net.segments[net.seg_index[sid]]
    by_node: dict[int, list[str]] = {}
    for o in net.segments:
        by_node.setdefault(o.u, []).append(o.id)
        by_node.setdefault(o.v, []).append(o.id)
    ends = []
    for nid in (s.u, s.v):
        i = net.node_pos[nid]
        ends.append({"nid": nid, "lonlat": net.node_lonlat[i].tolist(), "degree": len(by_node[nid]),
                     "segments": [x for x in by_node[nid] if x != sid]})
    res = r.analysis.result if r.analysis.state == "done" else None
    parallel = [o.id for o in net.segments if o.id != sid and {o.u, o.v} == {s.u, s.v}]
    return {
        "sid": s.id, "way_id": s.way_id, "osm_url": f"https://www.openstreetmap.org/way/{s.way_id}",
        "highway": s.highway, "tags": s.tags, "length_m": s.length_m,
        "direction": {1: "one-way (along way)", -1: "one-way (against way)", 0: "two-way"}[s.oneway],
        "endpoints": ends, "parallel_segments": parallel,
        "betweenness_share": (res["segment_scores"].get(s.id, 0.0) if res else None),
        "is_bridge": (s.id in set(res["bridges"]) if res else None),
    }


@router.get("/regions/{rid}/nodes/{nid}", summary="Intersection details")
def node(rid: str, nid: int) -> dict:
    r = _region(rid)
    net = r.network
    if nid not in net.node_pos:
        raise HTTPException(404, f"Node {nid} is not in this region.")
    segs = [s for s in net.segments if nid in (s.u, s.v)]
    i = net.node_pos[nid]
    res = r.analysis.result if r.analysis.state == "done" else None
    rec = next((x for x in res["intersections"] if x["nid"] == nid), None) if res else None
    return {
        "nid": nid, "osm_url": f"https://www.openstreetmap.org/node/{nid}", "lonlat": net.node_lonlat[i].tolist(),
        "degree": len(segs), "out_edges": int((net.e_src == i).sum()), "in_edges": int((net.e_dst == i).sum()),
        "segments": [{"sid": s.id, "name": s.tags.get("name") or s.tags.get("ref") or "", "highway": s.highway, "length_m": s.length_m} for s in segs],
        "in_main_network": bool(net.baseline()["main_mask"][i]),
        "critical_rank": rec["rank"] if rec else None,
        "is_articulation": rec["is_articulation"] if rec else None,
    }


@router.post("/regions/{rid}/evaluate", summary="Network state with the given failed segments (+ optional route)")
async def evaluate(rid: str, body: EvaluateBody) -> dict:
    r = _region(rid)
    if (body.origin is None) != (body.destination is None):
        raise HTTPException(422, "Provide both origin and destination, or neither.")
    o = (body.origin.lon, body.origin.lat) if body.origin else None
    d = (body.destination.lon, body.destination.lat) if body.destination else None
    try:
        return await run_in_threadpool(r.network.evaluate, body.failed, o, d)
    except UnknownSegmentError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/regions/{rid}/analysis", summary="Start critical-road analysis (background)")
def start_analysis(rid: str) -> dict:
    r = _region(rid)
    job = service.start_analysis(r)
    return {"state": job.state, "progress": job.progress, "phase": job.phase}


@router.get("/regions/{rid}/analysis", summary="Critical-road analysis status / result")
def analysis(rid: str) -> dict:
    r = _region(rid)
    j = r.analysis
    out = {"state": j.state, "progress": j.progress, "phase": j.phase, "error": j.error,
           "elapsed_s": ((j.finished_at or __import__("time").time()) - j.started_at) if j.started_at else None}
    if j.state == "done":
        out["result"] = j.result
    return out


@router.get("/search", summary="Search places (OSM place nodes in the index) and road names in the loaded region")
def search(q: str = Query(min_length=2, max_length=80), region_id: str | None = Query(None, max_length=32)) -> list[dict]:
    region = None
    if region_id:
        try:
            region = _region(region_id)
        except service.RegionError:
            region = None
    return service.search(q, region)
