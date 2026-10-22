"""Serves registered image artifacts. Paths come only from the registry."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ..registry import SAFE_ID, get_registry

router = APIRouter(tags=["files"])
CACHE = {"Cache-Control": "public, max-age=3600"}


def figure_url(figure_id: str | None) -> str | None:
    return f"/api/figures/{figure_id}" if figure_id else None


@router.get("/masks/{mask_set}/{image_id}.png", summary="Predicted road mask PNG", response_class=FileResponse)
def get_mask(mask_set: str, image_id: str):
    if not (SAFE_ID.match(mask_set) and SAFE_ID.match(image_id)):
        raise HTTPException(400, "Invalid mask id.")
    path = get_registry().mask_sets.get(mask_set, {}).get(image_id)
    if path is None or not path.is_file():
        raise HTTPException(404, f"No mask {mask_set}/{image_id}.")
    return FileResponse(path, media_type="image/png", headers=CACHE)


@router.get("/figures", summary="List notebook figures")
def list_figures(kind: str | None = Query(None, pattern=r"^[a-z_]+$"), set_id: str | None = Query(None, pattern=r"^[a-z0-9_]+$"),
                 image_id: str | None = Query(None, pattern=r"^[A-Za-z0-9_]+$")) -> list[dict]:
    out = []
    for f in get_registry().figures.values():
        if (kind and f.kind != kind) or (set_id and f.set_id != set_id) or (image_id and f.image_id != image_id):
            continue
        out.append({"figure_id": f.figure_id, "kind": f.kind, "title": f.title, "set_id": f.set_id,
                    "image_id": f.image_id, "url": figure_url(f.figure_id)})
    return sorted(out, key=lambda f: f["figure_id"])


@router.get("/figures/{figure_id}", summary="Notebook figure PNG (historical)", response_class=FileResponse)
def get_figure(figure_id: str):
    if not re.match(r"^[A-Za-z0-9_\-]+$", figure_id):
        raise HTTPException(400, "Invalid figure id.")
    info = get_registry().figures.get(figure_id)
    if info is None or not info.path.is_file():
        raise HTTPException(404, f"No figure '{figure_id}'.")
    return FileResponse(info.path, media_type="image/png", headers=CACHE)
