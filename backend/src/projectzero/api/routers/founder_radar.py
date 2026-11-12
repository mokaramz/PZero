"""Founder Radar endpoints (reviews 026a / 026b) — the old ``/api/founder_radar``, ``/api/radar_action``,
``/api/radar_import``, ``/api/radar_company``, ``/api/radar_promote``, ``/api/boardy_brief``, ``/api/radar_proposals``,
``/api/radar_pair``, ``/api/radar_review``, ``/api/radar_scan``, ``/api/radar_research`` and
``/api/radar_research_queue``, with the old bodies and answers:

* ``GET  /api/founder-radar``            the page (people, companies, leads, queue counts, health, coverage, geo,
                                         metrics, the state lists); reads never write (decision a)
* ``POST /api/founder-radar/action``     ``{id, action, ...}`` · 200 ``{ok, person}`` / 200 ``{ok: false, error}`` ·
                                         400 for an unknown ``state`` (decision f)
* ``POST /api/founder-radar/import``     ``{csv, include_email, label}``
* ``POST /api/founder-radar/company``    ``{key, fact | evidence | description | notes}``
* ``POST /api/founder-radar/promote``    ``{id, how, introduced_by, ...}``
* ``POST /api/founder-radar/boardy_brief`` ``{id, desired?, exclusions?}``
* ``POST /api/founder-radar/proposals``  ``{key}`` (a read)
* ``POST /api/founder-radar/pair``       ``{key, proposal, person}``
* ``POST /api/founder-radar/review``     ``{key, confirm, reject, bindings}``
* ``POST /api/founder-radar/scan``       ``{}`` -> the new health document (review 026b)
* ``POST /api/founder-radar/research``   ``{key}`` | ``{keys}`` | ``{}`` (the first 5 un-researched), ``refresh``
* ``POST /api/founder-radar/research_queue`` ``{batch}`` -> ``{ok, processed, remaining, done, failed, ...}``

The three runs (026b) use the network through ``founder_radar.runs`` (read, fetch with no transaction, one
deadline-bounded write); one run at a time (409 otherwise), 503 when the deadline cuts the write off. A write takes
the one write lock (then the people lock, the one lock order), loads the inputs, runs the pure route and applies its
``Outcome`` in ONE transaction: the people through the Network store (``person_events``; a merge through
``PeopleStore.merge_into``), the companies and research records and the metrics document through the Founder Radar
store (``radar_events``). Only real changes write (decision e). A strong-identifier conflict is the Network 409 and
writes nothing; before the import every write is a 409.
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
from projectzero.founder_radar import db, routes, runs
from projectzero.network.edits import NetworkError
from projectzero.network.view import BERLIN, berlin_today

router = APIRouter(prefix="/api/founder-radar", tags=["founder-radar"])
REQUEST_KEYS = ("id", "action", "key", "proposal", "person", "other", "state", "label")


def _clock(request: Request) -> datetime:
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    return clock() if clock is not None else datetime.now(BERLIN)


@router.get("")
def get_founder_radar(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    now = _clock(request)
    with read_only_transaction(settings.db_url) as conn:
        out = routes.view(db.inputs(conn, settings.schema), today=berlin_today(now), now=now)
    return JSONResponse(jsonable_encoder(out))


def _post(request: Request, body: Body, endpoint: str) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    now = _clock(request)
    fn = getattr(routes, {"import": "import_csv"}.get(endpoint, endpoint))
    detail = {"request": {k: body[k] for k in REQUEST_KEYS if isinstance(body.get(k), str | int | float | bool)}}
    try:
        if endpoint == "proposals":  # a read sent as a POST: never writes (decision a)
            with read_only_transaction(settings.db_url) as conn:
                outcome = fn(db.inputs(conn, settings.schema), body, today=berlin_today(now), now=now)
            return JSONResponse(jsonable_encoder(outcome.body), status_code=outcome.status)
        with transaction(settings.db_url) as conn:
            db.lock(conn, settings.schema)  # the one write lock, then the people lock (the one order)
            inputs = db.inputs(conn, settings.schema)
            outcome = fn(inputs, body, today=berlin_today(now), now=now)
            db.apply_outcome(conn, settings.schema, inputs, outcome, endpoint, detail)
    except IntakeClosedError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    except NetworkError as exc:  # raised inside the transaction: everything it wrote is rolled back
        return JSONResponse(jsonable_encoder({"ok": False, "error": str(exc), **exc.extra}), status_code=exc.status)
    return JSONResponse(jsonable_encoder(outcome.body), status_code=outcome.status)


def _route(endpoint: str) -> Callable[[Request, Body], JSONResponse]:
    def post(request: Request, body: Body) -> JSONResponse:
        return _post(request, body, endpoint)

    post.__name__ = f"post_{endpoint}"
    return post


for _endpoint in ("action", "import", "company", "promote", "boardy_brief", "proposals", "pair", "review"):
    router.add_api_route(f"/{_endpoint}", _route(_endpoint), methods=["POST"], name=f"founder_radar_{_endpoint}")


def _run(request: Request, body: Body, kind: str) -> JSONResponse:
    """The founder scan and company research (review 026b): ``runs.run``'s three phases, one run at a time."""
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    try:
        out = runs.run(settings.db_url, settings.schema, kind, body, _clock(request),
                       transport=getattr(request.app.state, "radar_transport", None),
                       resolver=getattr(request.app.state, "radar_resolver", None))  # fmt: skip
    except runs.RunRefused as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=exc.status)
    except IntakeClosedError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    except NetworkError as exc:  # a strong-identifier conflict in the write phase: rolled back
        return JSONResponse(jsonable_encoder({"ok": False, "error": str(exc), **exc.extra}), status_code=exc.status)
    return JSONResponse(jsonable_encoder(out))


def _run_route(kind: str) -> Callable[[Request, Body], JSONResponse]:
    def post(request: Request, body: Body) -> JSONResponse:
        return _run(request, body, kind)

    post.__name__ = f"post_{kind}"
    return post


for _kind in runs.KINDS:
    router.add_api_route(f"/{_kind}", _run_route(_kind), methods=["POST"], name=f"founder_radar_{_kind}")
