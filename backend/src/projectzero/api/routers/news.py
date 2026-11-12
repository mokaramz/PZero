"""News & Learning endpoints (reviews 028a / 028b), with the old bodies and answers:

* ``GET /api/news``                    the page payload (the old ``/api/news``), the old keys in the old order
* ``GET /api/news/weekly``             the weekly review (``weekly_review(record=False)``)
* ``GET /api/news/sources?window=``    the per-source metrics, computed live (30 / 90 / 180 / all; anything else 90)
* ``GET /api/news/refresh_status``     the stored event count and the archived runs; no run exists here (idle job)
* ``POST /api/news/outcome``           ``{event_id, decision}``: confirm records a Validation outcome; the answer of a
  confirmed event's next decision is the prior confirmation (``already``)
* ``POST /api/news/audit_miss``        a Validation miss audit from the story
* ``POST /api/news/backcast``          an early signal added to the story's ``backcast``

The reads run in one read-only transaction over ``news.inputs.load`` at the Berlin request clock and write nothing (the
curated seeding is applied in memory). A write runs in ONE transaction (review 028b): the production boundary and the
locks (intake, then news, then validation), the stored seeding (``news.store.ensure_seeded``, so the write sees a case
it just seeded), a fresh load, the pure write (``news.writes``), then its rows (the Validation row, the action line,
the event and its history). A refusal (400 ``{ok: false, error}``, the old texts) or any failure rolls ALL of it back.
* ``POST /api/news/refresh``           the refresh run (review 028c), synchronous with a whole-run deadline: the old
  ``{started, run_id, job, last, last_ok, events_total}``; 409 a run is already running (or before the import), 503 the
  write was cut off by the deadline (nothing saved)
* ``POST /api/news/sources/evaluate``  "Re-measure now": the evaluation alone -> ``{ok: true, evaluated_at}``; 409 / 503

The runs use the network only through ``news.runs`` (read, fetch with no transaction, one bounded write that re-reads
the stored inputs under the News lock); ``app.state.news_transport`` / ``news_resolver`` are the test seams.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from projectzero.api.routers.conviction import Body
from projectzero.core.db import read_only_transaction, transaction
from projectzero.dealflow.intake.postgres import IntakeClosedError
from projectzero.network.view import BERLIN, berlin_now, berlin_today
from projectzero.news import refresh_status, runs, sources_view, view, weekly_review, writes
from projectzero.news import store as news_store
from projectzero.news.inputs import load, load_status
from projectzero.news.inputs_model import NewsInputs, packaged_cases, with_entities
from projectzero.validation import store as validation_store
from projectzero.validation.core import entities
from projectzero.validation.inputs import load_docs
from projectzero.validation.inputs_model import inputs_from_docs as validation_inputs

router = APIRouter(prefix="/api/news", tags=["news"])


def _clock(request: Request) -> datetime:
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    return clock() if clock is not None else datetime.now(BERLIN)


def _inputs(request: Request) -> tuple[NewsInputs, datetime]:
    settings = request.app.state.settings
    now = _clock(request)
    with read_only_transaction(settings.db_url) as conn:
        return load(conn, settings.schema, now), now


def _ok(body: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(jsonable_encoder(body), status_code=status)


def _new_hex(request: Request) -> Callable[[], str]:
    seam: Callable[[], str] | None = getattr(request.app.state, "new_hex", None)
    return seam if seam is not None else lambda: secrets.token_hex(8)


@router.get("")
def get_news(request: Request) -> JSONResponse:
    inputs, now = _inputs(request)
    return _ok(view(inputs, berlin_today(now), berlin_now(now)))


@router.get("/weekly")
def get_weekly(request: Request) -> JSONResponse:
    inputs, now = _inputs(request)
    return _ok(weekly_review(inputs, berlin_today(now), berlin_now(now)))


@router.get("/sources")
def get_sources(request: Request, window: str = "90") -> JSONResponse:
    inputs, now = _inputs(request)
    return _ok(sources_view(inputs, window, berlin_today(now)))


@router.get("/refresh_status")
def get_refresh_status(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    with read_only_transaction(settings.db_url) as conn:
        inputs, stored = load_status(conn, settings.schema)
        active = news_store.run_active(conn, settings.schema)
    body = refresh_status(inputs)
    body["events_total"] = stored  # the stored events (the old ``len(load()["events"])``)
    body["job"]["running"] = active  # a refresh or evaluation run holds its lock right now (review 028c)
    return _ok(body)


# ── the writes (028b) ────────────────────────────────────────────────────────────────────────────────────────────────
_WRITES = {"outcome": writes.decide_outcome, "audit_miss": writes.audit_miss, "backcast": writes.add_backcast_signal}


def _write(request: Request, body: Body, endpoint: str) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    schema = settings.schema
    now = _clock(request)
    today, wall = berlin_today(now), berlin_now(now)
    try:
        with transaction(settings.db_url) as conn:
            news_store.lock(conn, schema)  # the one lock order: intake (the boundary), news, validation
            validation_store.lock(conn, schema)
            news_store.ensure_seeded(conn, schema, packaged_cases(), wall)  # seen by the load below
            v = validation_inputs(load_docs(conn, schema, now), today)
            n = with_entities(v.news_inputs, entities(v, today), v)  # the request's one entity build
            written = _WRITES[endpoint](n, body, today=today, now=wall, new_hex=_new_hex(request), validation=v)
            validation_store.append(conn, schema, written.validation_appends)  # the old order: Validation first
            if written.action_line is not None:
                news_store.append_action(conn, schema, written.action_line)
            if written.event is not None:
                event_id, record = written.event
                news_store.save_event(conn, schema, event_id, record, "backcast", {"request": dict(body)})
    except IntakeClosedError as exc:
        return _ok({"ok": False, "error": str(exc)}, 409)
    except ValueError as exc:  # the old route: a ValueError (NewsError, ValidationError, a bad case file) is a 400
        return _ok({"ok": False, "error": str(exc)}, 400)
    return _ok(written.answer)


def _route(endpoint: str) -> Callable[[Request, Body], JSONResponse]:
    def post(request: Request, body: Body) -> JSONResponse:
        return _write(request, body, endpoint)

    post.__name__ = f"post_{endpoint}"
    return post


for _endpoint in _WRITES:
    router.add_api_route(f"/{_endpoint}", _route(_endpoint), methods=["POST"], name=f"news_{_endpoint}")


# ── the runs (028c) ──────────────────────────────────────────────────────────────────────────────────────────────────
@router.post("/refresh")
def post_refresh(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    try:
        out = runs.refresh_run(settings.db_url, settings.schema, _clock(request),
                               transport=getattr(request.app.state, "news_transport", None),
                               resolver=getattr(request.app.state, "news_resolver", None),
                               new_hex=getattr(request.app.state, "new_hex", None))  # fmt: skip
    except IntakeClosedError as exc:
        return _ok({"ok": False, "error": str(exc)}, 409)
    except runs.RunRefused as exc:
        return _ok({"ok": False, "error": str(exc)}, exc.status)
    return _ok(out)


@router.post("/sources/evaluate")
def post_evaluate(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    try:
        out = runs.evaluate_run(settings.db_url, settings.schema, _clock(request))
    except IntakeClosedError as exc:
        return _ok({"ok": False, "error": str(exc)}, 409)
    except runs.RunRefused as exc:
        return _ok({"ok": False, "error": str(exc)}, exc.status)
    return _ok(out)
