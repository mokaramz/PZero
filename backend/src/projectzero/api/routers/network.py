"""Network endpoints (review 013) — thin: parse, run the blocking store call in the threadpool, shape.

Reads (the old bodies, computed with the request's clock; today = the Europe/Berlin date; reads never write):

* ``GET  /api/network/people``     the old ``/api/people``: ``{people: [record + introduced_by_name, chain,
                                   recommended_names, days_since_touch, due], strengths, potential}``, due first,
                                   then the stalest
* ``GET  /api/network/graph``      the old ``/api/graph``: ``{forest: [{id, name, role, company, founder_potential,
                                   strength, startups, watch, children}]}``
* ``GET  /api/network/watchlist``  the old ``/api/watchlist``: ``{people}`` (the listing, watched people only)

Writes (each ONE transaction; refused with 409 before the legacy import):

* ``POST /api/network/person_save``  add ``{name, ...FIELDS}`` / edit ``{id, ...FIELDS}`` (follow-up, log contact,
  judgment are edits) -> 200 ``{ok: true, id}`` · 400 ``{ok: false, error}`` · 404 ``{ok: false, error, id}`` (edit of
  an unknown id) · 409 ``{ok: false, error, id, duplicate: true}`` (add: the generated id exists) · 409 ``{ok: false,
  error, id, radar_name: true}`` (renaming a Founder Radar person) · 409 ``{ok: false, error, identifier: {kind,
  value}, owner}`` (a strong identifier another person holds)
* ``POST /api/network/talented``     ``{id, persons: [{name, note}]}`` -> 200 ``{ok: true, created: [id]}`` · 400
* ``POST /api/network/watch_log``    ``{id, note}`` -> 200 ``{ok: true}`` · 400

A body that is not a JSON object is a 400 (the old ``json_body``).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import psycopg
from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from projectzero.api.routers.conviction import Body
from projectzero.core.db import transaction
from projectzero.dealflow.intake.postgres import IntakeClosedError
from projectzero.network import edits
from projectzero.network.edits import NetworkError
from projectzero.network.people import slug
from projectzero.network.store import PeopleStore
from projectzero.network.view import BERLIN

router = APIRouter(prefix="/api/network", tags=["network"])
IDENTIFIER_RACE = "a strong identifier of this person already belongs to another person — nothing was saved"


def _clock(request: Request) -> datetime:
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    return clock() if clock is not None else datetime.now(BERLIN)


def _error(exc: NetworkError) -> JSONResponse:
    return JSONResponse(jsonable_encoder({"ok": False, "error": str(exc), **exc.extra}), status_code=exc.status)


@router.get("/people")
def get_people(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    with transaction(settings.db_url) as conn:
        return JSONResponse(jsonable_encoder(PeopleStore(conn, settings.schema).people_view(_clock(request))))


@router.get("/graph")
def get_graph(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    with transaction(settings.db_url) as conn:
        return JSONResponse(jsonable_encoder(PeopleStore(conn, settings.schema).graph_view()))


@router.get("/watchlist")
def get_watchlist(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    with transaction(settings.db_url) as conn:
        return JSONResponse(jsonable_encoder(PeopleStore(conn, settings.schema).watchlist_view(_clock(request))))


_VALIDATE: dict[str, Callable[[dict[str, Any]], Any]] = {
    "save": edits.validate_save,
    "talented": edits.validate_talented,
    "watch_log": edits.validate_watch_log,
}


def _write(request: Request, body: Body, action: str) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    now = _clock(request)
    try:
        _VALIDATE[action](body)  # bad requests never open a connection
        with transaction(settings.db_url) as conn:
            store = PeopleStore(conn, settings.schema)
            out = getattr(store, action)(body, now)
    except NetworkError as exc:  # raised inside the transaction: everything it wrote is rolled back
        return _error(exc)
    except IntakeClosedError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    except psycopg.errors.UniqueViolation as exc:  # the last line of defence, after the rollback
        name = exc.diag.constraint_name
        if name == "person_identifiers_strong_unique":
            return JSONResponse({"ok": False, "error": IDENTIFIER_RACE}, status_code=409)
        if name == "people_pkey" and action == "save" and not body.get("id"):
            pid = slug(str(body.get("name") or ""))
            return JSONResponse({"ok": False, "error": edits.DUPLICATE, "id": pid, "duplicate": True}, status_code=409)
        raise
    return JSONResponse(jsonable_encoder(out))


@router.post("/person_save")
def person_save(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, "save")


@router.post("/talented")
def talented(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, "talented")


@router.post("/watch_log")
def watch_log(request: Request, body: Body) -> JSONResponse:
    return _write(request, body, "watch_log")
