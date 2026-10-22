"""Metric formulas on small graphs with answers worked out by hand."""

import math

import networkx as nx
import pytest

from app import analysis


def graph(edges, nodes=()):
    G = nx.Graph()
    G.add_nodes_from(nodes)
    for i, (u, v, *w) in enumerate(edges):
        G.add_edge(u, v, id=f"e{i}_{u}{v}", length=float(w[0]) if w else 1.0, healed=False)
    return nx.freeze(G)


@pytest.fixture()
def path5():  # a-b-c-d-e, unit lengths
    return graph([("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")])


@pytest.fixture()
def star():  # hub h with 4 leaves
    return graph([("h", x) for x in "pqrs"])


@pytest.fixture()
def bridge():  # triangles abc and def joined by c-d
    return graph([("a", "b"), ("b", "c"), ("a", "c"), ("c", "d"), ("d", "e"), ("e", "f"), ("d", "f")])


def test_path_baseline_metrics(path5):
    m = analysis.compute_metrics(path5)
    assert (m.nodes, m.edges, m.components) == (5, 4, 1)
    assert m.reachable_pairs == 10 and m.reachable_pair_fraction == 1.0
    assert m.avg_path_length == pytest.approx(2.0)  # (4*1 + 3*2 + 2*3 + 1*4) / 10
    assert m.efficiency == pytest.approx((4 + 3 / 2 + 2 / 3 + 1 / 4) / 10)
    assert m.lcc_fraction == 1.0
    assert m.density == pytest.approx(4 / 10)


def test_path_betweenness(path5):
    bc = analysis.betweenness(path5)
    assert bc["c"] == pytest.approx(4 / 6)  # (a,d) (a,e) (b,d) (b,e) over C(4,2)
    assert bc["b"] == pytest.approx(3 / 6)
    assert bc["a"] == 0.0
    assert analysis.rank_nodes(path5, bc)[0] == "c"


def test_removing_path_middle_splits_network(path5):
    base = analysis.compute_metrics(path5)
    after = analysis.compute_metrics(analysis.remove_elements(path5, nodes=["c"]), base.nodes)
    assert after.components == 2
    assert after.lcc_fraction == pytest.approx(2 / 5)  # normalized by baseline N0
    assert after.reachable_pairs == 2 and after.reachable_pair_fraction == pytest.approx(0.2)
    assert after.avg_path_length == pytest.approx(1.0)  # only finite pairs
    assert after.efficiency == pytest.approx(0.2)
    cmp = analysis.compare(base, after)
    assert cmp["efficiency_retention"] == pytest.approx(0.2 / base.efficiency)
    assert cmp["degradation"] == pytest.approx(1 - 0.2 / base.efficiency)
    # Fragmentation LOWERS the reachable-pairs average path length, which is why the
    # legacy ratio L_base/L_after would wrongly report this as "more resilient".
    assert after.avg_path_length < base.avg_path_length
    assert cmp["efficiency_retention"] < 1


def test_star_hub_and_leaf_removal(star):
    bc = analysis.betweenness(star)
    assert bc["h"] == pytest.approx(1.0)
    assert all(bc[x] == 0 for x in "pqrs")
    base = analysis.compute_metrics(star)
    hub = analysis.compute_metrics(analysis.remove_elements(star, nodes=["h"]), base.nodes)
    assert hub.components == 4 and hub.isolated_nodes == 4
    assert hub.reachable_pairs == 0 and hub.avg_path_length is None  # no finite pair: None, never inf
    assert hub.efficiency == 0.0
    assert analysis.compare(base, hub)["efficiency_retention"] == 0.0
    leaf = analysis.compute_metrics(analysis.remove_elements(star, nodes=["p"]), base.nodes)
    assert leaf.components == 1 and leaf.reachable_pair_fraction == pytest.approx(6 / 10)


def test_bridge_graph(bridge):
    bc = analysis.betweenness(bridge)
    top2 = analysis.rank_nodes(bridge, bc)[:2]
    assert set(top2) == {"c", "d"}
    assert bc["c"] == pytest.approx(bc["d"])
    base = analysis.compute_metrics(bridge)
    bridge_edge = next(d["id"] for u, v, d in bridge.edges(data=True) if {u, v} == {"c", "d"})
    cut = analysis.compute_metrics(analysis.remove_elements(bridge, edges=[bridge_edge]), base.nodes)
    assert cut.components == 2 and cut.nodes == 6
    assert cut.reachable_pair_fraction == pytest.approx(6 / 15)
    # A non-bridge triangle edge keeps the network connected
    inner = next(d["id"] for u, v, d in bridge.edges(data=True) if {u, v} == {"a", "b"})
    kept = analysis.compute_metrics(analysis.remove_elements(bridge, edges=[inner]), base.nodes)
    assert kept.components == 1 and kept.reachable_pair_fraction == 1.0
    assert kept.efficiency < base.efficiency


def test_disconnected_baseline_ignores_infinite_pairs():
    G = graph([("a", "b"), ("c", "d", 3)])
    m = analysis.compute_metrics(G)
    assert m.components == 2
    assert m.avg_path_length == pytest.approx((1 + 3) / 2)
    assert m.efficiency == pytest.approx((2 * 1 + 2 * (1 / 3)) / 12)
    assert math.isfinite(m.avg_path_length)


def test_component_membership_is_deterministic():
    G = graph([("a", "b"), ("x", "y"), ("y", "z")], nodes=["q"])
    mem, sizes = analysis.component_membership(G)
    assert sizes == [3, 2, 1]
    assert mem["x"] == 0 and mem["a"] == 1 and mem["q"] == 2


def test_lcc_scope_ignores_small_components():
    G = graph([("a", "b"), ("b", "c"), ("x", "y"), ("y", "z"), ("z", "w")])
    bc_l = analysis.betweenness(G, "lcc")
    assert bc_l["b"] == 0.0  # not in LCC
    assert bc_l["y"] == pytest.approx(2 / 3)  # path of 4 nodes: (x,z)(x,w) over C(3,2)


def test_simulation_does_not_mutate_original(bridge):
    before_nodes, before_edges = sorted(bridge.nodes), sorted(bridge.edges(data="id"))
    analysis.remove_elements(bridge, nodes=["c"], edges=[next(iter(analysis.edge_lookup(bridge)))])
    analysis.run_steps(bridge, None, analysis.compute_metrics(bridge), 5000, strategy="betweenness_adaptive", k=3)
    assert sorted(bridge.nodes) == before_nodes and sorted(bridge.edges(data="id")) == before_edges
    with pytest.raises(nx.NetworkXError):
        bridge.remove_node("a")  # cached graphs are frozen


def test_unknown_targets_rejected(path5):
    with pytest.raises(analysis.InvalidTargetError):
        analysis.remove_elements(path5, nodes=["zz"])
    with pytest.raises(analysis.InvalidTargetError):
        analysis.run_steps(path5, [("edge", "nope")], analysis.compute_metrics(path5), 5000)


def test_sequential_steps_are_monotone(bridge):
    base = analysis.compute_metrics(bridge)
    steps, H = analysis.run_steps(bridge, None, base, 5000, strategy="betweenness_static", k=4)
    retention = [s["efficiency_retention"] for s in steps]
    assert all(0 <= r <= 1 for r in retention)
    assert retention == sorted(retention, reverse=True)
    assert steps[0]["removed"] in {"c", "d"}
    assert H.number_of_nodes() == 2


def test_adaptive_strategy_recomputes(path5):
    base = analysis.compute_metrics(path5)
    steps, _ = analysis.run_steps(path5, None, base, 5000, strategy="betweenness_adaptive", k=2)
    assert steps[0]["removed"] == "c"
    # after removing c, components {a,b} and {d,e} have betweenness 0 everywhere; tie broken by degree then id
    assert steps[1]["removed"] == "a"


def test_edge_then_endpoint_removal_noted():
    G = graph([("a", "b"), ("b", "c")])
    eid = next(d["id"] for u, v, d in G.edges(data=True) if {u, v} == {"a", "b"})
    steps, H = analysis.run_steps(G, [("node", "a"), ("edge", eid)], analysis.compute_metrics(G), 5000)
    assert steps[1]["note"] and H.number_of_edges() == 1


def test_too_large_guard(path5):
    with pytest.raises(analysis.GraphTooLargeError):
        analysis.compute_metrics(path5, max_nodes=3)


def test_relative_change_handles_zero_and_none():
    assert analysis.relative_change(0, 5) is None
    assert analysis.relative_change(None, 5) is None
    assert analysis.relative_change(4, 2) == -0.5
