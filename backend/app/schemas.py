"""Pydantic request / response models for the public API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Variant = Literal["healed", "original"]
ID_PATTERN = r"^[A-Za-z0-9_#\-]{1,64}$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------- requests ----------------
class ShortestPathRequest(Strict):
    source: str = Field(pattern=ID_PATTERN)
    target: str = Field(pattern=ID_PATTERN)
    weight: Literal["length", "hops"] = "length"
    variant: Variant = "healed"


class SimulationRequest(Strict):
    """Either list explicit removals, or pick a predefined strategy."""

    remove_nodes: list[str] = Field(default_factory=list, max_length=500)
    remove_edges: list[str] = Field(default_factory=list, max_length=500)
    mode: Literal["single", "sequential"] = "single"
    strategy: Literal["none", "betweenness_static", "betweenness_adaptive"] = "none"
    k: int = Field(default=5, ge=1, le=100, description="Number of nodes for a predefined strategy.")
    variant: Variant = "healed"

    @field_validator("remove_nodes", "remove_edges")
    @classmethod
    def _ids(cls, v: list[str]) -> list[str]:
        import re

        bad = [x for x in v if not re.match(ID_PATTERN, x)]
        if bad:
            raise ValueError(f"invalid id(s): {bad[:5]}")
        if len(set(v)) != len(v):
            raise ValueError("duplicate ids are not allowed")
        return v


class ReviewRequest(Strict):
    decision: Literal["approved", "rejected", "unreviewed"]
    note: str | None = Field(default=None, max_length=2000)


class ReportRequest(Strict):
    format: Literal["md", "html"] = "md"
    variant: Variant = "healed"
    simulation: SimulationRequest | None = None


# ---------------- responses ----------------
class Metrics(BaseModel):
    nodes: int
    edges: int
    baseline_nodes: int
    components: int
    isolated_nodes: int
    lcc_size: int
    lcc_fraction: float | None
    reachable_pairs: int
    total_pairs: int
    reachable_pair_fraction: float | None
    avg_path_length: float | None
    efficiency: float | None
    density: float | None
    avg_degree: float | None
    total_length: float


class NodeOut(BaseModel):
    id: str
    x: float
    y: float
    degree: int
    component: int
    betweenness: float
    rank: int


class EdgeOut(BaseModel):
    id: str
    source: str
    target: str
    length: float
    length_source: str
    healed: bool | None
    coords: list[tuple[float, float]] | None = None
    review: str | None = None


class GraphSummary(BaseModel):
    graph_id: str
    set_id: str
    image_id: str
    nodes: int | None = None
    edges: int | None = None
    healed_edges: int | None = None
    error: str | None = None


class GraphDetail(BaseModel):
    graph_id: str
    set_id: str
    image_id: str
    variant: Variant
    schema_name: str
    model_tag: str | None
    frame: dict[str, Any]
    layout: Literal["pixel", "schematic"]
    healing_provenance: str
    coords_order: str
    nodes: list[NodeOut]
    edges: list[EdgeOut]
    metrics: Metrics
    component_sizes: list[int]
    degree_histogram: list[int]
    file_stats: dict[str, Any] | None
    provenance: dict[str, Any]
    warnings: list[str]
    underlay: dict[str, Any] | None
