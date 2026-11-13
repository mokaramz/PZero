"""FastAPI app factory. Routers are thin: parse -> service -> shape the response. Errors use ``{ok: false, error}``."""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from projectzero.api.routers import (
    associate,
    content,
    conviction,
    dealflow,
    dealflow_triage,
    ecosystems,
    evaluator,
    events,
    founder_calls,
    founder_radar,
    home,
    intake,
    jobs,
    map,
    network,
    news,
    sources,
    system_health,
    today,
    validation,
)
from projectzero.api.security import security_middleware
from projectzero.core.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # review 032c: the in-app catch-up at start (the old recovery + ``start_catch_up``, its 4-second delay), in a
        # thread so startup never waits on the database; off under tests (``PZ_CATCHUP=0``, tests/conftest.py)
        from projectzero.jobs import runner

        if runner.env_enabled():
            s = app.state.settings
            threading.Thread(target=runner.app_start, args=(s.db_url, s.schema), daemon=True, name="pz-start").start()
        yield

    app = FastAPI(title="Project Zero", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings or Settings.from_env()
    app.middleware("http")(security_middleware)
    app.include_router(intake.router)
    app.include_router(dealflow.router)
    app.include_router(dealflow_triage.router)
    app.include_router(conviction.router)
    app.include_router(network.router)
    app.include_router(events.router)
    app.include_router(content.router)
    app.include_router(sources.router)
    app.include_router(ecosystems.router)
    app.include_router(founder_calls.router)
    app.include_router(evaluator.router)
    app.include_router(map.router)
    app.include_router(founder_radar.router)
    app.include_router(validation.router)
    app.include_router(news.router)
    app.include_router(today.router)
    app.include_router(home.router)
    app.include_router(system_health.router)
    app.include_router(associate.router)
    app.include_router(jobs.router)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        issues = [f"{'/'.join(str(p) for p in e.get('loc', ()))}: {e.get('msg')}" for e in exc.errors()]
        return JSONResponse({"ok": False, "error": "invalid request", "issues": issues}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception) -> JSONResponse:  # never leak internals or secrets
        return JSONResponse({"ok": False, "error": f"internal error ({type(exc).__name__})"}, status_code=500)

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        return {"ok": True}

    return app
