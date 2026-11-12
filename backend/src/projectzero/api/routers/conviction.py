"""Conviction endpoints (review 011) — thin: parse, run the blocking store call in the threadpool, shape.

* ``GET  /api/conviction/pipeline``  the old ``/api/pipeline``: ``{week, ..., signals: [record + computed fields]}``
* ``GET  /api/conviction/meta``      the old ``/api/meta`` (Taste Map reference data)
* ``GET  /api/conviction/case?slug=`` the old ``/api/case`` (``case_prep.view``), READ-ONLY from the imported case
* ``POST /api/conviction/save``      the old ``/api/save`` body (``SaveBody``: the record fields, ``slug?``,
                                     ``inbox_id?``); the checklist sends ``{slug, company, verified}``.
                                     200 ``{ok, slug, keep?}`` · 400 / 404 ``{ok: false, error}`` ·
                                     409 ``{ok: false, error, slug, duplicate: true}``
* ``POST /api/conviction/status``    ``{slug, status}`` -> 200 ``{ok: true}`` · 400 / 404 ``{ok: false, error}``
* ``POST /api/conviction/imq_trigger`` the old ``/api/imq_trigger`` (review 024): ``{slug, kind, date, url, fact,
                                     confirm}`` -> 200 ``{ok, trigger}`` · 200 ``{ok: false, error}`` (nothing written)

Review 019 (the old ``/api/radar``, ``/memo``, ``/email``, ``/weekly`` and ``/run``):

* ``GET  /api/conviction/radar``     ``{high, emerging, wildcard, research_queue, gated, watch}``; the first view that
                                     places an entry in the Top 10 credits its Radar milestone (decision a)
* ``GET  /api/conviction/radar.html`` the old ``weekly_memo.html`` as a download (decision c); credits like the view
* ``GET  /api/conviction/memo?c=``   ``{text}`` · 404 ``{error: "not found"}``
* ``GET  /api/conviction/email?c=``  ``{text}`` · 404 ``{error: "not found"}``
* ``POST /api/conviction/weekly``    ``{insight?, question?}`` -> ``{text}``; nothing is written

A body that is not a JSON object is a 400 (the old ``json_body``).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse

from projectzero.conviction import entries, radar, taste
from projectzero.conviction.store import DUPLICATE, ConvictionError, ConvictionStore, record_of
from projectzero.core.db import read_only_transaction, transaction
from projectzero.dealflow.candidates import DecisionError
from projectzero.dealflow.intake.postgres import IntakeClosedError
from projectzero.evaluator import routes as evaluator_routes
from projectzero.network.view import berlin_today

router = APIRouter(prefix="/api/conviction", tags=["conviction"])
UNIQUE_ENTRY = frozenset({"conviction_entries_slug_key", "conviction_entries_company_id_key"})


class BadBody(ValueError):
    pass


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON")


async def json_body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw.strip():
        return {}
    try:
        body = json.loads(raw, parse_constant=_reject_constant)  # NaN / Infinity can't be stored (jsonb)
    except ValueError as e:
        raise BadBody(f"request body is not valid JSON ({str(e)[:80]})") from e
    if not isinstance(body, dict):
        raise BadBody("request body is not valid JSON (request body must be a JSON object)")
    return body


async def body_or_error(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        return await json_body(request)
    except BadBody as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


Body = Annotated[dict[str, Any] | JSONResponse, Depends(body_or_error)]


def _clock(request: Request) -> datetime:
    clock: Callable[[], datetime] = getattr(request.app.state, "clock", datetime.now)
    return clock()


def refuse_early(body: dict[str, Any], action: str, now: datetime) -> None:
    if action == "save" and (problems := entries.validate_entry(body, now.date())):
        raise ConvictionError(400, entries.refusal(problems))
    if action == "status" and body.get("status") not in entries.STATUSES:
        raise ConvictionError(400, "status must be one of: " + ", ".join(entries.STATUSES))


def _error(exc: ConvictionError | DecisionError) -> JSONResponse:
    return JSONResponse(jsonable_encoder({"ok": False, "error": str(exc), **exc.extra}), status_code=exc.status)


@router.get("/pipeline")
def get_pipeline(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    with transaction(settings.db_url) as conn:
        return JSONResponse(jsonable_encoder(ConvictionStore(conn, settings.schema).pipeline_view(_clock(request))))


@router.get("/case")
def get_case(request: Request, slug: str = "") -> JSONResponse:
    """Read-only: the imported prepared case (no ``case_seen`` write, no preparation)."""
    slug = slug.strip()
    if not slug:
        return JSONResponse({"ok": False, "error": "slug required"}, status_code=400)
    settings = request.app.state.settings
    with transaction(settings.db_url) as conn:
        return JSONResponse(jsonable_encoder(ConvictionStore(conn, settings.schema).case_view(slug, _clock(request))))


@router.get("/meta")
def get_meta() -> dict[str, Any]:
    return taste.meta()


def _write(request: Request, body: Body, action: str) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    now = _clock(request)
    try:
        refuse_early(body, action, now)  # bad requests never open a connection
        with transaction(settings.db_url) as conn:
            store = ConvictionStore(conn, settings.schema)
            out = store.save(body, now) if action == "save" else store.set_status(body, now)
    except (ConvictionError, DecisionError) as exc:
        return _error(exc)
    except psycopg.errors.UniqueViolation as exc:  # last line of defence: the schema's one entry per slug / company
        if exc.diag.constraint_name not in UNIQUE_ENTRY:
            raise
        with transaction(settings.db_url) as conn:
            existing = ConvictionStore(conn, settings.schema).existing_slug(body)
        return JSONResponse({"ok": False, "error": DUPLICATE, "slug": existing, "duplicate": True}, status_code=409)
    return JSONResponse(jsonable_encoder(out))


@router.post("/save")
def save(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, "save")


@router.post("/status")
def status(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, "status")


@router.post("/imq_trigger")
def imq_trigger(request: Request, body: Body) -> JSONResponse:
    """The dated why-now trigger (review 024): the records whose radar slug is ``slug`` gain it, with their IMQ
    snapshot and one ``imq_trigger`` event each, only when the answer is ``ok``."""
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    now = _clock(request)
    try:
        with transaction(settings.db_url) as conn:
            store = ConvictionStore(conn, settings.schema)
            store.lock()
            rows = store.entry_rows()
            out = evaluator_routes.imq_trigger(body, conviction=[record_of(r) for r in rows], today=berlin_today(now),
                                               now=now)  # fmt: skip
            if out.conviction:
                request_ids = {k: body.get(k) for k in ("slug", "kind", "date") if isinstance(body.get(k), str)}
                store.write_records(rows, out.conviction, "imq_trigger", {"request": request_ids}, now)
    except IntakeClosedError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    return JSONResponse(jsonable_encoder(out.body), status_code=out.status)


# ── review 019: the Radar, memos, emails, the weekly update ────────────────────────────────────────────────────
NOT_FOUND = {"error": "not found"}  # the old routes' 404 body
RADAR_FILE = "weekly_memo.html"  # the old output's name


def radar_file_bytes(doc: str) -> bytes:
    """The bytes the old app wrote: UTF-8 in Windows text mode (every newline as CRLF), its only platform."""
    return doc.replace("\n", "\r\n").encode("utf-8")


def _credit_radar(request: Request, placed: set[str]) -> None:
    """The view-time milestone (decision a): a short write under the Conviction lock, only when something is due.
    Before the legacy import the production schema is closed to writes: the Radar is then shown without crediting."""
    settings = request.app.state.settings
    try:
        with transaction(settings.db_url) as conn:
            ConvictionStore(conn, settings.schema).credit_radar(placed)
    except IntakeClosedError:
        pass


def _radar_read(request: Request, now: datetime) -> tuple[list[dict[str, Any]], dict[str, Any], set[str], bool]:
    settings = request.app.state.settings
    with read_only_transaction(settings.db_url) as conn:
        store = ConvictionStore(conn, settings.schema)
        signals = store.signals(now)
        view, placed = store.radar_of(signals)
        return signals, view, placed, store.radar_due(placed)


@router.get("/radar")
def get_radar(request: Request) -> JSONResponse:
    _, view, placed, due = _radar_read(request, _clock(request))
    if due:
        _credit_radar(request, placed)
    return JSONResponse(jsonable_encoder(view))  # composed before the credit, as the old view returned it


@router.get("/radar.html")
def get_radar_html(request: Request) -> HTMLResponse:
    """The old ``POST /api/run`` without files: the Radar document, credited like the view."""
    now = _clock(request)
    signals, _, placed, due = _radar_read(request, now)
    if due:
        _credit_radar(request, placed)
    doc = radar.render_radar(signals, berlin_today(now))
    return HTMLResponse(radar_file_bytes(doc), headers={"Content-Disposition": f'attachment; filename="{RADAR_FILE}"'})


def _signal_text(request: Request, slug: str, render: Callable[[dict[str, Any], datetime], str]) -> JSONResponse:
    settings = request.app.state.settings
    now = _clock(request)
    with read_only_transaction(settings.db_url) as conn:
        entry = ConvictionStore(conn, settings.schema).signal(slug, now)
    if entry is None:
        return JSONResponse(NOT_FOUND, status_code=404)
    return JSONResponse({"text": render(entry, now)})


@router.get("/memo")
def get_memo(request: Request, c: str = "") -> JSONResponse:
    return _signal_text(request, c, lambda e, now: radar.memo(e, berlin_today(now)))


@router.get("/email")
def get_email(request: Request, c: str = "") -> JSONResponse:
    return _signal_text(request, c, lambda e, _now: radar.email(e))


@router.post("/weekly")
def post_weekly(request: Request, body: Body) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    with read_only_transaction(settings.db_url) as conn:
        text = ConvictionStore(conn, settings.schema).weekly_text(body, _clock(request))
    return JSONResponse({"text": text})
