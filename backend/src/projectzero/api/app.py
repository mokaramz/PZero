"""FastAPI app factory. Routers are thin: parse -> service -> shape the response. Errors use ``{ok: false, error}``."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from projectzero.api.routers import (
    content,
    conviction,
    dealflow,
    dealflow_triage,
    ecosystems,
    events,
    intake,
    network,
    sources,
)
from projectzero.api.security import security_middleware
from projectzero.core.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Project Zero", docs_url=None, redoc_url=None, openapi_url=None)
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
