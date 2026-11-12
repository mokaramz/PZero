"""Active Evaluator endpoints (review 024) — the old ``/api/evaluations``, ``/api/evaluation`` and ``/api/eval_*``,
with the old bodies and answers:

* ``GET  /api/evaluator/sessions``        the workspace (the sessions strip, the states, the families, the labels)
* ``GET  /api/evaluator/session?id=``     ``{session, panel, next}`` · 404 ``{error: "unknown session"}``
* ``POST /api/evaluator/start``           ``{subject: {kind, name, founder, slug, person_id}}``
* ``POST /api/evaluator/deck|next|skip|answer|evidence|resolve|end``   ``{id, ...}``; refusals are the old 200
  ``{ok: false, error}``, and every answer carries ``panel`` and ``row``

A write takes the one write lock, loads the sessions through the shared reader, applies the pure function and stores
only what changed (decision c): the changed session plus one ``eval_events`` row. Ending a session is ONE transaction:
the session, the founder call (through the Founder Calls store) and the linked Conviction records with an
``evaluator_end`` event each; a failure leaves none of them written. 409 before the legacy import.
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
from projectzero.evaluator import routes
from projectzero.evaluator.store import EvaluationsStore
from projectzero.founder_calls.store import FounderCallsStore
from projectzero.network.store import load_people
from projectzero.network.view import BERLIN, berlin_today

router = APIRouter(prefix="/api/evaluator", tags=["evaluator"])

ACTIONS = ("start", "deck", "next", "skip", "answer", "evidence", "resolve", "end")
REQUEST_KEYS = ("id", "qid", "claim_id", "kind", "call_type", "channel")


def _clock(request: Request) -> datetime:
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    return clock() if clock is not None else datetime.now(BERLIN)


def _radar_companies(conn: Any, schema: str) -> Any:
    doc = load_documents(conn, schema).get("radar_companies.json")
    return None if doc is UNREADABLE else doc


@router.get("/sessions")
def get_sessions(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    with read_only_transaction(settings.db_url) as conn:
        out = routes.workspace(EvaluationsStore(conn, settings.schema).load())
    return JSONResponse(jsonable_encoder(out))


@router.get("/session")
def get_session(request: Request, id: str = "") -> JSONResponse:
    settings = request.app.state.settings
    with read_only_transaction(settings.db_url) as conn:
        conviction = [record_of(r) for r in ConvictionStore(conn, settings.schema).entry_rows()]
        people = load_people(conn, settings.schema)
        doc = EvaluationsStore(conn, settings.schema).load()
        out = routes.session_view(doc, id, conviction=conviction, people=people, today=berlin_today(_clock(request)))
    if out is None:
        return JSONResponse({"error": routes.UNKNOWN_SESSION}, status_code=404)
    return JSONResponse(jsonable_encoder(out))


def _request_detail(act: str, body: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    ids = {k: body[k] for k in REQUEST_KEYS if isinstance(body.get(k), str | int | float | bool)}
    if act == "start" and isinstance(body.get("subject"), dict):
        subject = body["subject"]
        ids["subject"] = {k: subject[k] for k in ("kind", "slug", "person_id") if isinstance(subject.get(k), str)}
    detail: dict[str, Any] = {"request": ids}
    if answer.get("ok") is False:
        detail["refused"] = answer.get("error")
    return detail


def _write(request: Request, body: Body, act: str) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    now = _clock(request)
    today = berlin_today(now)
    try:
        with transaction(settings.db_url) as conn:
            sessions = EvaluationsStore(conn, settings.schema)
            sessions.lock()
            doc = sessions.load()
            conviction_store = ConvictionStore(conn, settings.schema)
            rows = conviction_store.entry_rows()
            conviction = [record_of(r) for r in rows]
            people = load_people(conn, settings.schema)
            calls = FounderCallsStore(conn, settings.schema)
            calls_doc = calls.load() if act == "end" else None
            outcome = routes.action(
                act, doc, body, conviction=conviction, people=people,
                radar_companies=_radar_companies(conn, settings.schema) if act == "start" else None,
                founder_calls=calls_doc, today=today, now=now, new_hex=getattr(request.app.state, "new_hex", None),
            )  # fmt: skip
            detail = _request_detail(act, body, outcome.body)
            if outcome.changed:
                sessions.write_sessions(doc, outcome.doc, act, detail)
            sid = outcome.changed[0] if outcome.changed else body.get("id")
            if outcome.founder_calls is not None and outcome.founder_calls.changed:
                calls.apply(calls_doc, outcome.founder_calls, "save", {"request": {"evaluation": sid}})
            if outcome.conviction:
                conviction_store.write_records(rows, outcome.conviction, "evaluator_end", {"evaluation": sid}, now)
    except IntakeClosedError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    return JSONResponse(jsonable_encoder(outcome.body), status_code=outcome.status)


def _route(act: str) -> Callable[[Request, Body], JSONResponse]:
    def post(request: Request, body: Body) -> JSONResponse:
        return _write(request, body, act)

    post.__name__ = f"post_{act}"
    return post


for _act in ACTIONS:
    router.add_api_route(f"/{_act}", _route(_act), methods=["POST"], name=f"evaluator_{_act}")
