"""Map endpoints (review 025) — the old ``/api/map``, ``/api/geo_intel``, ``/api/geo_ecosystem``, ``/api/geo_search``
and ``/api/sourcing_day``, with the old bodies and answers:

* ``GET  /api/map/pins``                 the pins (geocoded in memory, decision a) plus ``new_signals`` (decision c)
* ``GET  /api/map/intel``                ecosystem states, Where to go, coverage gaps, the cards
* ``GET  /api/map/ecosystem?city=``      "Why here?" · 404 ``{ok: false, error: "unknown or unplaced ecosystem: X"}``
* ``GET  /api/map/search?q=``            ``{results: [...]}``
* ``POST /api/map/sourcing_day``         ``{city, date}`` -> the day plan · 400 ``{ok: false, error}``; nothing stored

Every endpoint only reads, in one read-only transaction, over ``map.inputs.load`` at the Berlin request clock. There
is no cache (decision g): each request computes from the database.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from projectzero.api.routers.conviction import Body
from projectzero.core.db import read_only_transaction
from projectzero.map import intel, pins
from projectzero.map.inputs import load
from projectzero.map.inputs_model import MapInputs
from projectzero.network.view import BERLIN, berlin_today

router = APIRouter(prefix="/api/map", tags=["map"])
BUILT_AT = "%Y-%m-%dT%H:%M:%S"  # the old ``time.strftime`` format of ``built_at``


def _clock(request: Request) -> datetime:
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    return clock() if clock is not None else datetime.now(BERLIN)


def _inputs(request: Request, *, for_pins: bool = False) -> tuple[MapInputs, datetime]:
    settings = request.app.state.settings
    now = _clock(request)
    with read_only_transaction(settings.db_url) as conn:
        return load(conn, settings.schema, now, for_pins=for_pins), now


def _ok(body: Any) -> JSONResponse:
    return JSONResponse(jsonable_encoder(body))


def _error(exc: Exception, status: int) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(exc).strip("'")}, status_code=status)  # the old ApiError text


@router.get("/pins")
def get_pins(request: Request) -> JSONResponse:
    inputs, now = _inputs(request, for_pins=True)
    return _ok(pins.map_view(inputs, berlin_today(now)))


@router.get("/intel")
def get_intel(request: Request) -> JSONResponse:
    inputs, now = _inputs(request)
    berlin = now.astimezone(BERLIN)
    return _ok(intel.view(inputs, berlin_today(now), built_at=berlin.strftime(BUILT_AT)))


@router.get("/ecosystem")
def get_ecosystem(request: Request, city: str = "") -> JSONResponse:
    inputs, now = _inputs(request)
    try:
        return _ok(intel.detail(inputs, city, berlin_today(now)))
    except KeyError as exc:
        return _error(exc, 404)


@router.get("/search")
def get_search(request: Request, q: str = "") -> JSONResponse:
    inputs, now = _inputs(request)
    return _ok({"results": intel.search(inputs, q, berlin_today(now))})


@router.post("/sourcing_day")
def post_sourcing_day(request: Request, body: Body) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    inputs, now = _inputs(request)
    try:
        plan = intel.sourcing_day(inputs, str(body.get("city") or ""), str(body.get("date") or ""), berlin_today(now))
    except (KeyError, ValueError) as exc:
        return _error(exc, 400)
    return _ok(plan)
