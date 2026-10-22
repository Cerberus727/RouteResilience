from __future__ import annotations

from typing import Literal

import networkx as nx
from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from ..graph_io import GraphLoadError, Variant
from ..registry import get_registry
from ..schemas import GraphDetail, GraphSummary, ReportRequest, ReviewRequest, ShortestPathRequest, SimulationRequest
from ..services import criticality, exports, healing, reviews, simulation
from ..services import graphs as graph_service
from ..services.views import graph_detail

router = APIRouter(tags=["graphs"])
ID_RE = r"^[A-Za-z0-9_#\-]{1,64}$"


def _load(graph_id: str) -> graph_service.LoadedGraph:
    # GraphNotFoundError / GraphLoadError are mapped to HTTP errors in main.py
    return graph_service.get_graph(graph_id)


@router.get("/graphs", response_model=list[GraphSummary], summary="List graph files (all sets, or one set)")
def list_graphs(set_id: str | None = Query(None, pattern=r"^[a-z0-9_]+$"), summary: bool = True) -> list[dict]:
    reg = get_registry()
    out = []
    for gid in reg.all_graph_ids():
        s, _, path = reg.graph_path(gid)
        if set_id and s != set_id:
            continue
        row = {"graph_id": gid, "set_id": s, "image_id": gid.split("-", 1)[1]}
        if summary:
            try:
                lg = graph_service.get_graph(gid)
                row.update(nodes=len(lg.doc.nodes), edges=len(lg.doc.edges), healed_edges=sum(1 for e in lg.doc.edges if e.healed))
            except GraphLoadError as exc:
                row["error"] = f"{exc.code}: {exc.message}"
        out.append(row)
    return out


@router.get("/graphs/{graph_id}", response_model=GraphDetail, summary="Normalized graph with recomputed metrics")
async def get_graph(
    graph_id: str,
    variant: Variant = "healed",
    include_coords: bool = True,
    simplify: float = Query(1.0, ge=0, le=20, description="RDP tolerance in pixels for edge polylines (0 = raw)"),
) -> dict:
    lg = _load(graph_id)
    return await run_in_threadpool(graph_detail, lg, variant, include_coords, simplify)


@router.get("/graphs/{graph_id}/nodes/{node_id}", summary="Node attributes, neighbors and removal impact")
async def get_node(graph_id: str, node_id: str, variant: Variant = "healed") -> dict:
    lg = _load(graph_id)
    detail = await run_in_threadpool(criticality.node_detail, lg, node_id, variant)
    if detail is None:
        raise HTTPException(404, f"Node '{node_id}' not in graph {graph_id} ({variant}).")
    return detail


@router.get("/graphs/{graph_id}/critical-nodes", summary="Nodes ranked by length-weighted betweenness")
async def get_critical_nodes(
    graph_id: str,
    variant: Variant = "healed",
    top_k: int = Query(10, ge=1, le=100),
    impact_k: int = Query(5, ge=0, le=25),
    scope: Literal["full", "lcc"] = "full",
) -> dict:
    lg = _load(graph_id)
    return await run_in_threadpool(criticality.critical_nodes, lg, variant, top_k, scope, impact_k)


@router.post("/graphs/{graph_id}/shortest-path", summary="Shortest path between two nodes")
def shortest_path(graph_id: str, req: ShortestPathRequest) -> dict:
    lg = _load(graph_id)
    G = lg.graph(req.variant)
    missing = [n for n in (req.source, req.target) if n not in G]
    if missing:
        raise HTTPException(404, f"Node(s) not in graph: {', '.join(missing)}")
    weight = "length" if req.weight == "length" else None
    try:
        nodes = nx.dijkstra_path(G, req.source, req.target, weight=weight) if weight else nx.shortest_path(G, req.source, req.target)
    except nx.NetworkXNoPath:
        mem, _ = graph_service.membership(lg, req.variant)
        return {"reachable": False, "source": req.source, "target": req.target, "nodes": [], "edges": [],
                "length": None, "hops": None,
                "reason": f"No path: {req.source} is in component {mem[req.source]}, {req.target} in component {mem[req.target]}."}
    edges = [G.edges[u, v]["id"] for u, v in zip(nodes, nodes[1:])]
    length = sum(G.edges[u, v]["length"] for u, v in zip(nodes, nodes[1:]))
    healed_used = sum(1 for u, v in zip(nodes, nodes[1:]) if G.edges[u, v]["healed"])
    return {"reachable": True, "source": req.source, "target": req.target, "weight": req.weight, "nodes": nodes,
            "edges": edges, "length": length, "hops": len(edges), "healed_edges_used": healed_used}


@router.post("/graphs/{graph_id}/simulate-failure", summary="Remove nodes/edges on a copy and compare metrics")
async def simulate_failure(graph_id: str, req: SimulationRequest) -> dict:
    lg = _load(graph_id)
    return await run_in_threadpool(simulation.simulate, lg, req)


@router.post("/graphs/{graph_id}/simulate-failure/export", summary="Run a simulation and download the result")
async def simulate_export(graph_id: str, req: SimulationRequest, format: Literal["csv", "json"] = "csv") -> Response:
    lg = _load(graph_id)
    result = await run_in_threadpool(simulation.simulate, lg, req)
    name = f"simulation_{graph_id}"
    if format == "json":
        return JSONResponse(result, headers={"Content-Disposition": f'attachment; filename="{name}.json"'})
    return PlainTextResponse(exports.simulation_csv(result), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


@router.get("/graphs/{graph_id}/export", summary="Download graph statistics (JSON or CSV)")
async def export_graph(
    graph_id: str,
    format: Literal["json", "csv"] = "json",
    part: Literal["nodes", "edges", "metrics"] = "metrics",
    variant: Variant = "healed",
) -> Response:
    lg = _load(graph_id)
    if format == "json":
        body = await run_in_threadpool(exports.graph_json, lg, variant)
        return JSONResponse(body, headers={"Content-Disposition": f'attachment; filename="{graph_id}_{variant}.json"'})
    fn = {"nodes": exports.nodes_csv, "edges": exports.edges_csv, "metrics": exports.metrics_csv}[part]
    text = await run_in_threadpool(fn, lg, variant)
    return PlainTextResponse(text, media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{graph_id}_{variant}_{part}.csv"'})


def _report(lg, req: ReportRequest) -> tuple[str, str]:
    crit = criticality.critical_nodes(lg, req.variant, 10, "full", 5)
    sim = simulation.simulate(lg, req.simulation.model_copy(update={"variant": req.variant})) if req.simulation else None
    heal = healing.healing_summary(lg) if lg.doc.healing_provenance != "unavailable" else None
    md = exports.build_report(lg, req.variant, crit, sim, heal)
    if req.format == "html":
        return exports.markdown_to_html(md, f"RouteResilience — {lg.graph_id}"), "text/html"
    return md, "text/markdown"


@router.get("/graphs/{graph_id}/report", summary="Downloadable report (baseline + critical junctions + healing)")
async def report_get(graph_id: str, format: Literal["md", "html"] = "md", variant: Variant = "healed") -> Response:
    lg = _load(graph_id)
    body, media = await run_in_threadpool(_report, lg, ReportRequest(format=format, variant=variant))
    ext = "html" if format == "html" else "md"
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="report_{graph_id}.{ext}"'})


@router.post("/graphs/{graph_id}/report", summary="Report including a failure simulation")
async def report_post(graph_id: str, req: ReportRequest) -> Response:
    lg = _load(graph_id)
    body, media = await run_in_threadpool(_report, lg, req)
    ext = "html" if req.format == "html" else "md"
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="report_{graph_id}.{ext}"'})


@router.get("/graphs/{graph_id}/healing", summary="Healing review data (recorded bridge edges, before/after)")
async def get_healing(graph_id: str) -> dict:
    lg = _load(graph_id)
    return await run_in_threadpool(healing.healing_summary, lg)


@router.put("/graphs/{graph_id}/healing/{edge_id}/review", summary="Approve or reject a recorded healing bridge")
def put_review(graph_id: str, edge_id: str, req: ReviewRequest) -> dict:
    lg = _load(graph_id)
    if lg.doc.healing_provenance == "unavailable":
        raise HTTPException(409, "This graph does not record healing provenance; there is nothing to review.")
    edge = lg.doc.edge_index.get(edge_id)
    if edge is None:
        raise HTTPException(404, f"Edge '{edge_id}' not in graph {graph_id}.")
    if not edge.healed:
        raise HTTPException(400, f"Edge '{edge_id}' is an original road segment, not a healing bridge.")
    # ReviewStoreError (corrupt store) is mapped to a 500 with code=review_store_error in main.py
    record = reviews.set_review(graph_id, edge_id, None if req.decision == "unreviewed" else req.decision,
                                req.note, healing.artifact_version(lg))
    return {"graph_id": graph_id, "edge_id": edge_id, "review": record}
