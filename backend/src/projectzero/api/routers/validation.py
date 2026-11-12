"""Validation endpoints (reviews 027a / 027b), with the old bodies and answers:

* ``GET  /api/validation``                     the whole payload, the old keys in the old order; today's daily
  snapshot is answered IN MEMORY under the old last-row rule, never stored (027a decision a)
* ``GET  /api/validation/scout_packet?cycle=``  the Scout 00 feedback packet (read only)
* ``POST /api/validation/outcome``             record an outcome -> ``{ok: true, entry}``
* ``POST /api/validation/audit``               a miss or false-positive audit -> ``{ok: true, entry}``
* ``POST /api/validation/retract``             withdraw an outcome or audit -> ``{ok: true, entry}``
* ``POST /api/validation/benchmark_import``    a benchmark export: preview, or ``confirm`` -> the old summary
* ``POST /api/validation/scout_packet``        log the handover of the packet the page showed ``{cycle, generated,
  sha}`` -> the packet; a packet that changed since it was shown is a 409 and logs nothing (027b decision f)

The reads run in one read-only transaction over ``validation.inputs.load`` at the Berlin request clock. A write takes
the production write boundary and the one Validation lock (``validation.store.lock``: 409 before the import), loads
what it needs in the SAME transaction, runs the pure write (``validation.writes``) and appends its lines in order, all
in one transaction: a refusal (400 ``{ok: false, error}``, the old texts) or any failure writes nothing.
"""

from __future__ import annotations

import secrets
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
from projectzero.network.view import BERLIN, berlin_now, berlin_today
from projectzero.validation import ValidationError, scout_packet, store, view, writes
from projectzero.validation.inputs import load
from projectzero.validation.inputs_model import ValidationInputs, inputs_from_docs

router = APIRouter(prefix="/api/validation", tags=["validation"])


def _clock(request: Request) -> datetime:
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    return clock() if clock is not None else datetime.now(BERLIN)


def _new_hex(request: Request) -> Callable[[], str]:
    seam: Callable[[], str] | None = getattr(request.app.state, "new_hex", None)
    return seam if seam is not None else lambda: secrets.token_hex(8)


def _inputs(request: Request) -> tuple[ValidationInputs, datetime]:
    settings = request.app.state.settings
    now = _clock(request)
    with read_only_transaction(settings.db_url) as conn:
        return load(conn, settings.schema, now), now


def _ok(body: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(jsonable_encoder(body), status_code=status)


@router.get("")
def get_validation(request: Request) -> JSONResponse:
    inputs, now = _inputs(request)
    return _ok(view(inputs, berlin_today(now), berlin_now(now)))


@router.get("/scout_packet")
def get_scout_packet(request: Request, cycle: str = "") -> JSONResponse:
    inputs, now = _inputs(request)
    return _ok(scout_packet(inputs, cycle, berlin_today(now), berlin_now(now)))


# ── the writes (027b) ────────────────────────────────────────────────────────────────────────────────────────────────
def _logs_only(conn: psycopg.Connection[Any], schema: str, now: datetime) -> ValidationInputs:
    """A retraction reads only the outcome and audit logs (it searches them by id)."""
    return inputs_from_docs(store.texts(conn, schema), berlin_today(now))


# what each write reads, under the lock: an outcome nothing; a retraction the two logs; the rest every store
_NEEDS: dict[str, Callable[[psycopg.Connection[Any], str, datetime], ValidationInputs]] = {
    "outcome": lambda _conn, _schema, _now: ValidationInputs(),
    "retract": _logs_only,
    "audit": load,
    "benchmark_import": load,
    "scout_packet": load,
}


def _write(request: Request, body: Body, endpoint: str) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    now = _clock(request)
    today, wall = berlin_today(now), berlin_now(now)
    try:
        with transaction(settings.db_url) as conn:
            store.lock(conn, settings.schema)
            inputs = _NEEDS[endpoint](conn, settings.schema, now)
            if endpoint == "scout_packet":
                written = writes.packet_mark(inputs, body, today=today, now=wall)
            else:
                fn = getattr(writes, endpoint)
                written = fn(inputs, body, today=today, now=wall, new_hex=_new_hex(request))
            store.append(conn, settings.schema, written.appends)
    except IntakeClosedError as exc:
        return _ok({"ok": False, "error": str(exc)}, 409)
    except writes.StalePacket as exc:
        return _ok({"ok": False, "error": str(exc)}, 409)
    except ValidationError as exc:
        return _ok({"ok": False, "error": str(exc)}, 400)
    return _ok(written.answer)


def _route(endpoint: str) -> Callable[[Request, Body], JSONResponse]:
    def post(request: Request, body: Body) -> JSONResponse:
        return _write(request, body, endpoint)

    post.__name__ = f"post_{endpoint}"
    return post


for _endpoint in ("outcome", "audit", "retract", "benchmark_import", "scout_packet"):
    router.add_api_route(f"/{_endpoint}", _route(_endpoint), methods=["POST"], name=f"validation_{_endpoint}")
