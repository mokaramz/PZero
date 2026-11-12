"""Founder Calls endpoints (review 023) — the old ``/api/calls``, ``/call``, ``/call_memo``, ``/call_briefing``,
``/call_save``, ``/call_followup`` and ``/call_link``, with the old bodies and ``{error}`` answers:

* ``GET  /api/founder-calls/calls``      the workspace, plus the people and Conviction pickers
* ``GET  /api/founder-calls/call?id=``   one call · 404 ``{error}``
* ``GET  /api/founder-calls/memo?id=``   ``{markdown, label}`` · 404 ``{error}`` (nothing stored)
* ``POST /api/founder-calls/briefing``   ``{founder_id, confirm}`` · 400 / 404 ``{error}`` (nothing stored)
* ``POST /api/founder-calls/save``       the old call body · 400 ``{error}``; case preparation is a no-op (decision a)
* ``POST /api/founder-calls/followup``   ``{id, done}`` · 404 ``{error}``
* ``POST /api/founder-calls/link``       ``{founder_id, person_id}`` | ``{company_id, pipeline_slug}`` · 400 / 404

A write loads the document, applies the pure function and stores only the changed records plus one event, all under
the one write lock; 409 before the legacy import. A body that is not a JSON object is a 400.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from projectzero.api.routers.conviction import Body
from projectzero.conviction.inputs import UNREADABLE, load_documents
from projectzero.conviction.store import ConvictionStore, record_of
from projectzero.core.db import read_only_transaction, transaction
from projectzero.dealflow.intake.postgres import IntakeClosedError
from projectzero.founder_calls import routes
from projectzero.founder_calls.store import FounderCallsStore
from projectzero.network.store import load_people
from projectzero.network.view import BERLIN, berlin_today

router = APIRouter(prefix="/api/founder-calls", tags=["founder-calls"])


def _clock(request: Request) -> datetime:
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    return clock() if clock is not None else datetime.now(BERLIN)


def _pipeline(conn: Any, schema: str) -> list[dict[str, Any]]:
    return [record_of(r) for r in ConvictionStore(conn, schema).entry_rows()]


def _evaluations(conn: Any, schema: str) -> Any:
    doc = load_documents(conn, schema).get("evaluations.json")
    return {} if doc is None or doc is UNREADABLE else doc


@router.get("/calls")
def get_calls(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    today = berlin_today(_clock(request))
    with read_only_transaction(settings.db_url) as conn:
        doc = FounderCallsStore(conn, settings.schema).load()
        people, pipeline = load_people(conn, settings.schema), _pipeline(conn, settings.schema)
        out = routes.workspace(doc, people=people, pipeline=pipeline, evaluations=_evaluations(conn, settings.schema),
                               today=today)  # fmt: skip
    return JSONResponse(jsonable_encoder(out))


def _one(request: Request, call_id: str, fn: Callable[..., dict[str, Any] | None]) -> JSONResponse:
    settings = request.app.state.settings
    with read_only_transaction(settings.db_url) as conn:
        out = fn(FounderCallsStore(conn, settings.schema).load(), call_id, today=berlin_today(_clock(request)))
    if out is None:
        return JSONResponse({"error": routes.UNKNOWN_CALL}, status_code=404)
    return JSONResponse(jsonable_encoder(out))


@router.get("/call")
def get_call(request: Request, id: str = "") -> JSONResponse:
    return _one(request, id, routes.call_view)


@router.get("/memo")
def get_memo(request: Request, id: str = "") -> JSONResponse:
    return _one(request, id, routes.memo)


@router.post("/briefing")
def post_briefing(request: Request, body: Body) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    with read_only_transaction(settings.db_url) as conn:
        status, out = routes.briefing(FounderCallsStore(conn, settings.schema).load(), body,
                                      today=berlin_today(_clock(request)))  # fmt: skip
    return JSONResponse(jsonable_encoder(out), status_code=status)


def _write(request: Request, body: Body, action: str) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    now = _clock(request)
    today = berlin_today(now)
    try:
        with transaction(settings.db_url) as conn:
            store = FounderCallsStore(conn, settings.schema)
            store.lock()
            doc = store.load()
            if action == "save":
                outcome = routes.save(doc, body, today=today, now=now)
            elif action == "followup":
                outcome = routes.followup(doc, body, today=today, now=now)
            else:
                outcome = routes.link(doc, body, people=load_people(conn, settings.schema),
                                      pipeline=_pipeline(conn, settings.schema), today=today, now=now)  # fmt: skip
            if outcome.status == 200:
                ids = {k: body.get(k) for k in ("id", "founder_id", "company_id", "person_id", "pipeline_slug")
                       if body.get(k) is not None}  # fmt: skip
                store.apply(doc, outcome, action, {"request": ids})
    except IntakeClosedError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    return JSONResponse(jsonable_encoder(outcome.body), status_code=outcome.status)


@router.post("/save")
def post_save(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, "save")


@router.post("/followup")
def post_followup(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, "followup")


@router.post("/link")
def post_link(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, "link")
