"""Consistency checks against the real repository artifacts (skipped when absent)."""

import json

import networkx as nx
import pytest

from app import analysis, config, registry
from app.graph_io import load_graph_file, to_networkx
from app.services import graphs as graph_service


@pytest.fixture(scope="module")
def reg():
    config.get_settings.cache_clear()
    registry._registry = None
    graph_service.clear_cache()
    r = registry.get_registry()
    if not r.graph_sets:
        pytest.skip("real artifacts not present")
    return r


def test_every_graph_loads_and_matches_stored_stats(reg):
    for set_id, files in reg.graph_sets.items():
        for image_id, path in files.items():
            doc = load_graph_file(path, image_id)
            assert doc.healing_provenance == "recorded", path
            assert doc.coords_order == "row_col", path
            st = doc.file_stats
            assert st["num_nodes"] == len(doc.nodes) and st["num_edges"] == len(doc.edges)
            for variant, key in (("original", "connectivity_before"), ("healed", "connectivity_after")):
                G = to_networkx(doc, variant)
                ratio = len(max(nx.connected_components(G), key=len)) / G.number_of_nodes()
                assert round(ratio, 4) == pytest.approx(st[key], abs=1e-4), (path, variant)


def test_phase3_betweenness_is_reproduced(reg):
    checked = 0
    for set_id, analyses in reg.analysis_sets.items():
        for image_id, apath in analyses.items():
            stored = json.loads(apath.read_text())
            G = to_networkx(load_graph_file(reg.graph_sets[set_id][image_id]), "healed")
            bc = analysis.betweenness(G, scope="lcc")
            for gk in stored["gatekeepers"]:
                assert bc[gk["id"]] == pytest.approx(gk["betweenness"], abs=1e-3)
            checked += 1
    assert checked > 0
