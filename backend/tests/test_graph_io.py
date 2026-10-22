import json

import networkx as nx
import pytest

from app.graph_io import GraphLoadError, load_graph_file, parse_graph_dict, simplify_polyline, to_networkx

from .conftest import BRIDGE_EDGES, BRIDGE_NODES, phase2_graph


def test_phase2_schema_and_coordinate_conversion():
    doc = parse_graph_dict(phase2_graph("1001", BRIDGE_NODES, BRIDGE_EDGES))
    assert doc.schema == "phase2" and doc.coords_order == "row_col"
    e = doc.edge_index["e_a_b"]
    # stored [row, col] -> output (x, y): endpoints equal the node positions
    assert e.coords[0] == (10.0, 10.0) and e.coords[-1] == (30.0, 10.0)
    assert doc.healing_provenance == "recorded"
    assert [x.id for x in doc.nodes] == list(BRIDGE_NODES)  # IDs preserved, no renumbering
    assert doc.edge_index["e_c_d"].healed is True and e.healed is False


def test_xy_order_is_detected():
    data = phase2_graph("1", {"a": (5, 40), "b": (25, 40)}, [("a", "b", 20, False)])
    data["edges"][0]["coords"] = [[5, 40], [25, 40]]  # already (x, y)
    doc = parse_graph_dict(data)
    assert doc.coords_order == "xy"
    assert doc.edges[0].coords == ((5.0, 40.0), (25.0, 40.0))


def test_attributes_preserved_and_extra_fields_kept():
    data = phase2_graph("1", {"a": (0, 0), "b": (3, 4)}, [("a", "b", 7.5, False)])
    data["nodes"][0]["kind"] = "junction"
    data["edges"][0]["surface"] = "paved"
    doc = parse_graph_dict(data)
    assert doc.node_index["a"].extra == {"kind": "junction"}
    assert doc.node_index["a"].file_degree == 1
    assert doc.edges[0].extra == {"surface": "paved"}
    assert doc.edges[0].length == 7.5 and doc.edges[0].length_source == "weight"
    assert doc.file_stats["num_nodes"] == 2


def test_missing_healed_flag_means_unknown_not_false():
    data = phase2_graph("1", {"a": (0, 0), "b": (3, 4)}, [("a", "b", 5, False)], with_healed=False)
    doc = parse_graph_dict(data)
    assert doc.healing_provenance == "unavailable"
    assert doc.edges[0].healed is None


def test_partial_healing_flags():
    data = phase2_graph("1", {"a": (0, 0), "b": (3, 4), "c": (9, 9)}, [("a", "b", 5, False), ("b", "c", 5, True)])
    del data["edges"][1]["healed"]
    assert parse_graph_dict(data).healing_provenance == "partial"


def test_length_fallbacks():
    data = {"nodes": [{"id": "a", "x": 0, "y": 0}, {"id": "b", "x": 3, "y": 4}, {"id": "c", "x": 3, "y": 10}],
            "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "c", "weight": -2,
                                                         "coords": [[4, 3], [7, 3], [10, 3]]}]}
    doc = parse_graph_dict(data)
    assert doc.edges[0].length == pytest.approx(5.0) and doc.edges[0].length_source == "euclidean"
    assert doc.edges[1].length == pytest.approx(6.0) and doc.edges[1].length_source == "coords"
    assert len(doc.warnings) == 2


def test_dangling_selfloop_and_parallel_edges_are_skipped_with_warnings():
    data = {"nodes": [{"id": "a", "x": 0, "y": 0}, {"id": "b", "x": 1, "y": 0}],
            "edges": [{"source": "a", "target": "b", "weight": 1}, {"source": "b", "target": "a", "weight": 2},
                      {"source": "a", "target": "a", "weight": 1}, {"source": "a", "target": "zz", "weight": 1}]}
    doc = parse_graph_dict(data)
    assert len(doc.edges) == 1 and len(doc.warnings) == 3


def test_node_link_format_and_schematic():
    data = {"nodes": [{"id": 1}, {"id": 2}], "links": [{"source": 1, "target": 2}]}
    doc = parse_graph_dict(data, "x")
    assert doc.schema == "node_link" and not doc.has_positions
    assert doc.nodes[0].id == "1" and doc.edges[0].length_source == "default"


@pytest.mark.parametrize("payload", [[], {"nodes": []}, {"nodes": [{"x": 1}], "edges": []},
                                     {"nodes": [{"id": "a"}, {"id": "a"}], "edges": []}])
def test_invalid_schema(payload):
    with pytest.raises(GraphLoadError) as exc:
        parse_graph_dict(payload)
    assert exc.value.code == "invalid_schema"


def test_corrupt_file(tmp_path):
    p = tmp_path / "x_graph.json"
    p.write_text('{"nodes": [')
    with pytest.raises(GraphLoadError) as exc:
        load_graph_file(p)
    assert exc.value.code == "invalid_json" and "line" in exc.value.message
    with pytest.raises(GraphLoadError) as exc:
        load_graph_file(tmp_path / "missing.json")
    assert exc.value.code == "not_found"


def test_networkx_variants_and_freeze(tmp_path):
    p = tmp_path / "g.json"
    p.write_text(json.dumps(phase2_graph("1001", BRIDGE_NODES, BRIDGE_EDGES)))
    doc = load_graph_file(p)
    healed, original = to_networkx(doc, "healed"), to_networkx(doc, "original")
    assert healed.number_of_edges() == 7 and original.number_of_edges() == 6
    assert nx.number_connected_components(original) == 2
    assert original.number_of_nodes() == healed.number_of_nodes() == 6  # healing adds no nodes
    assert healed.edges["a", "b"]["id"] == "e_a_b"
    with pytest.raises(nx.NetworkXError):
        healed.add_edge("a", "f")


def test_simplify_polyline():
    line = tuple((float(i), 0.0) for i in range(100))
    assert simplify_polyline(line, 0.5) == [(0.0, 0.0), (99.0, 0.0)]
    corner = ((0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (10.0, 5.0), (10.0, 10.0))
    assert simplify_polyline(corner, 0.5) == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    assert simplify_polyline(corner, 0) == list(corner)
