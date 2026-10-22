"""Road graph construction, routing, failure simulation and recovery on small synthetic networks.

Coordinates are near (80.0 E, 13.0 N). These synthetic ways exist only in tests."""

import json
import sqlite3
from array import array

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.geo.network import RoadNetwork, UnknownSegmentError, haversine, oneway_direction, split_ways
from app.geo.osm_index import WayRecord, connect

D = 0.001  # ~108 m in longitude, ~111 m in latitude at 13°N


def way(wid, nodes, pts, highway="residential", **tags):
    return WayRecord(wid, highway, dict(tags), list(nodes), [(80.0 + x * D, 13.0 + y * D) for x, y in pts])


def ladder():
    """Two parallel streets joined by three rungs:

        1 ── 2 ── 3      (way 10, top street)
        |    |    |      (ways 20, 21, 22 = rungs)
        4 ── 5 ── 6      (way 11, bottom street)
    """
    return [
        way(10, [1, 2, 3], [(0, 1), (1, 1), (2, 1)]),
        way(11, [4, 5, 6], [(0, 0), (1, 0), (2, 0)]),
        way(20, [1, 4], [(0, 1), (0, 0)]),
        way(21, [2, 5], [(1, 1), (1, 0)]),
        way(22, [3, 6], [(2, 1), (2, 0)]),
    ]


def net_of(ways):
    return RoadNetwork("t", [79.99, 12.99, 80.01, 13.01], split_ways(ways))


def P(x, y):
    return (80.0 + x * D, 13.0 + y * D)


def test_oneway_semantics():
    assert oneway_direction("residential", {"oneway": "yes"}) == 1
    assert oneway_direction("residential", {"oneway": "-1"}) == -1
    assert oneway_direction("residential", {}) == 0
    assert oneway_direction("primary", {"junction": "roundabout"}) == 1
    assert oneway_direction("motorway", {}) == 1
    assert oneway_direction("motorway", {"oneway": "no"}) == 0
    assert oneway_direction("secondary", {"oneway": "reversible"}) == 0


def test_split_at_junctions_with_stable_ids():
    segs = split_ways(ladder())
    ids = sorted(s.id for s in segs)
    assert ids == sorted(["10:0", "10:1", "11:0", "11:1", "20:0", "21:0", "22:0"])
    s = next(s for s in segs if s.id == "10:1")
    assert (s.u, s.v) == (2, 3)
    assert s.length_m == pytest.approx(haversine(*P(1, 1), *P(2, 1)))
    assert split_ways(ladder())[3].id == segs[3].id  # deterministic


def test_closed_loop_is_split_not_self_loop():
    loop = way(30, [7, 8, 9, 7], [(0, 0), (1, 0), (1, 1), (0, 0)])
    segs = split_ways([loop])
    assert len(segs) == 2 and all(s.u != s.v for s in segs)


def test_baseline_route_and_detour_after_failure():
    net = net_of(ladder())
    a, b = P(0, 1), P(2, 1)  # node 1 -> node 3 along the top street
    base = net.evaluate([], a, b)["route"]
    assert base["baseline"]["available"] and base["baseline"]["segments"] == ["10:0", "10:1"]
    top = haversine(*P(0, 1), *P(2, 1))
    assert base["baseline"]["length_m"] == pytest.approx(top, rel=1e-9)
    ev = net.evaluate(["10:1"], a, b)
    r = ev["route"]
    assert r["current"]["available"] and r["uses_failed_segment"]
    assert "10:1" not in r["current"]["segments"]
    detour_expected = haversine(*P(1, 1), *P(1, 0)) + haversine(*P(1, 0), *P(2, 0)) + haversine(*P(2, 0), *P(2, 1)) - haversine(*P(1, 1), *P(2, 1))
    assert r["detour_m"] == pytest.approx(detour_expected, rel=1e-6)
    assert r["detour_pct"] == pytest.approx(detour_expected / top * 100, rel=1e-6)
    # geometry is continuous and ends at the destination
    assert r["current"]["coords"][0] == pytest.approx(list(a)) and r["current"]["coords"][-1] == pytest.approx(list(b))
    assert ev["network"]["cut_off_nodes"] == 0 and ev["sampled"]["pairs_disconnected"] == 0
    assert 0 < ev["sampled"]["efficiency_retention"] < 1


def test_restore_returns_exact_baseline():
    net = net_of(ladder())
    a, b = P(0, 1), P(2, 0)
    base = net.evaluate([], a, b)
    net.evaluate(["21:0", "10:1"], a, b)
    again = net.evaluate([], a, b)
    assert again["network"] == base["network"]
    assert again["sampled"] == base["sampled"]
    assert again["route"]["current"] == base["route"]["current"]


def test_disconnection_reports_no_route_and_cut_off_component():
    # A dead-end spur 3 -> 7 hanging off the ladder
    ways = ladder() + [way(40, [3, 7], [(2, 1), (3, 1)])]
    net = net_of(ways)
    ev = net.evaluate(["40:0"], P(0, 0), P(3, 1))
    r = ev["route"]
    # destination snaps to node 7, which is cut off once the spur fails
    assert r["baseline"]["available"] and not r["current"]["available"]
    assert r["current"]["length_m"] is None and r["detour_m"] is None
    assert ev["network"]["cut_off_nodes"] == 1
    assert ev["network"]["weak_components"] == 2
    assert r["reachable_from_origin"] == r["reachable_from_origin_baseline"] - 1


def test_oneway_is_respected():
    ways = [way(1, [1, 2], [(0, 0), (1, 0)], oneway="yes"), way(2, [2, 3, 1], [(1, 0), (1, 1), (0, 0)])]
    net = net_of(ways)
    fwd = net.evaluate([], P(0, 0), P(1, 0))["route"]["baseline"]
    back = net.evaluate([], P(1, 0), P(0, 0))["route"]["baseline"]
    assert fwd["segments"] == ["1:0"]
    assert "1:0" not in back["segments"]  # must use the two-way detour
    assert back["length_m"] > fwd["length_m"]


def test_parallel_segments_stay_distinct_and_use_minimum():
    # Two different ways joining the same pair of junctions (dual carriageway-like)
    short = way(1, [1, 2], [(0, 0), (1, 0)])
    long_ = way(2, [1, 9, 2], [(0, 0), (0.5, 0.6), (1, 0)])
    long_.node_ids = [1, 9, 2]
    tail = way(3, [2, 3], [(1, 0), (2, 0)])
    net = net_of([short, long_, tail])
    assert {"1:0", "2:0"} <= set(net.seg_index)
    r = net.evaluate([], P(0, 0), P(2, 0))["route"]["baseline"]
    assert r["segments"][0] == "1:0"
    # A summed (wrong) reduction would make this length short+long
    assert r["length_m"] == pytest.approx(haversine(*P(0, 0), *P(1, 0)) + haversine(*P(1, 0), *P(2, 0)))
    r2 = net.evaluate(["1:0"], P(0, 0), P(2, 0))["route"]["current"]
    assert r2["available"] and r2["segments"][0] == "2:0"


def test_unknown_segment_rejected():
    with pytest.raises(UnknownSegmentError):
        net_of(ladder()).evaluate(["999:0"], None, None)


def test_sampled_betweenness_prefers_bottleneck():
    # Two ladders joined by a single connector 3 -> 101
    left = ladder()
    right = [way(w.id + 100, [n + 100 for n in w.node_ids], [((x - 80.0) / D + 4, (y - 13.0) / D) for x, y in w.coords]) for w in ladder()]
    conn = way(99, [3, 101], [(2, 1), (4, 1)])
    net = net_of(left + right + [conn])
    seg_load, node_load, paths = net.sampled_betweenness(12)
    share = seg_load / paths
    top = net.segments[int(np.argmax(share))].id
    assert top == "99:0"
    assert paths > 0 and node_load.max() > 0


# ---------------------------------------------------------------- API level
@pytest.fixture()
def geo_client(tmp_path, monkeypatch):
    from app import config, registry
    from app.geo import service
    from app.main import create_app

    cache = tmp_path / "cache"
    con = connect(cache / "osm_roads.sqlite")
    ways = ladder() + [way(40, [3, 7], [(2, 1), (3, 1)], name="Spur Road")]
    for w in ways:
        c = array("d")
        for x, y in w.coords:
            c += array("d", [x, y])
        xs, ys = [p[0] for p in w.coords], [p[1] for p in w.coords]
        con.execute("INSERT INTO ways VALUES (?,?,?,?,?)", (w.id, w.highway, json.dumps(w.tags), array("q", w.node_ids).tobytes(), c.tobytes()))
        con.execute("INSERT INTO ways_rtree VALUES (?,?,?,?,?)", (w.id, min(xs), max(xs), min(ys), max(ys)))
    con.execute("INSERT INTO places VALUES (1,'Testnagar','suburb',80.001,13.0005)")
    con.execute("INSERT INTO extents (min_lon,min_lat,max_lon,max_lat,built_at,source,roads,places,seconds) VALUES (79.99,12.99,80.01,13.01,'now','synthetic',6,1,0)")
    con.commit()
    con.close()
    monkeypatch.setenv("ROUTERESILIENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ROUTERESILIENCE_CACHE_DIR", str(cache))
    monkeypatch.setenv("ROUTERESILIENCE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("ROUTERESILIENCE_DEFAULT_REGION", "79.995,12.995,80.005,13.005")
    config.get_settings.cache_clear()
    registry.reset_for_tests(config.get_settings())
    service.reset_for_tests()
    with TestClient(create_app()) as c:
        yield c
    config.get_settings.cache_clear()
    service.reset_for_tests()
    registry._registry = None


def test_api_region_roads_evaluate_restore(geo_client):
    st = geo_client.get("/api/geo/status").json()
    assert st["index_exists"] and st["extents"][0]["roads"] == 6
    r = geo_client.post("/api/geo/regions", json={}).json()
    rid = r["region_id"]
    assert r["summary"]["segments"] == 8 and r["coverage"] == "full"
    roads = geo_client.get(f"/api/geo/regions/{rid}/roads").json()
    assert len(roads["features"]) == 8
    f0 = roads["features"][0]
    assert f0["geometry"]["coordinates"][0][0] == pytest.approx(80.0, abs=0.01)  # real lon/lat, not pixels
    body = {"failed": ["40:0"], "origin": {"lon": P(0, 0)[0], "lat": P(0, 0)[1]}, "destination": {"lon": P(3, 1)[0], "lat": P(3, 1)[1]}}
    ev = geo_client.post(f"/api/geo/regions/{rid}/evaluate", json=body).json()
    assert ev["route"]["current"]["available"] is False and ev["network"]["cut_off_nodes"] == 1
    base = geo_client.post(f"/api/geo/regions/{rid}/evaluate", json={**body, "failed": []}).json()
    assert base["route"]["current"]["available"] and base["network"]["cut_off_nodes"] == 0
    seg = geo_client.get(f"/api/geo/regions/{rid}/segments/40:0").json()
    assert seg["tags"]["name"] == "Spur Road" and seg["osm_url"].endswith("/way/40")
    assert geo_client.get(f"/api/geo/regions/{rid}/segments/1:0").status_code == 404
    hits = geo_client.get("/api/geo/search", params={"q": "spur", "region_id": rid}).json()
    assert hits[0]["segment_ids"] == ["40:0"]
    assert any(h["name"] == "Testnagar" for h in geo_client.get("/api/geo/search", params={"q": "testn"}).json())


@pytest.mark.parametrize("body,status", [
    ({"failed": ["x"]}, 422), ({"failed": ["1:0", "1:0"]}, 422), ({"failed": ["999:0"]}, 400),
    ({"origin": {"lon": 80, "lat": 13}}, 422), ({"failed": [], "bogus": 1}, 422),
])
def test_api_evaluate_validation(geo_client, body, status):
    rid = geo_client.post("/api/geo/regions", json={}).json()["region_id"]
    assert geo_client.post(f"/api/geo/regions/{rid}/evaluate", json=body).status_code == status


def test_api_region_errors(geo_client):
    assert geo_client.post("/api/geo/regions", json={"bbox": [81, 14, 81.01, 14.01]}).json()["code"] == "not_indexed"
    assert geo_client.post("/api/geo/regions", json={"bbox": [79, 12, 80, 13]}).status_code == 413
    assert geo_client.post("/api/geo/regions", json={"bbox": [80, 13, 79, 12]}).status_code == 422
    assert geo_client.get("/api/geo/regions/abc123/roads").json()["code"] == "region_not_loaded"


def test_api_analysis_and_runs(geo_client):
    import time

    rid = geo_client.post("/api/geo/regions", json={}).json()["region_id"]
    geo_client.post(f"/api/geo/regions/{rid}/analysis")
    for _ in range(100):
        a = geo_client.get(f"/api/geo/regions/{rid}/analysis").json()
        if a["state"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert a["state"] == "done", a
    assert "40:0" in a["result"]["bridges"]  # the spur is a bridge; ladder rungs are not
    assert not {"20:0", "21:0", "22:0"} & set(a["result"]["bridges"])

    bbox = [79.995, 12.995, 80.005, 13.005]
    body = {"name": "spur test", "bbox": bbox, "origin": list(P(0, 0)), "destination": list(P(3, 1)),
            "actions": [{"action": "fail", "segment_id": "40:0"}, {"action": "restore", "segment_id": "40:0"}]}
    run = geo_client.post("/api/runs", json=body).json()
    steps = run["steps"]
    assert [s["action"] for s in steps] == ["baseline", "fail", "restore"]
    assert steps[1]["metrics"]["route_available"] is False and steps[1]["metrics"]["cut_off_nodes"] == 1
    assert steps[2]["metrics"] == steps[0]["metrics"]  # recovery restores the baseline exactly
    assert geo_client.get("/api/runs").json()[0]["id"] == run["id"]
    csv_text = geo_client.get(f"/api/runs/{run['id']}/export?format=csv").text
    assert csv_text.splitlines()[0].startswith("step,action") and len(csv_text.splitlines()) == 4
    md = geo_client.get(f"/api/runs/{run['id']}/export?format=md").text
    assert "**no route**" in md and "Limitations" in md
    bad = {**body, "actions": [{"action": "restore", "segment_id": "40:0"}]}
    assert geo_client.post("/api/runs", json=bad).status_code == 422
    assert geo_client.get("/api/runs/run-nope").status_code == 400
    assert geo_client.delete(f"/api/runs/{run['id']}").status_code == 200
    assert geo_client.get("/api/runs").json() == []


def test_api_without_index(tmp_path, monkeypatch):
    from app import config, registry
    from app.geo import service
    from app.main import create_app

    monkeypatch.setenv("ROUTERESILIENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ROUTERESILIENCE_CACHE_DIR", str(tmp_path / "nocache"))
    config.get_settings.cache_clear()
    registry.reset_for_tests(config.get_settings())
    service.reset_for_tests()
    try:
        with TestClient(create_app()) as c:
            st = c.get("/api/geo/status").json()
            assert st["index_exists"] is False and st["pbf"]["exists"] is False
            assert c.post("/api/geo/regions", json={}).json()["code"] == "index_missing"
            r = c.post("/api/geo/index", json={})
            assert r.status_code == 409 and "pbf" in r.json()["detail"].lower()
    finally:
        config.get_settings.cache_clear()
        service.reset_for_tests()
        registry._registry = None


def test_real_chennai_region_fail_and_restore():
    """Against the real OSM index (skipped if it has not been built)."""
    from app import config
    from app.geo import service
    from app.geo.osm_index import Extent

    config.get_settings.cache_clear()
    service.reset_for_tests()
    if not service.index_manager().available():
        pytest.skip("OSM road index not built")
    region = service.load_region(Extent.parse(config.get_settings().default_region))
    net = region.network
    assert net.summary()["segments"] > 1000
    lon_ok = all(79 < s.coords[0][0] < 81 and 12 < s.coords[0][1] < 14 for s in net.segments[:500])
    assert lon_ok  # geographic coordinates (Chennai), not pixels
    o, d = (80.2337, 13.0418), (80.2582, 13.0607)
    base = net.evaluate([], o, d)
    route = base["route"]["baseline"]
    assert route["available"] and route["length_m"] > 1000
    mid = route["segments"][len(route["segments"]) // 2]
    failed = net.evaluate([mid], o, d)
    cur = failed["route"]["current"]
    assert mid not in cur["segments"]
    assert (not cur["available"]) or cur["length_m"] >= route["length_m"]  # a closure can never shorten the route
    restored = net.evaluate([], o, d)
    assert restored["route"]["current"] == base["route"]["current"]
    assert restored["network"] == base["network"]
    service.reset_for_tests()
