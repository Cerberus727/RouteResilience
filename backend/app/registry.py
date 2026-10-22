"""Artifact registry: discovers pipeline outputs and maps safe IDs to validated paths.

API parameters never become filesystem paths directly. Every file the API can
serve is listed here at scan time, and requests are resolved by dictionary
lookup on IDs that match a strict pattern.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings, get_settings

SAFE_ID = re.compile(r"^[A-Za-z0-9_]+$")
GRAPH_ID = re.compile(r"^([a-z0-9_]+)-([A-Za-z0-9_]+)$")
TIMESTAMP = re.compile(r"(\d{8}T\d{6}Z)")


@dataclass(frozen=True)
class FigureInfo:
    figure_id: str
    path: Path
    kind: str  # predictions | training_curves | phase2 | criticality | criticality_metrics | synthetic | sam_comparison | sweep_grid
    title: str
    set_id: str | None = None
    image_id: str | None = None


@dataclass
class Registry:
    data_dir: Path
    outputs_root: Path | None
    checkpoints_root: Path | None
    outputs_candidates: list[Path] = field(default_factory=list)
    checkpoints_candidates: list[Path] = field(default_factory=list)
    notebooks: dict[str, Path] = field(default_factory=dict)  # phase1/phase2/phase3 -> path
    graph_sets: dict[str, dict[str, Path]] = field(default_factory=dict)
    mask_sets: dict[str, dict[str, Path]] = field(default_factory=dict)
    analysis_sets: dict[str, dict[str, Path]] = field(default_factory=dict)
    analysis_csv: dict[str, Path] = field(default_factory=dict)
    figures: dict[str, FigureInfo] = field(default_factory=dict)
    checkpoints: dict[str, Path] = field(default_factory=dict)  # model key -> .pth
    warnings: list[str] = field(default_factory=list)

    # ---- lookups -------------------------------------------------------
    def graph_path(self, graph_id: str) -> tuple[str, str, Path] | None:
        m = GRAPH_ID.match(graph_id)
        if not m:
            return None
        set_id, image_id = m.group(1), m.group(2)
        path = self.graph_sets.get(set_id, {}).get(image_id)
        return (set_id, image_id, path) if path else None

    def all_graph_ids(self) -> list[str]:
        return [f"{s}-{i}" for s, files in sorted(self.graph_sets.items()) for i in _sorted_ids(files)]

    def counts(self) -> dict[str, int]:
        return {
            "graph_sets": len(self.graph_sets),
            "graph_files": sum(len(v) for v in self.graph_sets.values()),
            "mask_sets": len(self.mask_sets),
            "mask_files": sum(len(v) for v in self.mask_sets.values()),
            "analysis_files": sum(len(v) for v in self.analysis_sets.values()),
            "figures": len(self.figures),
            "checkpoints": len(self.checkpoints),
            "notebooks": len(self.notebooks),
        }


def _sorted_ids(ids) -> list[str]:
    return sorted(ids, key=lambda s: (0, int(s)) if s.isdigit() else (1, s))


def _timestamp_key(path: Path) -> tuple[str, float]:
    m = TIMESTAMP.search(path.name)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (m.group(1) if m else "", mtime)


def _discover_root(data_dir: Path, prefix: str, looks_valid) -> tuple[Path | None, list[Path]]:
    """Find `<prefix>` or `<prefix>-<timestamp>...` folders (optionally with a nested
    `<prefix>/` folder, as produced by Google Drive downloads) and pick the newest."""
    candidates: list[Path] = []
    if not data_dir.is_dir():
        return None, []
    for entry in data_dir.iterdir():
        if not entry.is_dir() or not (entry.name == prefix or entry.name.startswith(prefix + "-")):
            continue
        for cand in (entry / prefix, entry):
            if cand.is_dir() and looks_valid(cand):
                candidates.append(cand)
                break
    if not candidates:
        return None, []
    candidates.sort(key=lambda p: _timestamp_key(p if p.name != prefix else p.parent), reverse=True)
    return candidates[0], candidates


def _looks_like_outputs(path: Path) -> bool:
    return any(p.is_dir() and p.name.startswith(("graphs_", "masks_", "analysis_")) for p in path.iterdir())


def _looks_like_checkpoints(path: Path) -> bool:
    return any(p.suffix in (".pth", ".pt") for p in path.iterdir())


def _index_dir(directory: Path, suffix: str, warnings: list[str]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for f in directory.iterdir():
        if not f.is_file() or not f.name.endswith(suffix):
            continue
        image_id = f.name[: -len(suffix)]
        if not SAFE_ID.match(image_id):
            warnings.append(f"Ignored file with unsupported name: {f.name}")
            continue
        out[image_id] = f
    return out


def scan(settings: Settings | None = None) -> Registry:
    settings = settings or get_settings()
    data_dir = settings.data_dir
    warnings: list[str] = []

    if settings.outputs_dir:
        outputs_root, out_cands = (settings.outputs_dir if settings.outputs_dir.is_dir() else None), [settings.outputs_dir]
    else:
        outputs_root, out_cands = _discover_root(data_dir, "outputs", _looks_like_outputs)
    if settings.checkpoints_dir:
        ckpt_root, ck_cands = (settings.checkpoints_dir if settings.checkpoints_dir.is_dir() else None), [settings.checkpoints_dir]
    else:
        ckpt_root, ck_cands = _discover_root(data_dir, "checkpoints", _looks_like_checkpoints)

    if outputs_root is None:
        warnings.append(f"No outputs folder found under {data_dir} (looked for 'outputs' or 'outputs-<timestamp>').")
    if ckpt_root is None:
        warnings.append(f"No checkpoints folder found under {data_dir}.")
    if len(out_cands) > 1:
        warnings.append(f"Multiple outputs folders found; using newest: {outputs_root}")
    if len(ck_cands) > 1:
        warnings.append(f"Multiple checkpoints folders found; using newest: {ckpt_root}")

    reg = Registry(
        data_dir=data_dir,
        outputs_root=outputs_root,
        checkpoints_root=ckpt_root,
        outputs_candidates=out_cands,
        checkpoints_candidates=ck_cands,
        warnings=warnings,
    )

    # Notebooks: phase1*.ipynb etc. If several match, the most recently modified wins.
    nb_dir = settings.notebooks_dir or data_dir
    if nb_dir.is_dir():
        for phase in ("phase1", "phase2", "phase3"):
            matches = sorted(nb_dir.glob(f"{phase}*.ipynb"), key=lambda p: p.stat().st_mtime, reverse=True)
            if matches:
                reg.notebooks[phase] = matches[0]

    if outputs_root is not None:
        for d in sorted(p for p in outputs_root.iterdir() if p.is_dir()):
            name = d.name
            if name.startswith("graphs_"):
                reg.graph_sets[_set_id(name, "graphs_", warnings)] = _index_dir(d, "_graph.json", warnings)
            elif name.startswith("masks_"):
                set_id = _set_id(name, "masks_", warnings)
                reg.mask_sets[set_id] = _index_dir(d, "_pred.png", warnings)
                for f in d.glob("*.png"):
                    if f.name == "sam_repair_comparison.png":
                        reg.figures["sam_repair_comparison"] = FigureInfo(
                            "sam_repair_comparison", f, "sam_comparison", "SAM repair before/after (Phase I figure)", set_id
                        )
            elif name.startswith("analysis_viz_"):
                set_id = _set_id(name, "analysis_viz_", warnings)
                for f in d.glob("*.png"):
                    stem = f.stem
                    if stem.endswith("_criticality_metrics"):
                        iid, kind, title = stem[: -len("_criticality_metrics")], "criticality_metrics", "Criticality metrics figure"
                    elif stem.endswith("_criticality"):
                        iid, kind, title = stem[: -len("_criticality")], "criticality", "Criticality heatmap"
                    else:
                        continue
                    if SAFE_ID.match(iid):
                        fid = f"{kind}-{set_id}-{iid}"
                        reg.figures[fid] = FigureInfo(fid, f, kind, f"{title} — {iid}", set_id, iid)
            elif name.startswith("analysis_"):
                set_id = _set_id(name, "analysis_", warnings)
                reg.analysis_sets[set_id] = _index_dir(d, "_criticality.json", warnings)
                for csv in d.glob("*.csv"):
                    reg.analysis_csv[set_id] = csv
            elif name.startswith("visualizations_"):
                set_id = _set_id(name, "visualizations_", warnings)
                for iid, f in _index_dir(d, "_phase2.png", warnings).items():
                    fid = f"phase2-{set_id}-{iid}"
                    reg.figures[fid] = FigureInfo(fid, f, "phase2", f"Phase II graph figure — {iid}", set_id, iid)
            elif name.startswith("synthetic_tests_"):
                set_id = _set_id(name, "synthetic_tests_", warnings)
                for iid, f in _index_dir(d, "_synth.png", warnings).items():
                    fid = f"synthetic-{set_id}-{iid}"
                    reg.figures[fid] = FigureInfo(fid, f, "synthetic", f"Synthetic occlusion test — {iid}", set_id, iid)
                for f in d.glob("*_sweep_grid.png"):
                    iid = f.name[: -len("_sweep_grid.png")]
                    if SAFE_ID.match(iid):
                        fid = f"sweep_grid-{set_id}-{iid}"
                        reg.figures[fid] = FigureInfo(fid, f, "sweep_grid", f"Healing parameter sweep — {iid}", set_id, iid)

    if ckpt_root is not None:
        for f in sorted(ckpt_root.iterdir()):
            if f.suffix == ".pth" and f.name.startswith("best_road_model_"):
                key = f.stem[len("best_road_model_"):]
                if SAFE_ID.match(key):
                    reg.checkpoints[key] = f
            elif f.suffix == ".png":
                stem = f.stem
                for kind, prefix in (("predictions", "predictions_"), ("training_curves", "training_curves_")):
                    if stem.startswith(prefix) and SAFE_ID.match(stem):
                        tag = stem[len(prefix):]
                        title = ("Prediction samples" if kind == "predictions" else "Training curves") + f" — {tag}"
                        reg.figures[stem] = FigureInfo(stem, f, kind, title, tag)
    return reg


def _set_id(dirname: str, prefix: str, warnings: list[str]) -> str:
    set_id = dirname[len(prefix):].lower()
    if not re.match(r"^[a-z0-9_]+$", set_id):
        warnings.append(f"Folder {dirname} has an unsupported name; it is indexed as '{set_id}' but may be unreachable.")
    return set_id


_lock = threading.Lock()
_registry: Registry | None = None


def get_registry() -> Registry:
    global _registry
    with _lock:
        if _registry is None:
            _registry = scan()
        return _registry


def rescan() -> Registry:
    global _registry
    with _lock:
        _registry = scan()
        return _registry


def reset_for_tests(settings: Settings) -> Registry:
    global _registry
    with _lock:
        _registry = scan(settings)
        return _registry
