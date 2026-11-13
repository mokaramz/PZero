"""Investment Desk endpoint (review 031a): the old ``GET /api/home`` (``domain/ecosys.home``), key for key.

* ``GET /api/home`` -> ``{priority, best_event, due, new_signals, latest_signals, omar, progress, watch, weekday,
  date}``

A read model with no writes (decision a). Every reader runs on ONE connection whose transaction is REPEATABLE READ,
READ ONLY from before its first query (decision c, as Today), at one clock: the request instant as Berlin wall time
(decision b).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from projectzero.api.clock import berlin_request_now
from projectzero.core.db import snapshot_transaction
from projectzero.home import core
from projectzero.home import inputs as home_inputs

router = APIRouter(prefix="/api", tags=["home"])


def home_view(db_url: str, schema: str, now: datetime) -> dict[str, Any]:
    with snapshot_transaction(db_url) as conn:
        inputs = home_inputs.load(conn, schema, now)
    return core.view(inputs, now.date(), now)


@router.get("/home")
def get_home(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    return JSONResponse(jsonable_encoder(home_view(settings.db_url, settings.schema, berlin_request_now(request))))
