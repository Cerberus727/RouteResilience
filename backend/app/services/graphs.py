"""Loads graphs through the registry and caches immutable derived data."""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

import networkx as nx

from .. import analysis
from ..config import get_settings
from ..graph_io import GraphDoc, GraphLoadError, Variant, load_graph_file, to_networkx
from ..registry import get_registry

T = TypeVar("T")


class GraphNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class LoadedGraph:
    graph_id: str
    set_id: str
    image_id: str
    path: Path
    version: tuple[int, int]  # (mtime_ns, size) — cache key component
    doc: GraphDoc
    healed: nx.Graph  # frozen
    original: nx.Graph  # frozen (healed edges removed)

    def graph(self, variant: Variant) -> nx.Graph:
        return self.original if variant == "original" else self.healed


_lock = threading.Lock()
_graphs: OrderedDict[tuple, LoadedGraph] = OrderedDict()
_derived: OrderedDict[tuple, object] = OrderedDict()
_MAX_GRAPHS = 64
_MAX_DERIVED = 512


def _evict(cache: OrderedDict, limit: int) -> None:
    while len(cache) > limit:
        cache.popitem(last=False)


def clear_cache() -> None:
    with _lock:
        _graphs.clear()
        _derived.clear()


def get_graph(graph_id: str) -> LoadedGraph:
    found = get_registry().graph_path(graph_id)
    if not found:
        raise GraphNotFoundError(f"Unknown graph id '{graph_id}'.")
    set_id, image_id, path = found
    try:
        st = path.stat()
    except OSError as exc:
        raise GraphLoadError("not_found", f"Graph file is no longer on disk: {path.name}") from exc
    key = (str(path), st.st_mtime_ns, st.st_size)
    with _lock:
        if key in _graphs:
            _graphs.move_to_end(key)
            return _graphs[key]
    doc = load_graph_file(path, fallback_image_id=image_id)
    lg = LoadedGraph(
        graph_id=graph_id,
        set_id=set_id,
        image_id=image_id,
        path=path,
        version=(st.st_mtime_ns, st.st_size),
        doc=doc,
        healed=to_networkx(doc, "healed"),
        original=to_networkx(doc, "original"),
    )
    with _lock:
        _graphs[key] = lg
        _evict(_graphs, _MAX_GRAPHS)
    return lg


def _memo(key: tuple, fn: Callable[[], T]) -> T:
    with _lock:
        if key in _derived:
            _derived.move_to_end(key)
            return _derived[key]  # type: ignore[return-value]
    value = fn()
    with _lock:
        _derived[key] = value
        _evict(_derived, _MAX_DERIVED)
    return value


def baseline_metrics(lg: LoadedGraph, variant: Variant) -> analysis.NetworkMetrics:
    max_nodes = get_settings().max_graph_nodes
    m = _memo((lg.graph_id, lg.version, variant, "metrics"), lambda: analysis.compute_metrics(lg.graph(variant), None, max_nodes))
    return analysis.NetworkMetrics(**m.to_dict())  # copy: callers may not alter the cached value


def betweenness(lg: LoadedGraph, variant: Variant, scope: str = "full") -> dict[str, float]:
    bc = _memo((lg.graph_id, lg.version, variant, "bc", scope), lambda: analysis.betweenness(lg.graph(variant), scope))
    return dict(bc)


def membership(lg: LoadedGraph, variant: Variant) -> tuple[dict[str, int], list[int]]:
    mem, sizes = _memo((lg.graph_id, lg.version, variant, "cc"), lambda: analysis.component_membership(lg.graph(variant)))
    return dict(mem), list(sizes)
