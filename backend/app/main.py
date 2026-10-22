"""FastAPI application entry point.

Run (from the `backend/` folder):  uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, analysis
from .config import get_settings
from .graph_io import GraphLoadError
from .registry import get_registry
from .geo.service import RegionError
from .routes import experiments, files, geo, graphs, models, system, workspace
from .services.lab import LabError
from .services.runs import RunError
from .services.graphs import GraphNotFoundError
from .services.reviews import ReviewStoreError

log = logging.getLogger("routeresilience")


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        reg = get_registry()
        log.info("RouteResilience data dir: %s | outputs: %s | %s", reg.data_dir, reg.outputs_root, reg.counts())
        for w in reg.warnings:
            log.warning(w)
        yield

    app = FastAPI(
        lifespan=lifespan,
        title="RouteResilience API",
        version=__version__,
        description="Road-network resilience analysis over existing RouteResilience pipeline artifacts. "
                    "Every value is either read from an artifact (historical) or recomputed here; nothing is synthesized.",
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["*"],
    )

    def error(status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": message, "code": code})

    @app.exception_handler(GraphNotFoundError)
    async def _nf(_: Request, exc: GraphNotFoundError):
        return error(404, "graph_not_found", str(exc))

    @app.exception_handler(GraphLoadError)
    async def _gl(_: Request, exc: GraphLoadError):
        return error(422, f"artifact_{exc.code}", f"The graph artifact could not be used: {exc.message}")

    @app.exception_handler(analysis.GraphTooLargeError)
    async def _tl(_: Request, exc: analysis.GraphTooLargeError):
        return error(413, "graph_too_large", str(exc))

    @app.exception_handler(analysis.InvalidTargetError)
    async def _it(_: Request, exc: analysis.InvalidTargetError):
        return error(400, "invalid_target", str(exc))

    @app.exception_handler(ReviewStoreError)
    async def _rs(_: Request, exc: ReviewStoreError):
        return error(500, "review_store_error", str(exc))

    @app.exception_handler(RegionError)
    async def _re(_: Request, exc: RegionError):
        return error(exc.status, exc.code, exc.message)

    @app.exception_handler(LabError)
    async def _le(_: Request, exc: LabError):
        return error(exc.status, exc.code, exc.message)

    @app.exception_handler(RunError)
    async def _ru(_: Request, exc: RunError):
        return error(exc.status, "run_error", exc.message)

    for r in (system.router, models.router, graphs.router, experiments.router, files.router, geo.router, workspace.router):
        app.include_router(r, prefix="/api")

    # Serve the built frontend (frontend/dist) when present: single-process deployment.
    dist = settings.frontend_dist
    if (dist / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            if full_path.startswith("api/"):
                return error(404, "not_found", "Unknown API route.")
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
