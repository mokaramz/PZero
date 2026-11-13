"""The two writers the old scheduler's jobs had and the rewrite lacked (review 032c, plan revision 3). Each runs in ONE
transaction under its own transaction-scoped advisory lock, held to commit, so its absence check and its append can
never interleave with another writer's: two transactions for the same key are serialized and the second finds the
first's line.

* ``record_weekly``: the old ``news.weekly_review(record=True)``: the review (``news.core.weekly_review``, pure) with
  its ``at`` appended to the ``weekly`` News log as ``json.dumps(..., ensure_ascii=False, sort_keys=True)``, at most
  ONE per ISO week (of the review's ``week_ending``), under ``pg_advisory_xact_lock(hashtext('<schema>.news.weekly'))``.
* ``record_snapshot``: the old ``validation._snapshot`` (the append ``validation.view()`` made): today's headline
  snapshot line (``validation.core.snapshot_line``) appended to the ``snapshots`` log, at most ONE per Berlin date,
  under ``pg_advisory_xact_lock(hashtext('<schema>.validation.snapshot'))``.

Both check the import marker first (``guard``), then take the lock, then run the runner's ``still_due`` check on the
locked transaction (``None``: no check), and only then read and write. ``before_lock``: a test seam called with the
transaction open, just before the lock is requested.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import psycopg

from projectzero.core import occurrence
from projectzero.core.db import transaction
from projectzero.dealflow.intake.postgres import ensure_intake_open
from projectzero.dealflow.triage.view import decisions as read_jsonl
from projectzero.network.view import berlin_now, berlin_today
from projectzero.news import core as news_core
from projectzero.news import inputs as news_inputs
from projectzero.news import store as news_store
from projectzero.validation import core as validation_core
from projectzero.validation import inputs as validation_inputs
from projectzero.validation import store as validation_store

WEEKLY_LOCK = "{schema}.news.weekly"
SNAPSHOT_LOCK = "{schema}.validation.snapshot"
Guard = Callable[[psycopg.Connection[Any], str], None]


def _xact_lock(conn: psycopg.Connection[Any], key: str) -> None:
    conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (key,))


def _iso_week(value: Any) -> tuple[int, int] | None:
    try:
        y, w, _d = date.fromisoformat(str(value)[:10]).isocalendar()
    except ValueError:
        return None
    return y, w


def record_weekly(
    db_url: str,
    schema: str,
    now: datetime,
    *,
    still_due: occurrence.StillDue | None = None,
    guard: Guard = ensure_intake_open,
    before_lock: Callable[[], None] | None = None,
) -> bool:
    """Record this ISO week's learning review; ``False`` when the week already has one (nothing written)."""
    today, wall = berlin_today(now), berlin_now(now)
    with transaction(db_url) as conn:
        guard(conn, schema)
        if before_lock is not None:
            before_lock()
        _xact_lock(conn, WEEKLY_LOCK.format(schema=schema))
        occurrence.check(still_due, conn)
        week = _iso_week(today.isoformat())
        logs = news_store.log_texts(conn, schema, ("weekly",))
        if any(_iso_week(r.get("week_ending")) == week for r in news_core._rows(logs[news_store.LOGS["weekly"]])):
            return False
        rev = news_core.weekly_review(news_inputs.load(conn, schema, now), today, wall)
        line = json.dumps({**rev, "at": validation_core.ts(now)}, ensure_ascii=False, sort_keys=True)
        news_store.append_log(conn, schema, "weekly", line)
        return True


def record_snapshot(
    db_url: str,
    schema: str,
    now: datetime,
    *,
    still_due: occurrence.StillDue | None = None,
    guard: Guard = ensure_intake_open,
    before_lock: Callable[[], None] | None = None,
) -> bool:
    """Record today's (Berlin) Validation snapshot; ``False`` when today already has one (nothing written)."""
    today = berlin_today(now)
    with transaction(db_url) as conn:
        guard(conn, schema)
        if before_lock is not None:
            before_lock()
        _xact_lock(conn, SNAPSHOT_LOCK.format(schema=schema))
        occurrence.check(still_due, conn)
        rows = read_jsonl(validation_store.texts(conn, schema)[validation_store.PATHS["snapshots"]])
        if any(r.get("date") == today.isoformat() for r in rows):
            return False
        inputs = validation_inputs.load(conn, schema, now)
        ents, _issues = validation_core.build(inputs, today)
        head = validation_core._headline(ents, today, inputs.audits_log)
        cal = validation_core.calibration(ents, inputs.decisions_log)
        validation_store.append(conn, schema, [("snapshots", validation_core.snapshot_line(head, cal, today, now))])
        return True
