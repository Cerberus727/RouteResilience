"""Runtime configuration, read from environment variables (and an optional `.env`).

Nothing here hardcodes a machine-specific absolute path: the default data
directory is the repository root (the parent of `backend/`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PREFIX = "ROUTERESILIENCE_"


def _load_dotenv(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser; real environment variables always win."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _optional_path(value: str | None) -> Path | None:
    return Path(value).expanduser().resolve() if value else None


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    outputs_dir: Path | None = None  # explicit override of the timestamped outputs folder
    checkpoints_dir: Path | None = None  # explicit override of the timestamped checkpoints folder
    notebooks_dir: Path | None = None  # defaults to data_dir
    state_dir: Path = field(default_factory=lambda: REPO_ROOT / "backend" / "state")
    frontend_dist: Path = field(default_factory=lambda: REPO_ROOT / "frontend" / "dist")
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    # Limits that keep a single request bounded.
    max_graph_nodes: int = 5000  # graphs above this are refused by all-pairs metrics
    max_removals: int = 200  # nodes + edges per simulation request
    max_sequential_steps: int = 50
    max_top_k: int = 100
    max_impact_k: int = 25
    # Geographic road network (OpenStreetMap)
    osm_pbf: Path | None = None  # defaults to the first *.osm.pbf in data_dir
    cache_dir: Path = field(default_factory=lambda: REPO_ROOT / ".cache" / "routeresilience")
    osm_extent: str = "80.15,12.95,80.32,13.16"  # index extent (central Chennai) — min_lon,min_lat,max_lon,max_lat
    default_region: str = "80.215,13.02,80.265,13.065"  # first region loaded in the map (T. Nagar – Mylapore – Egmore)
    max_region_segments: int = 80_000
    max_region_span_deg: float = 0.25
    betweenness_sources: int = 160
    # DeepGlobe road dataset (segmentation lab)
    deepglobe_dir: Path | None = None  # defaults to <data_dir>/deepgloberoad


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env = {**_load_dotenv(REPO_ROOT / ".env"), **os.environ}

    def get(name: str) -> str | None:
        value = env.get(ENV_PREFIX + name)
        return value if value not in (None, "") else None

    data_dir = _optional_path(get("DATA_DIR")) or REPO_ROOT
    kwargs: dict = {
        "data_dir": data_dir,
        "outputs_dir": _optional_path(get("OUTPUTS_DIR")),
        "checkpoints_dir": _optional_path(get("CHECKPOINTS_DIR")),
        "notebooks_dir": _optional_path(get("NOTEBOOKS_DIR")),
    }
    if get("STATE_DIR"):
        kwargs["state_dir"] = _optional_path(get("STATE_DIR"))
    if get("CORS_ORIGINS"):
        kwargs["cors_origins"] = tuple(o.strip() for o in get("CORS_ORIGINS").split(",") if o.strip())
    pbf = _optional_path(get("OSM_PBF"))
    if pbf is None:
        found = sorted(data_dir.glob("*.osm.pbf")) if data_dir.is_dir() else []
        pbf = found[0] if found else None
    kwargs["osm_pbf"] = pbf
    if get("CACHE_DIR"):
        kwargs["cache_dir"] = _optional_path(get("CACHE_DIR"))
    for key, name in (("OSM_EXTENT", "osm_extent"), ("DEFAULT_REGION", "default_region")):
        if get(key):
            kwargs[name] = get(key)
    if get("MAX_REGION_SEGMENTS"):
        kwargs["max_region_segments"] = int(get("MAX_REGION_SEGMENTS"))
    kwargs["deepglobe_dir"] = _optional_path(get("DEEPGLOBE_DIR")) or (data_dir / "deepgloberoad")
    if get("MAX_GRAPH_NODES"):
        kwargs["max_graph_nodes"] = int(get("MAX_GRAPH_NODES"))
    return Settings(**kwargs)
