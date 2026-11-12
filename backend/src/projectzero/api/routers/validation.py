"""Validation endpoints (review 027a, the read side) — the old ``GET /api/validation`` and
``GET /api/validation_scout_packet``, with the old answers:

* ``GET /api/validation``                     the whole payload, the old keys in the old order; today's daily snapshot
  is appended IN MEMORY under the old last-row rule, never stored (decision a)
* ``GET /api/validation/scout_packet?cycle=``  the Scout 00 feedback packet, read only (decision c: "mark as sent" is
  027b; its News and source-network learnings are deferred with a visible reason)

Both only read, in one read-only transaction over ``validation.inputs.load`` at the Berlin request clock. The writes
(record outcome, audit, retract, benchmark import, the packet mark) arrive with review 027b.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from projectzero.core.db import read_only_transaction
from projectzero.network.view import BERLIN, berlin_now, berlin_today
from projectzero.validation import scout_packet, view
from projectzero.validation.inputs import load
from projectzero.validation.inputs_model import ValidationInputs

router = APIRouter(prefix="/api/validation", tags=["validation"])


def _clock(request: Request) -> datetime:
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    return clock() if clock is not None else datetime.now(BERLIN)


def _inputs(request: Request) -> tuple[ValidationInputs, datetime]:
    settings = request.app.state.settings
    now = _clock(request)
    with read_only_transaction(settings.db_url) as conn:
        return load(conn, settings.schema, now), now


def _ok(body: Any) -> JSONResponse:
    return JSONResponse(jsonable_encoder(body))


@router.get("")
def get_validation(request: Request) -> JSONResponse:
    inputs, now = _inputs(request)
    return _ok(view(inputs, berlin_today(now), berlin_now(now)))


@router.get("/scout_packet")
def get_scout_packet(request: Request, cycle: str = "") -> JSONResponse:
    inputs, now = _inputs(request)
    return _ok(scout_packet(inputs, cycle, berlin_today(now), berlin_now(now)))
