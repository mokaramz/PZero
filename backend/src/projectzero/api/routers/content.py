"""Public work endpoints (review 020) — the old ``/api/content``, ``/content_save`` and ``/content_delete``:

* ``GET  /api/content``         ``{items: [...], ...the archived document's other keys}``
* ``POST /api/content/save``    ``{id?, platform, kind, title, url, notes, inbound, status}`` -> ``{ok: true, id}``
* ``POST /api/content/delete``  ``{id}`` -> ``{ok: true}``

400 ``{ok: false, error}`` for a body that is not a JSON object or an id that is not a string (before any connection);
409 before the legacy import (the production write boundary). See ``content.store`` for the rules.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from projectzero.api.routers.conviction import Body
from projectzero.content.store import ContentError, ContentStore, delete_id, request_id
from projectzero.core.db import read_only_transaction, transaction
from projectzero.dealflow.intake.postgres import IntakeClosedError
from projectzero.network.view import BERLIN

router = APIRouter(prefix="/api/content", tags=["content"])


def _clock(request: Request) -> datetime:
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    return clock() if clock is not None else datetime.now(BERLIN)


@router.get("")
def get_content(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    with read_only_transaction(settings.db_url) as conn:
        return JSONResponse(jsonable_encoder(ContentStore(conn, settings.schema).view()))


def _write(request: Request, body: Body, action: str) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    now = _clock(request)
    try:
        (request_id if action == "save" else delete_id)(body)  # a bad id never opens a connection
        with transaction(settings.db_url) as conn:
            store = ContentStore(conn, settings.schema)
            out = store.save(body, now) if action == "save" else store.delete(body)
    except ContentError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=exc.status)
    except IntakeClosedError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    return JSONResponse(jsonable_encoder(out))


@router.post("/save")
def save(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, "save")


@router.post("/delete")
def delete(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, "delete")
