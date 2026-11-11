"""Conviction endpoints (review 011) — thin: parse, run the blocking store call in the threadpool, shape.

* ``GET  /api/conviction/pipeline``  the old ``/api/pipeline``: ``{week, ..., signals: [record + computed fields]}``
* ``GET  /api/conviction/meta``      the old ``/api/meta`` (Taste Map reference data)
* ``GET  /api/conviction/case?slug=`` the old ``/api/case`` (``case_prep.view``), READ-ONLY from the imported case
* ``POST /api/conviction/save``      the old ``/api/save`` body (``SaveBody``: the record fields, ``slug?``,
                                     ``inbox_id?``); the checklist sends ``{slug, company, verified}``.
                                     200 ``{ok, slug, keep?}`` · 400 / 404 ``{ok: false, error}`` ·
                                     409 ``{ok: false, error, slug, duplicate: true}``
* ``POST /api/conviction/status``    ``{slug, status}`` -> 200 ``{ok: true}`` · 400 / 404 ``{ok: false, error}``

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
from fastapi.responses import JSONResponse

from projectzero.conviction import entries, taste
from projectzero.conviction.store import DUPLICATE, ConvictionError, ConvictionStore
from projectzero.core.db import transaction
from projectzero.dealflow.candidates import DecisionError

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
