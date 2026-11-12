"""Sources endpoints (review 021) — the old ``GET /api/sources`` and ``POST /api/source_toggle``:

* ``GET  /api/sources``         the registry view, plus ``report`` / ``manual_sources`` / ``pages`` / ``feeds``
                                (the four fields the old page read from ``GET /api/inbox``); ``dealflow.sources.view``
* ``POST /api/sources/toggle``  ``{id, enabled}`` -> ``{ok: true}`` (an unknown id too, as before)

400 ``{ok: false, error}`` for a body that is not a JSON object; 409 before the legacy import (the write boundary).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from projectzero.api.routers.conviction import Body
from projectzero.core.db import read_only_transaction, transaction
from projectzero.dealflow.intake.postgres import IntakeClosedError
from projectzero.dealflow.sources.store import SourcesStore

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("")
def get_sources(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    with read_only_transaction(settings.db_url) as conn:
        return JSONResponse(jsonable_encoder(SourcesStore(conn, settings.schema).view()))


@router.post("/toggle")
def toggle(request: Request, body: Body) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    try:
        with transaction(settings.db_url) as conn:
            out = SourcesStore(conn, settings.schema).toggle(body)
    except IntakeClosedError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    return JSONResponse(jsonable_encoder(out))
