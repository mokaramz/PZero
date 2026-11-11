"""Events endpoints (review 015): read-only, each in ONE read-only transaction (``set transaction read only``: a read
that tried to write fails instead of changing data), computed with ONE Berlin ``today`` from the request instant.

* ``GET /api/events``          the old ``/api/events``: ``{events, leads (decision new), weekend_window, today, types,
                               dims, dim_order, manual_sources, pages, scout_reports, source_count}``
* ``GET /api/events/health``   the old ``/api/event_health`` (the last scan's Event Source Health)
* ``GET /api/events/suggest``  the old ``/api/event_suggest``: ``{parts}`` for a draft given as query params
* ``GET /api/events/wsig``     the old ``/api/wsig?days=`` (default 14): ``{ranked}`` · 400 when ``days`` is not a whole
                               number
* ``GET /api/events/weekend``  the old ``POST /api/weekend`` ``{start, end}`` (it never wrote): ``{missions}``

The writes (``event_save``, ``event_verify``, ``event_lead``, ``event_debrief``, ``scout_event``) are review 016; the
source scan (``event_find``) is review 017.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from projectzero.core.db import read_only_transaction
from projectzero.events import store, view
from projectzero.events.when import BERLIN

router = APIRouter(prefix="/api/events", tags=["events"])


def _now(request: Request) -> datetime:
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    return clock() if clock is not None else datetime.now(BERLIN)


def _read(
    request: Request,
    build: Callable[[store.EventsData, Any], dict[str, Any]],
    *,
    people: bool,
    records: bool = True,
) -> JSONResponse:
    settings = request.app.state.settings
    today = view.berlin_today(_now(request))  # one instant, one Berlin date, for everything this request computes
    with read_only_transaction(settings.db_url) as conn:
        data = store.load(conn, settings.schema, today, people=people, records=records)
    return JSONResponse(jsonable_encoder(build(data, today)))


@router.get("")
def get_events(request: Request) -> JSONResponse:
    return _read(request, view.events_payload, people=False)


@router.get("/health")
def get_health(request: Request) -> JSONResponse:
    return _read(request, lambda data, _today: data.health(), people=False, records=False)


@router.get("/suggest")
def get_suggest(request: Request) -> JSONResponse:
    return JSONResponse(jsonable_encoder(view.suggest_payload(request.query_params.multi_items())))


@router.get("/wsig")
def get_wsig(request: Request) -> JSONResponse:
    raw = request.query_params.get("days", "").strip() or "14"  # the old ``query()``: Starlette's get
    try:
        days = int(raw)
    except ValueError:
        message = f"days must be a whole number (got {raw[:20]!r})"
        return JSONResponse({"ok": False, "error": message}, status_code=400)
    return _read(request, lambda data, today: view.wsig_payload(data, today, days), people=True)


@router.get("/weekend")
def get_weekend(request: Request) -> JSONResponse:
    start, end = request.query_params.get("start", ""), request.query_params.get("end", "")
    return _read(request, lambda data, today: view.weekend_payload(data, today, start, end), people=True)
