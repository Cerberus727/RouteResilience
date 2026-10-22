"""Extracts *historical* results printed in the executed notebooks.

Only values literally present in the saved cell outputs are returned; each
record carries its source (notebook file + cell index) so the UI can label it.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from ..registry import get_registry

_lock = threading.Lock()
_cache: dict[tuple, dict] = {}

EPOCH_RE = re.compile(
    r"Epoch (\d+) \| Train Loss: ([\d.]+) IoU: ([\d.]+) \| Val Loss: ([\d.]+) IoU: ([\d.]+)"
)
MODEL_RE = re.compile(r"MODEL_NAME=(\w+) \| family=(\w+) \| IMG_SIZE=(\d+)")
PARAMS_RE = re.compile(r"\| Params: ([\d,]+)")
BEST_RE = re.compile(r"finished\. best val iou ([\d.]+)")
SPLIT_RE = re.compile(r"Train: (\d+) \| Val: (\d+)")
SAM_RE = re.compile(
    r"(\w+) \| components (\d+)->(\d+) \| largest-frac ([\d.]+)->([\d.]+) \| \+pixels (-?\d+)"
)
SAM_INPUT_RE = re.compile(r"Input masks\s*:\s*(\S+)")
SYNTH_RE = re.compile(
    r"\[(\w+)\] Original conn=([\d.]+) \| Broken=([\d.]+) \| Healed=([\d.]+) \| Bridges=(\d+)"
)
SWEEP_RE = re.compile(r"(\d+)/(\d+) tiles \(([\d.]+)%\) needed at least one bridge")
AVG_CONN_RE = re.compile(r"Avg connectivity: ([\d.]+) -> ([\d.]+)")
P2_MODEL_RE = re.compile(r"Model\s*:\s*(\w+)")
P2_MASKDIR_RE = re.compile(r"Mask dir\s*:\s*(\S+)")
P2_RESULT_RE = re.compile(r"\[(\w+)\] nodes=(\d+) edges=(\d+) bridges=(\d+) connectivity: ([\d.]+) -> ([\d.]+)")


def _cell_texts(path: Path) -> list[tuple[int, str, str]]:
    """[(cell_index, source, stdout_text)] for code cells."""
    with open(path, "r", encoding="utf-8") as f:
        nb = json.load(f)
    out = []
    for idx, cell in enumerate(nb.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        texts = []
        for o in cell.get("outputs", []):
            if "text" in o:
                texts.append("".join(o["text"]) if isinstance(o["text"], list) else str(o["text"]))
            elif o.get("output_type") == "error":
                texts.append(f"ERROR {o.get('ename', '')}: {o.get('evalue', '')}")
        out.append((idx, src, "\n".join(texts)))
    return out


def _parse_phase1(path: Path) -> dict:
    cells = _cell_texts(path)
    res: dict = {"source": path.name, "model_name": None, "family": None, "img_size": None,
                 "params": None, "split": None, "training": None, "sam_repair": None, "errors": []}
    for idx, src, text in cells:
        if m := MODEL_RE.search(text):
            res["model_name"], res["family"], res["img_size"] = m.group(1), m.group(2), int(m.group(3))
        if m := SPLIT_RE.search(text):
            res["split"] = {"train": int(m.group(1)), "val": int(m.group(2)), "cell": idx}
        epochs = EPOCH_RE.findall(text)
        if epochs:
            pm = PARAMS_RE.search(text)
            if pm:
                res["params"] = int(pm.group(1).replace(",", ""))
            best = BEST_RE.search(text)
            res["training"] = {
                "cell": idx,
                "epochs": [
                    {"epoch": int(e), "train_loss": float(tl), "train_iou": float(ti), "val_loss": float(vl), "val_iou": float(vi)}
                    for e, tl, ti, vl, vi in epochs
                ],
                "best_val_iou_reported": float(best.group(1)) if best else None,
            }
        sams = SAM_RE.findall(text)
        if sams and "repair" in src.lower():
            inp = SAM_INPUT_RE.search(text)
            res["sam_repair"] = {
                "cell": idx,
                "input_mask_dir": inp.group(1).rstrip("/").split("/")[-1] if inp else None,
                "rows": [
                    {"image_id": i, "components_before": int(cb), "components_after": int(ca),
                     "largest_frac_before": float(lb), "largest_frac_after": float(la), "pixels_added": int(px)}
                    for i, cb, ca, lb, la, px in sams
                ],
            }
        if "ERROR " in text:
            for line in text.splitlines():
                if line.startswith("ERROR "):
                    res["errors"].append({"cell": idx, "message": line[6:]})
    return res


def _parse_phase2(path: Path) -> dict:
    cells = _cell_texts(path)
    res: dict = {"source": path.name, "model_tag": None, "mask_dir": None, "synthetic": None, "sweep": None, "export": None}
    for idx, src, text in cells:
        if (m := P2_MODEL_RE.search(text)) and "Mask dir" in text:
            res["model_tag"] = m.group(1)
            if md := P2_MASKDIR_RE.search(text):
                res["mask_dir"] = md.group(1).rstrip("/").split("/")[-1]
        synth = SYNTH_RE.findall(text)
        if synth:
            res["synthetic"] = {
                "cell": idx,
                "rows": [
                    {"image_id": i, "conn_original": float(o), "conn_broken": float(b), "conn_healed": float(h), "bridges": int(n)}
                    for i, o, b, h, n in synth
                ],
            }
        if m := SWEEP_RE.search(text):
            avg = AVG_CONN_RE.search(text)
            res["sweep"] = {
                "cell": idx, "tiles_needing_bridge": int(m.group(1)), "tiles_total": int(m.group(2)),
                "percent": float(m.group(3)),
                "avg_conn_before": float(avg.group(1)) if avg else None,
                "avg_conn_after": float(avg.group(2)) if avg else None,
            }
        rows = P2_RESULT_RE.findall(text)
        if rows:
            res["export"] = {
                "cell": idx,
                "rows": [
                    {"image_id": i, "nodes": int(n), "edges": int(e), "bridges": int(b), "conn_before": float(cb), "conn_after": float(ca)}
                    for i, n, e, b, cb, ca in rows
                ],
            }
    return res


_PARSERS = {"phase1": _parse_phase1, "phase2": _parse_phase2}


def parsed(phase: str) -> dict | None:
    """Parsed historical outputs for 'phase1' / 'phase2', or None if the notebook is missing/unreadable."""
    path = get_registry().notebooks.get(phase)
    if path is None or phase not in _PARSERS:
        return None
    try:
        key = (phase, str(path), path.stat().st_mtime_ns)
    except OSError:
        return None
    with _lock:
        if key in _cache:
            return _cache[key]
        try:
            value = _PARSERS[phase](path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            value = {"source": path.name, "error": f"Could not parse notebook: {exc}"}
        _cache[key] = value
        return value


def graph_set_provenance(set_id: str) -> dict:
    """What the Phase II notebook says about how a graph set was produced."""
    p2 = parsed("phase2")
    info: dict = {"set_id": set_id, "source_mask_set": None, "verified": False, "note": None}
    if p2 and p2.get("model_tag") == set_id and p2.get("mask_dir"):
        mask_dir = p2["mask_dir"]
        info.update(source_mask_set=mask_dir.removeprefix("masks_"), verified=True)
        if mask_dir != f"masks_{set_id}":
            info["note"] = (
                f"The Phase II notebook run tagged '{set_id}' read masks from '{mask_dir}' "
                f"(hard-coded MASK_DIR). These graphs were NOT built from masks_{set_id}."
            )
    return info
