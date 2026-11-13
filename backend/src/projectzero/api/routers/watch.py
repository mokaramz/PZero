"""WATCH (review 037a) — thin: parse, run the blocking work in the threadpool (sync ``def`` routes), shape.

The old paths, bodies, answers and error texts (``api/routers/watch.py``):

* ``GET  /api/watch``         the old ``watch.view()``: ``{companies, labels, note}`` (the payload itself, no ``ok``
                              envelope), built from ONE read-only snapshot by ``watch.view.watch_view``
* ``POST /api/watch_target``  ``{name, urls[], candidate_id?, active?}`` -> ``{ok, target}``
* ``POST /api/watch_ack``     ``{id, status: reviewed|dismissed, note?}`` -> ``{ok, kind: "status", trigger_id,
                              status, at, note}``

Errors use ``{ok: false, error}``: 400 with the old texts ("company name required", "not a public http(s) URL: ...",
"status must be reviewed or dismissed", "no such trigger"; new: "urls must be a list of strings", where the old code
crashed), 409 before the import. Each write is ONE transaction (``watch.writes``); the answer is sent after it commits.
``app.state.clock`` is the test seam for the written timestamps. "Check now" (``watch_check``) is the WATCH sensors'
(037b).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from projectzero.api.routers.conviction import Body
from projectzero.core.db import snapshot_transaction, transaction
from projectzero.dealflow.intake.postgres import IntakeClosedError
from projectzero.network.view import BERLIN
from projectzero.watch import writes
from projectzero.watch.view import watch_view

router = APIRouter(prefix="/api", tags=["watch"])


def _clock(request: Request) -> datetime:
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    return clock() if clock is not None else datetime.now(BERLIN)


@router.get("/watch")
def get_watch(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    with snapshot_transaction(settings.db_url) as conn:
        body = watch_view(conn, settings.schema)
    return JSONResponse(jsonable_encoder(body))


def _write(
    request: Request, body: Any, check: Callable[[Any], Any], work: Callable[..., dict[str, Any]]
) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    try:
        check(body)  # the pure checks first: a bad request never opens a connection
        with transaction(settings.db_url) as conn:
            out = work(conn, settings.schema, body, _clock(request))
    except writes.WatchError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=exc.status)
    except IntakeClosedError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    return JSONResponse(jsonable_encoder(out))


@router.post("/watch_target")
def watch_target(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, writes.parse_target, writes.set_target)


@router.post("/watch_ack")
def watch_ack(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, writes.parse_ack, writes.acknowledge)
