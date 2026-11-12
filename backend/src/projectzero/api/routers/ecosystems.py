"""Ecosystems endpoints (review 022) — the old ``/api/eco``, ``/api/city_registry``, ``/api/coverage`` and
``/api/coverage_adopt``:

* ``GET  /api/ecosystems/eco?city=``        the city view (an empty city is ``Karlsruhe``, as before)
* ``GET  /api/ecosystems/registry``         the city registry
* ``GET  /api/ecosystems/coverage``         coverage by ecosystem and source family
* ``POST /api/ecosystems/coverage/adopt``   ``{id, confirm}`` -> the old answers, HTTP 200 (``{ok: false, error}``
                                            for a refusal); 409 before the legacy import (the write boundary)

A body that is not a JSON object is a 400. Nothing on these paths calls the network or a model.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from projectzero.api.routers.conviction import Body
from projectzero.core.db import read_only_transaction, transaction
from projectzero.dealflow.intake.postgres import IntakeClosedError
from projectzero.ecosystems.store import EcosystemsStore
from projectzero.network.view import BERLIN

router = APIRouter(prefix="/api/ecosystems", tags=["ecosystems"])
HOME_CITY = "Karlsruhe"  # the old route's default city


def _clock(request: Request) -> datetime:
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    return clock() if clock is not None else datetime.now(BERLIN)


def _read(request: Request, fn: Callable[[EcosystemsStore, datetime], object]) -> JSONResponse:
    settings = request.app.state.settings
    with read_only_transaction(settings.db_url) as conn:
        return JSONResponse(jsonable_encoder(fn(EcosystemsStore(conn, settings.schema), _clock(request))))


@router.get("/eco")
def get_eco(request: Request, city: str = "") -> JSONResponse:
    return _read(request, lambda store, now: store.eco(city or HOME_CITY, now))


@router.get("/registry")
def get_registry(request: Request) -> JSONResponse:
    return _read(request, lambda store, now: store.registry(now))


@router.get("/coverage")
def get_coverage(request: Request) -> JSONResponse:
    return _read(request, lambda store, now: store.coverage(now))


@router.post("/coverage/adopt")
def adopt(request: Request, body: Body) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    try:
        with transaction(settings.db_url) as conn:
            out = EcosystemsStore(conn, settings.schema).adopt(body.get("id"), body.get("confirm"), _clock(request))
    except IntakeClosedError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    return JSONResponse(jsonable_encoder(out))
