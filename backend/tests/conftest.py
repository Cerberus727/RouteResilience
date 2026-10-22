"""Test fixtures: a throw-away data directory with small synthetic artifacts.

The synthetic graphs are used ONLY by tests, to check formulas against answers
computed by hand. The app never reads them.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config, registry
from app.services import graphs as graph_service
from app.services import notebooks


def phase2_graph(image_id: str, nodes: dict[str, tuple[int, int]], edges: list[tuple[str, str, float, bool]], with_healed=True) -> dict:
    """Build a Phase II-schema graph. nodes: id -> (x, y). Coords stored as [row, col] like Phase II."""
    out_edges = []
    for s, t, w, healed in edges:
        (x1, y1), (x2, y2) = nodes[s], nodes[t]
        e = {"id": f"e_{s}_{t}", "source": s, "target": t, "weight": w,
             "coords": [[y1, x1], [(y1 + y2) // 2, (x1 + x2) // 2], [y2, x2]]}
        if with_healed:
            e["healed"] = healed
        out_edges.append(e)
    return {
        "image_id": image_id, "model": "synth",
        "nodes": [{"id": k, "x": x, "y": y, "degree": sum(1 for e in edges if k in e[:2])} for k, (x, y) in nodes.items()],
        "edges": out_edges,
        "stats": {"num_nodes": len(nodes), "num_edges": len(edges), "connectivity_before": 0.5, "connectivity_after": 1.0,
                  "bridges_added": sum(1 for e in edges if e[3])},
    }


# Two triangles {a,b,c} and {d,e,f} joined by the healed bridge c–d.
BRIDGE_NODES = {"a": (10, 10), "b": (30, 10), "c": (20, 30), "d": (60, 30), "e": (50, 50), "f": (70, 50)}
BRIDGE_EDGES = [("a", "b", 1, False), ("b", "c", 1, False), ("a", "c", 1, False),
                ("c", "d", 1, True),
                ("d", "e", 1, False), ("e", "f", 1, False), ("d", "f", 1, False)]
PATH_NODES = {k: (10 * i + 5, 7) for i, k in enumerate("abcde")}
PATH_EDGES = [(u, v, 1, False) for u, v in zip("abcd", "bcde")]


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    out = tmp_path / "outputs-20990101T000000Z-1-001" / "outputs"
    gdir = out / "graphs_synth"
    gdir.mkdir(parents=True)
    (gdir / "1001_graph.json").write_text(json.dumps(phase2_graph("1001", BRIDGE_NODES, BRIDGE_EDGES)))
    (gdir / "1002_graph.json").write_text(json.dumps(phase2_graph("1002", PATH_NODES, PATH_EDGES, with_healed=False)))
    (gdir / "1003_graph.json").write_text('{"nodes": [ {"id": "a"} ')  # truncated / corrupt
    (gdir / "1004_graph.json").write_text(json.dumps({"hello": "world"}))  # valid JSON, wrong schema
    (gdir / "bad name_graph.json").write_text("{}")  # unsafe name: must be ignored

    mdir = out / "masks_synth"
    mdir.mkdir()
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[10:20, 10:90] = 255  # one component
    mask[50:60, 10:30] = 255  # second component
    Image.fromarray(mask).save(mdir / "1001_pred.png")
    (mdir / "1002_pred.png").write_bytes(b"not a png")

    ck = tmp_path / "checkpoints-20990101T000000Z-1-001" / "checkpoints"
    ck.mkdir(parents=True)
    (ck / "best_road_model_synth.pth").write_bytes(b"not a checkpoint")
    return tmp_path


@pytest.fixture()
def client(data_dir: Path, tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("ROUTERESILIENCE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ROUTERESILIENCE_NOTEBOOKS_DIR", str(data_dir))  # no notebooks there
    monkeypatch.setenv("ROUTERESILIENCE_STATE_DIR", str(tmp_path / "state"))
    config.get_settings.cache_clear()
    registry.reset_for_tests(config.get_settings())
    graph_service.clear_cache()
    notebooks._cache.clear()
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c
    config.get_settings.cache_clear()
    graph_service.clear_cache()
    registry._registry = None  # next access rescans with the real environment
