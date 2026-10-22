import csv
import io
import json

import pytest


def test_health_and_discovery(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok"
    assert h["counts"]["graph_files"] == 4  # 'bad name_graph.json' ignored
    assert any("unsupported name" in w for w in h["warnings"])
    assert h["notebooks"] == {}


def test_list_graphs_reports_corrupt_files(client):
    rows = {r["graph_id"]: r for r in client.get("/api/graphs").json()}
    assert rows["synth-1001"]["nodes"] == 6 and rows["synth-1001"]["healed_edges"] == 1
    assert rows["synth-1003"]["error"].startswith("invalid_json")
    assert rows["synth-1004"]["error"].startswith("invalid_schema")


def test_graph_detail(client):
    g = client.get("/api/graphs/synth-1001").json()
    assert g["metrics"]["components"] == 1 and g["metrics"]["nodes"] == 6
    assert g["healing_provenance"] == "recorded"
    assert g["underlay"]["mask_set"] == "synth" and g["frame"] == {"width": 100, "height": 100, "source": "mask"}
    assert {n["id"] for n in g["nodes"]} == set("abcdef")
    assert g["nodes"][0].keys() >= {"betweenness", "component", "rank", "degree"}
    top = min(g["nodes"], key=lambda n: n["rank"])
    assert top["id"] in {"c", "d"}
    edge = next(e for e in g["edges"] if e["id"] == "e_a_b")
    assert edge["coords"][0] == [10, 10]
    orig = client.get("/api/graphs/synth-1001?variant=original").json()
    assert orig["metrics"]["components"] == 2 and len(orig["edges"]) == 6


@pytest.mark.parametrize("gid,status,code", [
    ("synth-9999", 404, "graph_not_found"),
    ("nope", 404, "graph_not_found"),
    ("synth-1003", 422, "artifact_invalid_json"),
    ("synth-1004", 422, "artifact_invalid_schema"),
])
def test_graph_errors(client, gid, status, code):
    r = client.get(f"/api/graphs/{gid}")
    assert r.status_code == status and r.json()["code"] == code


def test_path_traversal_is_impossible(client):
    for url in ["/api/masks/synth/..%2F..%2Fsecret.png", "/api/masks/..%2Fsynth/1001.png",
                "/api/figures/..%2F..%2Fx", "/api/graphs/synth-..%2F1001", "/api/samples/..%2Fx"]:
        r = client.get(url)
        assert r.status_code in (400, 404), url
    assert client.get("/api/masks/synth/1001.png").headers["content-type"] == "image/png"


def test_node_detail_and_missing_node(client):
    n = client.get("/api/graphs/synth-1001/nodes/c").json()
    assert n["degree"] == 3 and {x["id"] for x in n["neighbors"]} == {"a", "b", "d"}
    assert n["impact"]["components_after"] == 2
    assert client.get("/api/graphs/synth-1001/nodes/zz").status_code == 404


def test_critical_nodes(client):
    r = client.get("/api/graphs/synth-1001/critical-nodes?top_k=3&impact_k=2").json()
    assert [n["rank"] for n in r["nodes"]] == [1, 2, 3]
    assert {r["nodes"][0]["id"], r["nodes"][1]["id"]} == {"c", "d"}
    assert "impact" in r["nodes"][1] and "impact" not in r["nodes"][2]
    assert "not a probability" in r["interpretation"]
    assert client.get("/api/graphs/synth-1001/critical-nodes?top_k=0").status_code == 422
    assert client.get("/api/graphs/synth-1001/critical-nodes?scope=bogus").status_code == 422


def test_shortest_path(client):
    p = client.post("/api/graphs/synth-1001/shortest-path", json={"source": "a", "target": "f"}).json()
    assert p["reachable"] and p["nodes"][0] == "a" and p["nodes"][-1] == "f" and p["length"] == 3 and p["healed_edges_used"] == 1
    q = client.post("/api/graphs/synth-1001/shortest-path", json={"source": "a", "target": "f", "variant": "original"}).json()
    assert q["reachable"] is False and "component" in q["reason"] and q["length"] is None
    assert client.post("/api/graphs/synth-1001/shortest-path", json={"source": "a", "target": "zz"}).status_code == 404
    assert client.post("/api/graphs/synth-1001/shortest-path", json={"source": "a; rm", "target": "b"}).status_code == 422


def test_simulation_and_original_unchanged(client):
    before = client.get("/api/graphs/synth-1001").json()["metrics"]
    r = client.post("/api/graphs/synth-1001/simulate-failure", json={"remove_edges": ["e_c_d"]})
    assert r.status_code == 200
    res = r.json()
    assert res["final"]["components"] == 2 and res["comparison"]["changes"]["components"]["delta"] == 1
    assert res["final"]["reachable_pair_fraction"] == pytest.approx(6 / 15)
    assert res["removed_edges"] == ["e_c_d"] and res["removed_nodes"] == []
    assert 0 <= res["comparison"]["efficiency_retention"] < 1
    # sequential + strategy
    s = client.post("/api/graphs/synth-1001/simulate-failure", json={"strategy": "betweenness_static", "k": 3}).json()
    assert len(s["steps"]) == 3 and s["mode"] == "sequential"
    after = client.get("/api/graphs/synth-1001").json()["metrics"]
    assert before == after  # stored/cached graph untouched


@pytest.mark.parametrize("body,status", [
    ({}, 400),  # nothing to remove
    ({"remove_nodes": ["zz"]}, 400),
    ({"remove_nodes": ["a"], "strategy": "betweenness_static"}, 400),
    ({"remove_nodes": ["a", "a"]}, 422),
    ({"remove_nodes": ["../etc"]}, 422),
    ({"remove_nodes": ["a"], "bogus": 1}, 422),
    ({"strategy": "betweenness_static", "k": 1000}, 422),
    ({"remove_nodes": [f"n{i}" for i in range(501)]}, 422),
])
def test_simulation_validation(client, body, status):
    assert client.post("/api/graphs/synth-1001/simulate-failure", json=body).status_code == status


def test_exports_match_api(client):
    g = client.get("/api/graphs/synth-1001").json()
    nodes = list(csv.DictReader(io.StringIO(client.get("/api/graphs/synth-1001/export?format=csv&part=nodes").text)))
    assert {r["id"] for r in nodes} == {n["id"] for n in g["nodes"]}
    by_id = {n["id"]: n for n in g["nodes"]}
    for r in nodes:
        assert float(r["betweenness"]) == pytest.approx(by_id[r["id"]]["betweenness"])
        assert int(r["degree"]) == by_id[r["id"]]["degree"]
    edges = list(csv.DictReader(io.StringIO(client.get("/api/graphs/synth-1001/export?format=csv&part=edges").text)))
    assert len(edges) == 7 and sum(r["healed"] == "true" for r in edges) == 1
    metrics = list(csv.DictReader(io.StringIO(client.get("/api/graphs/synth-1001/export?format=csv&part=metrics").text)))
    assert int(metrics[0]["components"]) == 1 and float(metrics[0]["efficiency"]) == pytest.approx(g["metrics"]["efficiency"])
    full = client.get("/api/graphs/synth-1001/export?format=json").json()
    assert full["metrics"] == g["metrics"] and full["definitions"]
    r = client.get("/api/graphs/synth-1001/export?format=xml")
    assert r.status_code == 422


def test_simulation_export_csv(client):
    r = client.post("/api/graphs/synth-1001/simulate-failure/export?format=csv", json={"remove_nodes": ["c", "d"], "mode": "sequential"})
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [row["step"] for row in rows] == ["0", "1", "2"] and rows[0]["kind"] == "baseline"
    assert rows[2]["components"] == "2"  # {a,b} and {e,f} remain


def test_report(client):
    md = client.get("/api/graphs/synth-1001/report?format=md").text
    assert "# RouteResilience report — synth-1001" in md and "Metric definitions" in md
    assert "not a probability" in md
    html = client.post("/api/graphs/synth-1001/report",
                       json={"format": "html", "simulation": {"remove_nodes": ["c"]}}).text
    assert html.startswith("<!doctype html>") and "Failure simulation" in html and "<table>" in html


def test_healing_review_persistence(client, tmp_path):
    h = client.get("/api/graphs/synth-1001/healing").json()
    assert h["counts"]["healed_edges"] == 1 and h["healed_edges"][0]["id"] == "e_c_d"
    assert h["metrics_original"]["components"] == 2 and h["metrics_healed"]["components"] == 1
    r = client.put("/api/graphs/synth-1001/healing/e_c_d/review", json={"decision": "rejected", "note": "crosses a river"})
    assert r.status_code == 200 and r.json()["review"]["decision"] == "rejected"
    store = json.loads((tmp_path / "state" / "healing_reviews.json").read_text())
    assert store["reviews"]["synth-1001"]["e_c_d"]["note"] == "crosses a river"
    h2 = client.get("/api/graphs/synth-1001/healing").json()
    assert h2["counts"]["rejected"] == 1 and h2["metrics_reviewed"]["components"] == 2
    assert h2["healed_edges"][0]["review_stale"] is False
    # graph artifact itself is unchanged
    assert client.get("/api/graphs/synth-1001").json()["metrics"]["components"] == 1
    # clearing
    client.put("/api/graphs/synth-1001/healing/e_c_d/review", json={"decision": "unreviewed"})
    assert client.get("/api/graphs/synth-1001/healing").json()["counts"]["unreviewed"] == 1
    # an original road segment cannot be reviewed; unknown edge 404; no provenance 409
    assert client.put("/api/graphs/synth-1001/healing/e_a_b/review", json={"decision": "approved"}).status_code == 400
    assert client.put("/api/graphs/synth-1001/healing/zz/review", json={"decision": "approved"}).status_code == 404
    assert client.put("/api/graphs/synth-1002/healing/e_a_b/review", json={"decision": "approved"}).status_code == 409
    assert client.put("/api/graphs/synth-1001/healing/e_c_d/review", json={"decision": "maybe"}).status_code == 422


def test_healing_without_provenance(client):
    h = client.get("/api/graphs/synth-1002/healing").json()
    assert h["healing_provenance"] == "unavailable" and h["healed_edges"] == []
    assert "No bridge list can be shown" in h["provenance_note"]


def test_corrupt_review_store_is_not_overwritten(client, tmp_path):
    p = tmp_path / "state" / "healing_reviews.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{oops")
    r = client.put("/api/graphs/synth-1001/healing/e_c_d/review", json={"decision": "approved"})
    assert r.status_code == 500 and r.json()["code"] == "review_store_error"
    assert p.read_text() == "{oops"


def test_models_and_samples_without_notebooks(client):
    models = {m["id"]: m for m in client.get("/api/models").json()}
    assert "synth" in models and models["synth"]["mask_count"] == 2
    m = client.get("/api/models/synth/metrics").json()
    assert m["training_history"] is None and m["evaluation"]["ground_truth_available"] is False
    ck = client.get("/api/models/synth/checkpoint").json()
    assert ck["compatibility"]["loadable"] is False and ck["compatibility"]["diagnostic"]
    s = client.get("/api/samples/1001").json()
    assert s["masks"][0]["stats"]["components"] == 2 and s["ground_truth_available"] is False
    bad = client.get("/api/samples/1002").json()
    assert "error" in bad["masks"][0]["stats"]  # corrupt PNG reported, not crashed
    assert client.get("/api/samples/424242").status_code == 404
    assert client.get("/api/models/nope").status_code == 404


def test_experiments_and_overview(client):
    exps = client.get("/api/experiments").json()
    ids = {e["id"] for e in exps}
    assert "graphs-synth" in ids and not any(e["kind"] == "training" for e in exps)  # no notebook -> no training rows
    detail = client.get("/api/experiments/graphs-synth").json()
    assert len(detail["rows"]) == 2 and len(detail["errors"]) == 2
    assert client.get("/api/experiments/nope").status_code == 404
    ov = client.get("/api/overview").json()
    gs = ov["graph_sets"][0]
    assert gs["graphs_ok"] == 2 and gs["graphs_failed"] == 2 and gs["nodes"] == 11
    assert client.get("/api/definitions").json()


def test_missing_outputs_directory(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import config, registry
    from app.main import create_app

    monkeypatch.setenv("ROUTERESILIENCE_DATA_DIR", str(tmp_path / "empty"))
    monkeypatch.setenv("ROUTERESILIENCE_STATE_DIR", str(tmp_path / "state"))
    config.get_settings.cache_clear()
    registry.reset_for_tests(config.get_settings())
    try:
        with TestClient(create_app()) as c:
            h = c.get("/api/health").json()
            assert h["status"] == "degraded" and h["counts"]["graph_files"] == 0
            assert c.get("/api/graphs").json() == []
            ov = c.get("/api/overview").json()
            assert ov["default_graph_id"] is None and ov["graph_sets"] == []
    finally:
        config.get_settings.cache_clear()
        registry._registry = None
