"""News & Learning endpoints (review 028a, the read side), with the old answers:

* ``GET /api/news``                    the page payload (the old ``/api/news``), the old keys in the old order
* ``GET /api/news/weekly``             the weekly review (``weekly_review(record=False)``)
* ``GET /api/news/sources?window=``    the per-source metrics, computed live (30 / 90 / 180 / all; anything else 90)
* ``GET /api/news/refresh_status``     the refresh status from the archives; no run exists here, so the job is idle

Each reads in one read-only transaction over ``news.inputs.load`` at the Berlin request clock and writes nothing (the
curated seeding is applied in memory, decision a). The writes (028b: outcome decisions, miss audits, backcast
signals) and the refresh / source evaluation runs (028c) arrive with their reviews.
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
from projectzero.news import refresh_status, sources_view, view, weekly_review
from projectzero.news.inputs import load, load_status
from projectzero.news.inputs_model import NewsInputs

router = APIRouter(prefix="/api/news", tags=["news"])


def _clock(request: Request) -> datetime:
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    return clock() if clock is not None else datetime.now(BERLIN)


def _inputs(request: Request) -> tuple[NewsInputs, datetime]:
    settings = request.app.state.settings
    now = _clock(request)
    with read_only_transaction(settings.db_url) as conn:
        return load(conn, settings.schema, now), now


def _ok(body: Any) -> JSONResponse:
    return JSONResponse(jsonable_encoder(body))


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
        return _ok(refresh_status(load_status(conn, settings.schema)))
