"""Saved simulation runs and the segmentation lab."""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..services import lab, runs

router = APIRouter(tags=["workspace"])
SEG = re.compile(r"^\d{1,15}:\d{1,5}$")


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["fail", "restore", "reset"]
    segment_id: str | None = None

    @field_validator("segment_id")
    @classmethod
    def _sid(cls, v):
        if v is not None and not SEG.match(v):
            raise ValueError("invalid segment id")
        return v


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="", max_length=120)
    bbox: list[float] = Field(min_length=4, max_length=4)
    origin: list[float] | None = Field(default=None, min_length=2, max_length=2)
    destination: list[float] | None = Field(default=None, min_length=2, max_length=2)
    actions: list[Action] = Field(max_length=200)


@router.post("/runs", summary="Save a simulation run (metrics are recomputed server-side for every step)")
async def save_run(body: RunBody) -> dict:
    if (body.origin is None) != (body.destination is None):
        raise HTTPException(422, "Provide both origin and destination, or neither.")
    for i, a in enumerate(body.actions, 1):
        if a.action in ("fail", "restore") and not a.segment_id:
            raise HTTPException(422, f"Step {i}: '{a.action}' needs a segment_id.")
    return await run_in_threadpool(runs.save_run, body.name, body.bbox, body.origin, body.destination,
                                   [a.model_dump() for a in body.actions])


@router.get("/runs", summary="Saved runs, newest first")
def list_runs() -> list[dict]:
    return runs.list_runs()


@router.get("/runs/{run_id}", summary="Saved run detail")
def get_run(run_id: str) -> dict:
    return runs.get_run(run_id)


@router.delete("/runs/{run_id}", summary="Delete a saved run")
def delete_run(run_id: str) -> dict:
    runs.delete_run(run_id)
    return {"deleted": run_id}


@router.get("/runs/{run_id}/export", summary="Export a run as JSON, CSV or Markdown report")
def export_run(run_id: str, format: Literal["json", "csv", "md"] = "json") -> Response:
    run = runs.get_run(run_id)
    disp = {"Content-Disposition": f'attachment; filename="{run_id}.{format}"'}
    if format == "json":
        return JSONResponse(run, headers=disp)
    if format == "csv":
        return PlainTextResponse(runs.run_csv(run), media_type="text/csv", headers=disp)
    return PlainTextResponse(runs.run_markdown(run), media_type="text/markdown", headers=disp)


# ------------------------------------------------------------------ lab
class InferBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = Field(pattern=r"^[A-Za-z0-9_]{1,64}$")
    image_id: str = Field(pattern=r"^[A-Za-z0-9_]{1,64}$")


@router.get("/lab/samples", summary="DeepGlobe samples with Phase I split membership")
def lab_samples(subset: Literal["all", "phase1_val", "phase1_train", "phase1_saved", "valid", "test"] = "phase1_saved",
                offset: int = Query(0, ge=0), limit: int = Query(60, ge=1, le=200),
                q: str | None = Query(None, max_length=32, pattern=r"^[A-Za-z0-9_]*$")) -> dict:
    return lab.list_samples(subset, offset, limit, q or None)


@router.get("/lab/models", summary="Checkpoints and whether each can run inference here")
async def lab_models() -> list[dict]:
    return await run_in_threadpool(lab.models)


@router.get("/lab/images/{image_id}/{kind}", summary="Satellite image (sat) or ground-truth mask (gt)")
def lab_image(image_id: str, kind: Literal["sat", "gt"]):
    s = lab.get_sample(image_id)
    if kind == "gt":
        if s.mask is None:
            raise HTTPException(404, "No ground-truth mask exists for this image (only the train/ folder has masks).")
        return FileResponse(s.mask, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
    return FileResponse(s.sat, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@router.post("/lab/infer", summary="Run road segmentation on one DeepGlobe image")
async def lab_infer(body: InferBody) -> dict:
    return await run_in_threadpool(lab.infer, body.model_id, body.image_id)


@router.get("/lab/results/{rid}/{kind}.png", summary="Inference output image")
def lab_result(rid: str, kind: Literal["mask", "overlay", "errors", "ground_truth"]):
    if not re.match(r"^[0-9a-f]{12}$", rid):
        raise HTTPException(400, "Invalid result id.")
    return Response(lab.result_image(rid, kind), media_type="image/png")
