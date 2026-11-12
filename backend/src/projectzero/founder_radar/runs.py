"""The Founder Radar runs that use the network (review 026b): the founder scan, company research and the research
queue, in the three phases of the Events scan (``events/scan.py``), so no transaction is open while the network is used:

1. **read** (one short read-only transaction, closed before any request): the write boundary is checked first (before
   the import every run is a 409 and nothing is fetched), then the inputs, the sources, the cursor and the queue; the
   pure ``*_plan`` decides what to fetch.
2. **fetch** (no transaction): every request through ``fetching.Fetch`` (``core.net``: the guard, the per-caller
   policies, the pinned transport), bounded by its timeout and the run's wall-clock budget (``events.scan.budget``:
   a write-time reserve is kept back).
3. **write** (ONE transaction bounded by the same budget, ``events.scan.bounded_transaction``: the connect, the waits
   for the write lock and the people lock, every statement and the commit): the CURRENT inputs are re-read and the
   pure ``*_apply`` merges the results onto them; ``db.apply_outcome`` writes them. A write the deadline cuts off is a
   503 and saves nothing.

One run at a time: a SESSION advisory lock (``<schema>.founder_radar.fetch``) taken with ``pg_try_advisory_lock`` on a
dedicated connection and released on every exit path. Scan, research and the queue share it, so a second run is a
409 (and the old queue's lost update cannot happen).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from projectzero.core import net
from projectzero.core.db import connect, read_only_transaction
from projectzero.dealflow.intake.postgres import ensure_intake_open
from projectzero.events.edits import EventsError
from projectzero.events.scan import bounded_transaction, budget
from projectzero.founder_radar import db, fetching, research, scanning
from projectzero.network.view import berlin_today

ALREADY_RUNNING = "a founder scan or company research is already running — wait for it to finish"
WRITE_DEADLINE = (
    "the run's deadline passed before its results could be saved (Founder Radar was busy) — nothing was saved; "
    "run it again"
)
KINDS = ("scan", "research", "research_queue")


class RunRefused(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _detail(kind: str, body: dict[str, Any]) -> dict[str, Any]:
    keep = {k: body[k] for k in ("key", "refresh", "batch") if isinstance(body.get(k), str | int | bool)}
    if isinstance(body.get("keys"), list):
        keep["keys"] = [k for k in body["keys"] if isinstance(k, str)]
    return {"request": keep, "run": kind}


def run(
    db_url: str,
    schema: str,
    kind: str,
    body: dict[str, Any],
    now: datetime,
    *,
    transport: net.Transport | None = None,
    resolver: net.Resolver | None = None,
    clock: Callable[[], float] = time.monotonic,
    token: str | None = None,
    deadline_s: float | None = None,
) -> dict[str, Any]:
    """One run (``kind``: ``scan`` | ``research`` | ``research_queue``). Returns the old answer; raises ``RunRefused``
    (409 already running / before the import, 503 the write was cut off). ``token`` defaults to ``PZ_GITHUB_TOKEN``."""
    assert kind in KINDS, kind
    today = berlin_today(now)
    if token is None:
        token = os.environ.get(fetching.GITHUB_TOKEN_ENV) or None
    key = f"{schema}.founder_radar.fetch"
    session = connect(db_url, autocommit=True)  # a dedicated SESSION for the run lock
    try:
        got = session.execute("select pg_try_advisory_lock(hashtext(%s))", (key,)).fetchone()
        if not (got and got[0]):
            raise RunRefused(409, ALREADY_RUNNING)
        try:
            limit = deadline_s or (scanning.SCAN_DEADLINE_S if kind == "scan" else research.RESEARCH_DEADLINE_S)
            stop_fetching, done_by = budget(clock(), limit)
            # ── phase 1: read (closed before any request)
            with read_only_transaction(db_url) as conn:
                ensure_intake_open(conn, schema)  # before the import: 409, and nothing is fetched
                docs = db.documents(conn, schema)
                first = db.inputs(conn, schema, docs)
            fetch = fetching.Fetch(transport=transport, resolver=resolver, deadline=stop_fetching, clock=clock)
            # ── phase 2: fetch (no transaction)
            if kind == "scan":
                plan = scanning.scan_plan(first, sources_doc=docs["sources"], cursor_doc=docs["cursor"])
                scanned = scanning.scan_fetch(plan, fetch, now=now, today=today, token=token, clock=clock)
            elif kind == "research":
                rplan = research.research_plan(first, body, today=today, now=now)
                fetched = research.research_fetch(rplan, fetch, now=now, today=today)
            else:
                rplan = research.queue_plan(first, docs["queue"], body, today=today, now=now)
                fetched = research.research_fetch(rplan, fetch, now=now, today=today)
            # ── phase 3: write (re-read under both locks, bounded by the same budget)
            with bounded_transaction(db_url, done_by, clock) as conn:
                db.lock(conn, schema)
                docs_now = db.documents(conn, schema)
                current = db.inputs(conn, schema, docs_now)
                detail = _detail(kind, body)
                if kind == "scan":
                    so = scanning.scan_apply(current, scanned, cursor_doc=docs_now["cursor"], now=now, today=today,
                                             clock=clock)  # fmt: skip
                    db.apply_outcome(conn, schema, current, so.outcome, "scan", detail,
                                     run_documents={db.RUN_DOCUMENTS["cursor"]: so.cursor,
                                                    db.INPUT_DOCUMENTS["health"]: so.health})  # fmt: skip
                    return so.outcome.body
                ro = research.research_apply(current, fetched, queue_doc=docs_now["queue"], now=now, today=today)
                db.apply_outcome(conn, schema, current, ro.outcome, kind, detail,
                                 run_documents={db.RUN_DOCUMENTS["queue"]: ro.queue})  # fmt: skip
                return ro.outcome.body
        except EventsError as exc:  # the write phase's deadline: rolled back, nothing saved
            raise RunRefused(exc.status, WRITE_DEADLINE) from exc
        finally:
            session.execute("select pg_advisory_unlock(hashtext(%s))", (key,))
    finally:
        session.close()
