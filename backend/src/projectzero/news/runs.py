"""The News refresh run and the standalone source evaluation (review 028c), in the three phases of the Events scan
(``events/scan.py``) and the Founder Radar runs (``founder_radar/runs.py``), so no transaction is open while the
network is used:

1. **read** (one short transaction bounded by the time fetching must stop, closed before any request; it only reads):
   the write boundary first (before the import
   every run is a 409 and nothing is fetched), then only what the fetch plan reads (the extra feeds, the cooldowns);
   the run id comes from the ``new_hex`` seam.
2. **fetch** (no transaction): ``refresh.fetch_all`` through ``fetching.FeedFetch`` (``core.net``: the News host
   policy on every hop, the pinned transport, verified TLS), bounded by each feed's timeout and the run's budget
   (``events.scan.budget``: a write-time reserve is kept back). Its only result is the fetched items per feed.
3. **write** (ONE transaction bounded by the same budget, ``events.scan.bounded_transaction``: the connect, the lock
   wait, every statement and the commit; the deadline is checked again before commit): the News write lock,
   ``ensure_seeded``, then the CURRENT stored inputs are read again and ``refresh.apply`` matches, derives and
   evaluates against them (Codex H-257: a backcast committed during the fetch is kept), and its rows are written. A
   write the deadline cuts off is a 503 and saves nothing.

One run at a time: a SESSION advisory lock (``news.store.RUN_LOCK``) taken with ``pg_try_advisory_lock`` on a dedicated
connection and released on every exit path; the refresh and the standalone evaluation share it (a second one is the
old 409 "A news refresh is already running."), and the status reports it as ``job.running``.
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import psycopg

from projectzero.core import net
from projectzero.core.db import connect
from projectzero.dealflow.intake.postgres import ensure_intake_open
from projectzero.events.edits import EventsError
from projectzero.events.scan import bounded_transaction, budget
from projectzero.network.view import berlin_now, berlin_today
from projectzero.news import refresh
from projectzero.news import store as news_store
from projectzero.news.fetching import FeedFetch
from projectzero.news.inputs_model import base_from_docs, packaged_cases
from projectzero.validation.inputs import load_docs
from projectzero.validation.inputs_model import ValidationInputs
from projectzero.validation.inputs_model import inputs_from_docs as validation_inputs

RUN_DEADLINE_S = 180.0  # the whole run: 10 feeds at up to 20 s each, plus the write
WRITE_DEADLINE = (
    "the news refresh's deadline passed before its results could be saved (News was busy) — nothing was saved; "
    "run it again"
)
PLAN_DEADLINE = (
    "the news refresh could not read what it needs before its deadline (News was busy) — nothing was fetched or saved; "
    "run it again"
)
NewHex = Callable[[], str]


class RunRefused(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _current(conn: psycopg.Connection[Any], schema: str, now: datetime) -> refresh.RunInputs:
    """The CURRENT stored inputs, read again under the News write lock (after ``ensure_seeded``)."""
    v: ValidationInputs = validation_inputs(load_docs(conn, schema, now), berlin_today(now))
    return refresh.RunInputs(v.news_inputs, v)


def _write_documents(conn: psycopg.Connection[Any], schema: str, docs: dict[str, Any]) -> None:
    stored = news_store.documents(conn, schema)
    for key, body in docs.items():
        if json.dumps(stored.get(key), ensure_ascii=False) != json.dumps(body, ensure_ascii=False):
            news_store.save_document(conn, schema, key, body)


def _locked_session(db_url: str, schema: str) -> psycopg.Connection[Any]:
    session = connect(db_url, autocommit=True)  # a dedicated SESSION for the run lock
    got = session.execute(
        "select pg_try_advisory_lock(hashtext(%s))", (news_store.RUN_LOCK.format(schema=schema),)
    ).fetchone()
    if not (got and got[0]):
        session.close()
        raise RunRefused(409, refresh.ALREADY_RUNNING)
    return session


def _release(session: psycopg.Connection[Any], schema: str) -> None:
    try:
        session.execute("select pg_advisory_unlock(hashtext(%s))", (news_store.RUN_LOCK.format(schema=schema),))
    finally:
        session.close()


def refresh_run(
    db_url: str,
    schema: str,
    now: datetime,
    *,
    transport: net.Transport | None = None,
    resolver: net.Resolver | None = None,
    clock: Callable[[], float] = time.monotonic,
    new_hex: NewHex | None = None,
    deadline_s: float | None = None,
    trigger: str = "manual",
    after_fetch: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """One refresh run. Returns the old ``POST /api/news_refresh`` answer (``job.running`` false: the run finished);
    raises ``RunRefused`` (409 already running / before the import, 503 the write was cut off). ``after_fetch``: a test
    seam called between the fetch and the write phase."""
    today, wall = berlin_today(now), berlin_now(now)
    hexes = new_hex or (lambda: secrets.token_hex(2))
    session = _locked_session(db_url, schema)
    try:
        stop_fetching, done_by = budget(clock(), deadline_s or RUN_DEADLINE_S)
        # ── phase 1: read (closed before any request)
        # bounded too (Codex H-261): a lock held on what the plan reads cannot keep the run (and its lock) past the
        # deadline — a 503, nothing fetched, nothing written
        try:
            with bounded_transaction(db_url, stop_fetching, clock) as conn:
                ensure_intake_open(conn, schema)  # before the import: 409, and nothing is fetched
                first = base_from_docs(news_store.documents(conn, schema))
        except EventsError as exc:
            raise RunRefused(exc.status, PLAN_DEADLINE) from exc
        p = refresh.plan(first, today, wall, run_id=refresh.new_run_id(now, hexes), trigger=trigger, clock=clock)
        # ── phase 2: fetch (no transaction)
        results = refresh.fetch_all(
            p, FeedFetch(transport=transport, resolver=resolver, deadline=stop_fetching, clock=clock)
        )
        if after_fetch is not None:
            after_fetch()
        # ── phase 3: write (re-read under the lock, bounded by the same budget)
        with bounded_transaction(db_url, done_by, clock) as conn:
            news_store.lock(conn, schema)
            news_store.ensure_seeded(conn, schema, packaged_cases(), wall)
            out = refresh.apply(
                _current(conn, schema, now), results, today=today, now=wall, run_id=p.run_id, clock=clock
            )
            for change in (*out.new_events, *out.changed_events):  # each pass's own state (Codex H-261)
                states = list(change.states) or [(name, change.record) for name in change.passes or ("ingest",)]
                news_store.save_event_passes(conn, schema, change.event_id, change.record, states, {"run_id": p.run_id})
            if out.rest is not None:
                news_store.save_rest(conn, schema, out.rest)
            for log, line in out.appends:
                news_store.append_log(conn, schema, log, line)
            _write_documents(conn, schema, out.documents)
            note = {"run_id": p.run_id, "deferred": list(out.deferred)}
            news_store.append_log(conn, schema, "run_notes", json.dumps(note, ensure_ascii=False, sort_keys=True))
            return out.answer
    except EventsError as exc:  # the write phase's deadline: rolled back, nothing saved
        raise RunRefused(exc.status, WRITE_DEADLINE) from exc
    finally:
        _release(session, schema)


def evaluate_run(
    db_url: str,
    schema: str,
    now: datetime,
    *,
    clock: Callable[[], float] = time.monotonic,
    deadline_s: float | None = None,
) -> dict[str, Any]:
    """The standalone source evaluation ("Re-measure now"): no network; serialized with every refresh run (the run
    lock) and with every News write (the News write lock). Answers ``{ok: true, evaluated_at}``."""
    today, wall = berlin_today(now), berlin_now(now)
    session = _locked_session(db_url, schema)
    try:
        _stop, done_by = budget(clock(), deadline_s or RUN_DEADLINE_S)
        with bounded_transaction(db_url, done_by, clock) as conn:
            news_store.lock(conn, schema)  # also the production boundary: 409 before the import
            news_store.ensure_seeded(conn, schema, packaged_cases(), wall)
            ev = refresh.remeasure(_current(conn, schema, now), today=today, now=wall)
            for log, line in ev.appends:
                news_store.append_log(conn, schema, log, line)
            _write_documents(conn, schema, {"news/source_state.json": ev.source_state,
                                            "news/source_metrics.json": ev.source_metrics})  # fmt: skip
            if ev.deferred_nominations:
                note = {"evaluated_at": ev.result.get("at"), "deferred": ["the source network arrives with its port"]}
                news_store.append_log(conn, schema, "run_notes", json.dumps(note, ensure_ascii=False, sort_keys=True))
            return {"ok": True, "evaluated_at": ev.result.get("at")}
    except EventsError as exc:
        raise RunRefused(exc.status, WRITE_DEADLINE) from exc
    finally:
        _release(session, schema)
