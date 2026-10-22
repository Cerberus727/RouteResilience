from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from ..services import experiments

router = APIRouter(tags=["experiments"])


@router.get("/experiments", summary="Experiment history assembled from artifacts and notebook logs")
async def list_experiments() -> list[dict]:
    return await run_in_threadpool(experiments.list_experiments)


@router.get("/experiments/{experiment_id}", summary="Experiment detail with result rows")
async def get_experiment(experiment_id: str) -> dict:
    if len(experiment_id) > 80:
        raise HTTPException(400, "Invalid experiment id.")
    try:
        return await run_in_threadpool(experiments.get_experiment, experiment_id)
    except experiments.ExperimentNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
