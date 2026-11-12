"""Founder Radar endpoints (review 026a, part one: no network) — the old ``/api/founder_radar``, ``/api/radar_action``,
``/api/radar_import``, ``/api/radar_company``, ``/api/radar_promote``, ``/api/boardy_brief``, ``/api/radar_proposals``,
``/api/radar_pair`` and ``/api/radar_review``, with the old bodies and answers:

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

The scan and the research crawl are review 026b. A write takes the one write lock (then the people lock, the one lock
order), loads the inputs, runs the pure route and applies its ``Outcome`` in ONE transaction: the people through the
Network store (``person_events``; a merge through ``PeopleStore.merge_into``), the companies and research records and
the metrics document through the Founder Radar store (``radar_events``). Only real changes write (decision e). A
strong-identifier conflict is the Network 409 and writes nothing; before the import every write is a 409.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.api.routers.conviction import Body
from projectzero.conviction.store import ConvictionStore, record_of
from projectzero.core.db import read_only_transaction, schema_ident, transaction
from projectzero.dealflow.intake.postgres import IntakeClosedError
from projectzero.founder_radar import routes
from projectzero.founder_radar.store import FounderRadarStore
from projectzero.network.edits import NetworkError
from projectzero.network.store import PeopleStore, load_people
from projectzero.network.view import BERLIN, berlin_today

router = APIRouter(prefix="/api/founder-radar", tags=["founder-radar"])
DOCUMENTS = {"health": "radar_health.json", "regions": "radar_regions.json", "metrics": "radar_metrics.json"}
METRICS = DOCUMENTS["metrics"]
EVENT_ACTION = {"action": "action", "import": "import", "company": "company", "promote": "promote",
                "boardy_brief": "boardy", "pair": "pair", "review": "review"}  # fmt: skip
REQUEST_KEYS = ("id", "action", "key", "proposal", "person", "other", "state", "label")


def _clock(request: Request) -> datetime:
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    return clock() if clock is not None else datetime.now(BERLIN)


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _documents(conn: Any, schema: str) -> dict[str, Any]:
    """The radar documents kept as ``documents`` rows. A row still equal to its byte-exact archive is read from the
    archive, so its key order is the old one (JSONB sorted it); a row written since is read as stored."""
    s = schema_ident(schema)
    keys = list(DOCUMENTS.values())
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL("select key, body from {}.documents where key = any(%s)").format(s), (keys,))
        stored = {r["key"]: r["body"] for r in cur.fetchall()}
        cur.execute(sql.SQL("select path, raw from {}.legacy_documents where path = any(%s)").format(s), (keys,))
        archived = {r["path"]: r["raw"] for r in cur.fetchall()}
    out: dict[str, Any] = {}
    for field, key in DOCUMENTS.items():
        body = stored.get(key)
        if key in archived:
            try:
                parsed = json.loads(bytes(archived[key]).decode("utf-8-sig"))
            except (UnicodeDecodeError, ValueError):
                parsed = None
            if parsed is not None and (body is None or _same(parsed, body)):
                body = parsed
        out[field] = body
    return out


def _tombstones(conn: Any, schema: str) -> frozenset[str]:
    s = schema_ident(schema)
    with conn.cursor() as cur:
        cur.execute(sql.SQL("select id from {}.people where merged_into is not null").format(s))
        return frozenset(str(r[0]) for r in cur.fetchall())


def _inputs(conn: Any, schema: str) -> routes.Inputs:
    store = FounderRadarStore(conn, schema)
    return routes.Inputs(
        people=load_people(conn, schema),
        companies=store.load_companies(),
        research=store.load_research(),
        signals=[record_of(r) for r in ConvictionStore(conn, schema).entry_rows()],
        reserved_ids=_tombstones(conn, schema),
        **_documents(conn, schema),
    )


@router.get("")
def get_founder_radar(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    now = _clock(request)
    with read_only_transaction(settings.db_url) as conn:
        out = routes.view(_inputs(conn, settings.schema), today=berlin_today(now), now=now)
    return JSONResponse(jsonable_encoder(out))


def _apply(conn: Any, schema: str, inputs: routes.Inputs, outcome: routes.Outcome, endpoint: str,
           detail: dict[str, Any]) -> None:  # fmt: skip
    """Write what the outcome changed, in the caller's transaction (under both locks)."""
    people = PeopleStore(conn, schema)
    action = EVENT_ACTION[endpoint]
    if outcome.people is not None and outcome.people_changed:
        new_by_id = {str(p.get("id")): p for p in outcome.people if isinstance(p, dict)}
        survivor = outcome.merged[0] if outcome.merged else None
        ids = [str(i) for i in outcome.people_changed if str(i) != survivor]
        live = people._lock_rows(ids)  # the one lock order; a person merged meanwhile is absent
        before_by_id = {str(p.get("id")): p for p in inputs.people if isinstance(p, dict)}
        for pid in ids:
            if pid in before_by_id and pid not in live:
                continue  # merged by a concurrent request: absent for this write (revision 2)
            people._write(pid, before_by_id.get(pid), new_by_id[pid], "radar",
                          {**detail, "endpoint": endpoint})  # fmt: skip
        if outcome.merged is not None:
            s_id, t_id = outcome.merged
            people.merge_into(s_id, t_id, new_by_id[s_id], {**detail, "endpoint": endpoint})
    radar = FounderRadarStore(conn, schema)
    if outcome.companies is not None:
        radar.write_records("companies", inputs.companies, outcome.companies, action, detail)
    if outcome.research is not None:
        radar.write_records("research", inputs.research, outcome.research, action, detail)
    if outcome.metrics is not None:
        radar.write_document(METRICS, outcome.metrics, "snapshot", {**detail, "endpoint": endpoint})


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
                outcome = fn(_inputs(conn, settings.schema), body, today=berlin_today(now), now=now)
            return JSONResponse(jsonable_encoder(outcome.body), status_code=outcome.status)
        with transaction(settings.db_url) as conn:
            FounderRadarStore(conn, settings.schema).lock()  # the one write lock ...
            PeopleStore(conn, settings.schema)._lock()  # ... then the people lock (the one order)
            inputs = _inputs(conn, settings.schema)
            outcome = fn(inputs, body, today=berlin_today(now), now=now)
            _apply(conn, settings.schema, inputs, outcome, endpoint, detail)
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
