"""The jobs the runner can run (review 032c), each the old ``_run_*`` over its NEW entry point, with the old result
line, plus its OCCURRENCE reader: the job's own ``last()`` value, re-read on the job's locked connection by the
runner's ``still_due`` check (plan revision 3).

| job | entry point | occurrence |
|---|---|---|
| event_scan | ``events.scan.scan`` (its scan lock) | ``event_health.json``'s ``scan_time`` and ``updated_at`` |
| validation_snapshot | ``writers.record_snapshot`` | the newest ``snapshots`` line (``validation_log.seq``) |
| news_refresh | ``news.runs.refresh_run(trigger="scheduled")`` | the newest ``runs`` News log line |
| news_weekly_review | ``writers.record_weekly`` + ``news.runs.evaluation`` | the newest ``weekly`` News log line |
| news_source_review | ``news.runs.evaluation(record_history=True)`` | the newest monthly-review mark (``run_notes``) |

The other six active jobs are not ported (decision b): ``REAL`` holds no entry for them, so they never run.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql

from projectzero.core import occurrence
from projectzero.core.db import schema_ident
from projectzero.events import scan
from projectzero.health.catalog import JOBS as JOB_ROWS
from projectzero.jobs import writers
from projectzero.jobs.ported import PORTED
from projectzero.network.view import berlin_today
from projectzero.news import refresh, runs

Guard = Callable[[psycopg.Connection[Any], str], None]


@dataclass(frozen=True)
class JobDeps:
    """What a job reaches the outside world through. ``None``: the production default (the network). Tests and the
    route pass the fixture fetchers / transports (the same seams the Events and News routes take)."""

    events_fetcher: Any = None
    events_transport: Any = None
    events_resolver: Any = None
    events_deadline_s: float = scan.SCAN_DEADLINE_S
    news_transport: Any = None
    news_resolver: Any = None
    new_hex: Callable[[], str] | None = None
    card_gateway: Mapping[str, Any] | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)  # test seams for fake jobs


@dataclass(frozen=True)
class JobContext:
    db_url: str
    schema: str
    now: datetime  # the run's instant (aware, or naive Berlin wall time)
    still_due: occurrence.StillDue
    deps: JobDeps
    guard: Guard
    source: str = "app"


@dataclass(frozen=True)
class Job:
    id: str
    label: str
    interval_h: float
    run: Callable[[JobContext], str]
    occurrence: Callable[[psycopg.Connection[Any], str], Any]
    last: Any = None  # the plan's ``last`` reader (a ``health.core.LAST`` key, or None)

    def row(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "interval_h": self.interval_h, "last": self.last}


def _one(conn: psycopg.Connection[Any], schema: str, query: str, params: Any = ()) -> Any:
    row = conn.execute(sql.SQL(query).format(s=schema_ident(schema)), params).fetchone()
    return tuple(row) if row is not None else None


def event_scan_occurrence(conn: psycopg.Connection[Any], schema: str) -> Any:
    return _one(
        conn, schema, "select body->>'scan_time', updated_at from {s}.documents where key = 'event_health.json'"
    )


def news_log_occurrence(log: str) -> Callable[[psycopg.Connection[Any], str], Any]:
    def read(conn: psycopg.Connection[Any], schema: str) -> Any:
        return _one(conn, schema, "select max(seq) from {s}.news_logs where log = %s", (log,))

    return read


def source_review_occurrence(conn: psycopg.Connection[Any], schema: str) -> Any:
    """The newest recorded MONTHLY review (its ``run_notes`` mark): the weekly evaluation may also append a
    ``source_history`` line (the old "none yet / older than 28 days" rule), which is not this job's occurrence."""
    mark = f'%"{runs.SOURCE_REVIEW_MARK}": true%'  # the line is json.dumps(..., sort_keys=True); never cast
    return _one(conn, schema, "select max(seq) from {s}.news_logs where log = 'run_notes' and line like %s", (mark,))


def snapshot_occurrence(conn: psycopg.Connection[Any], schema: str) -> Any:
    return _one(conn, schema, "select max(seq) from {s}.validation_log where log = 'snapshots'")


# ------------------------------------------------------------------------------------------------ the old _run_*
def _run_events(ctx: JobContext) -> str:
    d = ctx.deps
    health = scan.scan(ctx.db_url, ctx.schema, ctx.now, d.events_fetcher, deadline_s=d.events_deadline_s,
                       transport=d.events_transport, resolver=d.events_resolver, still_due=ctx.still_due)  # fmt: skip
    t = health.get("totals", {})
    return f"{t.get('accepted', 0)} event(s) accepted · {t.get('failed', 0)} source failure(s)"


def _run_snapshot(ctx: JobContext) -> str:
    if writers.record_snapshot(ctx.db_url, ctx.schema, ctx.now, still_due=ctx.still_due, guard=ctx.guard):
        return "snapshot recorded"
    return f"snapshot already recorded for {berlin_today(ctx.now).isoformat()}"


def _run_news(ctx: JobContext) -> str:
    d = ctx.deps
    try:
        out = runs.refresh_run(ctx.db_url, ctx.schema, ctx.now, transport=d.news_transport, resolver=d.news_resolver,
                               new_hex=d.new_hex, trigger="scheduled", card_gateway=d.card_gateway,
                               still_due=ctx.still_due)  # fmt: skip
    except runs.RunRefused as exc:
        if exc.status == 409 and str(exc) == refresh.ALREADY_RUNNING:
            return "skipped — a news refresh was already running"
        raise
    r = out.get("last") or {}
    return (
        f"{str(r.get('status', 'ok')).upper()} · {r.get('new', 0)} new event(s) · {r.get('merged', 0)} updated · "
        f"{r.get('duplicates_skipped', 0)} already known · {r['sources_ok']} feed(s) ok · "
        f"{len(r['sources_failed'])} failed · ${r.get('usd', 0):.4f}"
    )


def _run_news_weekly(ctx: JobContext) -> str:
    wrote = writers.record_weekly(ctx.db_url, ctx.schema, ctx.now, still_due=ctx.still_due, guard=ctx.guard)
    r = runs.evaluation(ctx.db_url, ctx.schema, ctx.now)  # weekly: refresh rolling news-source metrics
    head = "weekly learning review recorded" if wrote else "weekly learning review already recorded this week"
    return f"{head} · news sources: {r['benchmark_events']} material events measured"


def _run_news_sources_monthly(ctx: JobContext) -> str:
    r = runs.evaluation(ctx.db_url, ctx.schema, ctx.now, record_history=True, still_due=ctx.still_due)
    return (
        f"{r['benchmark_events']} material events · {len(r['lifecycle_changes'])} lifecycle change(s) · "
        f"{len(r['nominated'])} publication candidate(s) handed to the source network"
    )


_ENTRY: dict[str, tuple[Callable[[JobContext], str], Callable[[psycopg.Connection[Any], str], Any]]] = {
    "event_scan": (_run_events, event_scan_occurrence),
    "validation_snapshot": (_run_snapshot, snapshot_occurrence),
    "news_refresh": (_run_news, news_log_occurrence("runs")),
    "news_weekly_review": (_run_news_weekly, news_log_occurrence("weekly")),
    "news_source_review": (_run_news_sources_monthly, source_review_occurrence),
}
assert set(_ENTRY) == PORTED

# the runnable jobs, keyed by id, with the old rows' labels, intervals and plan readers
REAL: dict[str, Job] = {
    r["id"]: Job(r["id"], r["label"], float(r["interval_h"]), _ENTRY[r["id"]][0], _ENTRY[r["id"]][1], r["last"])
    for r in JOB_ROWS
    if r["id"] in _ENTRY
}
