"""System health endpoints (review 032a): the old reads, key for key.

* ``GET /api/system_health``           the old ``services/health.system()``: the verdict, status, issues, sources,
                                       coverage, jobs, spend, providers and diagnostics
* ``GET /api/system_health_overview``  the old ``services/health_overview.overview()``: the job history, the models
                                       and spend by day, the pipeline counts, backups / integrity / releases

Read models with no writes (decision a). Each runs on ONE connection whose transaction is REPEATABLE READ, READ ONLY
from before its first query, at one clock: the request instant as Berlin wall time (decision b,
``api.clock.berlin_request_now``). The background-job runner is not ported (decision e / k: ``RUNNER`` is ``None``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from projectzero.api.clock import berlin_request_now
from projectzero.core.db import snapshot_transaction
from projectzero.health import core
from projectzero.health import inputs as health_inputs

router = APIRouter(prefix="/api", tags=["system health"])


def system_view(db_url: str, schema: str, now: datetime) -> dict[str, Any]:
    with snapshot_transaction(db_url) as conn:
        inputs = health_inputs.load(conn, schema, now)
    return core.system_view(inputs, now, core.RUNNER)


def overview_view(db_url: str, schema: str, now: datetime) -> dict[str, Any]:
    with snapshot_transaction(db_url) as conn:
        inputs = health_inputs.load(conn, schema, now)
    return core.overview_view(inputs, now)


@router.get("/system_health")
def get_system_health(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    return JSONResponse(jsonable_encoder(system_view(settings.db_url, settings.schema, berlin_request_now(request))))


@router.get("/system_health_overview")
def get_system_health_overview(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    return JSONResponse(jsonable_encoder(overview_view(settings.db_url, settings.schema, berlin_request_now(request))))
