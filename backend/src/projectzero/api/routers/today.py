"""Today endpoint (review 030a): the old ``GET /api/today`` (``services/today.view``), key for key.

* ``GET /api/today`` -> ``{date, actions, more, considered, exceptions, machine_working, triage, rules, snapshot}``

A read model with no writes and no store of its own. Every reader runs on ONE connection whose transaction is
REPEATABLE READ, READ ONLY from before its first query (revision 2), so the ranked list comes from one committed
state. One clock (decision b): the request instant as Berlin wall time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from projectzero.api.clock import berlin_request_now
from projectzero.core.db import snapshot_transaction
from projectzero.today import core
from projectzero.today import inputs as today_inputs

router = APIRouter(prefix="/api", tags=["today"])


def today_view(db_url: str, schema: str, now: datetime, *, after_first_read: Any = None) -> dict[str, Any]:
    with snapshot_transaction(db_url) as conn:
        inputs = today_inputs.load(conn, schema, now, after_first_read=after_first_read)
    return core.view(inputs, now.date(), now)


@router.get("/today")
def get_today(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    hook = getattr(request.app.state, "today_after_first_read", None)  # tests only: the concurrent-edit regression
    view = today_view(settings.db_url, settings.schema, berlin_request_now(request), after_first_read=hook)
    return JSONResponse(jsonable_encoder(view))
