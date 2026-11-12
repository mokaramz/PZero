"""Events endpoints (review 015): read-only, each in ONE read-only transaction (``set transaction read only``: a read
that tried to write fails instead of changing data), computed with ONE Berlin ``today`` from the request instant.

* ``GET /api/events``          the old ``/api/events``: ``{events, leads (decision new), weekend_window, today, types,
                               dims, dim_order, manual_sources, pages, scout_reports, source_count}``
* ``GET /api/events/health``   the old ``/api/event_health`` (the last scan's Event Source Health)
* ``GET /api/events/suggest``  the old ``/api/event_suggest``: ``{parts}`` for a draft given as query params
* ``GET /api/events/wsig``     the old ``/api/wsig?days=`` (default 14): ``{ranked}`` · 400 when ``days`` is not a whole
                               number
* ``GET /api/events/weekend``  the old ``POST /api/weekend`` ``{start, end}`` (it never wrote): ``{missions}``

Writes (review 016; each ONE transaction under ``events.writes``' lock order; refused with 409 before the legacy
import; a body that is not a JSON object is a 400):

* ``POST /api/events/save``     the old ``event_save``: add ``{name, ...}`` / edit ``{id, ...}``; with ``convert_lead``
                               the lead's conversion in the same transaction -> 200 ``{ok, id}`` (``id|merged:<name>``
                               after a merge; ``replayed: true`` when a conversion is answered again) · 400 · 404
                               (unknown id / lead) · 409 ``{collision: true, id}`` (same name and date, conflicting
                               place)
* ``POST /api/events/verify``   the old ``event_verify`` ``{id, verified}`` -> ``{ok}`` (``ok: false``: unknown id)
* ``POST /api/events/lead``     the old ``event_lead`` ``{id, decision}`` -> ``{ok}`` · 400 · 404
* ``POST /api/events/debrief``  the old ``event_debrief`` ``{id, people_met: [{name, note, founder_potential}],
                               leads: [{name, desc, url}], notes}`` -> ``{ok, people, leads}`` · 400 (a lead without
                               public evidence: nothing written) · 404
* ``POST /api/events/scout``    the old ``scout_event`` ``{id, action: add | monitor | ignore}`` -> ``{ok, status,
                               event_id}`` (``ok: false`` + error for an unknown report or action)

* ``POST /api/events/find``     the old ``event_find`` (review 017), synchronous: scan every event source
                               (``events.scan``: read, fetch with no transaction open, write in one transaction) ->
                               ``{added, accepted,
                               dropped_past, dropped_dupe, health, report}`` · 409 when a scan is already running or
                               before the legacy import
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import psycopg
from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from projectzero.api.routers.conviction import Body
from projectzero.core.db import read_only_transaction, transaction
from projectzero.dealflow.intake.postgres import IntakeClosedError
from projectzero.events import edits, scan, store, view
from projectzero.events.edits import EventsError
from projectzero.events.when import BERLIN
from projectzero.events.writes import EventsWriter
from projectzero.network.edits import NetworkError

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


# ── writes (review 016) ─────────────────────────────────────────────────────────────────────────────────────────
_VALIDATE: dict[str, Callable[[dict[str, Any]], Any]] = {
    "save": edits.validate_save,
    "lead": edits.lead_decision,
    "debrief": edits.validate_debrief,
}
SAVE_RACE = "this event was just created by another save — open it and save again; nothing was saved"


def _write(request: Request, body: Body, action: str) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    try:
        if check := _VALIDATE.get(action):
            check(body)  # bad requests never open a connection
        with transaction(settings.db_url) as conn:
            out = getattr(EventsWriter(conn, settings.schema, _now(request)), action)(body)
    except (EventsError, NetworkError) as exc:  # raised inside the transaction: everything it wrote is rolled back
        return JSONResponse(jsonable_encoder({"ok": False, "error": str(exc), **exc.extra}), status_code=exc.status)
    except IntakeClosedError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    except psycopg.errors.UniqueViolation as exc:  # the last line of defence, after the rollback
        if exc.diag.constraint_name == "events_pkey":
            return JSONResponse({"ok": False, "error": SAVE_RACE}, status_code=409)
        raise
    return JSONResponse(jsonable_encoder(out))


@router.post("/save")
def event_save(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, "save")


@router.post("/verify")
def event_verify(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, "verify")


@router.post("/lead")
def event_lead(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, "lead")


@router.post("/debrief")
def event_debrief(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, "debrief")


@router.post("/scout")
def scout_event(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, "scout")


@router.post("/find")
def event_find(request: Request, body: Body) -> JSONResponse:
    """The old ``event_find`` (its body is ignored). ``app.state.events_fetcher`` replaces the network in tests."""
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    fetcher = getattr(request.app.state, "events_fetcher", None)
    try:
        state = request.app.state
        health = scan.scan(
            settings.db_url,
            settings.schema,
            _now(request),
            fetcher,
            deadline_s=getattr(state, "events_scan_deadline_s", scan.SCAN_DEADLINE_S),
            transport=getattr(state, "events_transport", None),
            resolver=getattr(state, "events_resolver", None),
        )
    except EventsError as exc:
        return JSONResponse(jsonable_encoder({"ok": False, "error": str(exc), **exc.extra}), status_code=exc.status)
    except IntakeClosedError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    return JSONResponse(jsonable_encoder(scan.find_answer(health)))
