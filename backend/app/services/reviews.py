"""Persistent reviewer decisions on healed (bridge) edges.

Decisions are stored separately from the pipeline artifacts in
`<state_dir>/healing_reviews.json` and never modify any graph file. Writes are
atomic (temp file + os.replace) and serialized with a process-wide lock.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..config import get_settings

_lock = threading.Lock()
FILENAME = "healing_reviews.json"
DECISIONS = ("approved", "rejected")


class ReviewStoreError(Exception):
    pass


def _path() -> Path:
    return get_settings().state_dir / FILENAME


def _read() -> dict:
    p = _path()
    if not p.exists():
        return {"version": 1, "reviews": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewStoreError(f"Review store {p.name} is unreadable: {exc}. It was not overwritten.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("reviews"), dict):
        raise ReviewStoreError(f"Review store {p.name} has an unexpected structure. It was not overwritten.")
    return data


def get_reviews(graph_id: str) -> dict[str, dict]:
    with _lock:
        return dict(_read()["reviews"].get(graph_id, {}))


def set_review(graph_id: str, edge_id: str, decision: str | None, note: str | None, artifact_version: str) -> dict | None:
    """decision=None clears the review."""
    with _lock:
        data = _read()
        graph_reviews = data["reviews"].setdefault(graph_id, {})
        if decision is None:
            graph_reviews.pop(edge_id, None)
            record = None
        else:
            record = {
                "decision": decision,
                "note": (note or "")[:2000],
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "artifact_version": artifact_version,
            }
            graph_reviews[edge_id] = record
        if not graph_reviews:
            data["reviews"].pop(graph_id, None)
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".reviews-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            os.replace(tmp, p)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return record
