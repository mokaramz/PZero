"""The jobs the runner can run (review 032c), each the old ``_run_*`` over its NEW entry point, with the old result
line, plus its OCCURRENCE reader: the job's own ``last()`` value, re-read on the job's locked connection by the
runner's ``still_due`` check (plan revision 3).

| job | entry point | occurrence |
|---|---|---|
| deal_flow_scan | ``dealflow.scan.run.scan`` (its scan lock, review 034a) | the newest ``scan_runs`` row |
| event_scan | ``events.scan.scan`` (its scan lock) | ``event_health.json``'s ``scan_time`` and ``updated_at`` |
| validation_snapshot | ``writers.record_snapshot`` | the newest ``snapshots`` line (``validation_log.seq``) |
| news_refresh | ``news.runs.refresh_run(trigger="scheduled")`` | the newest ``runs`` News log line |
| news_weekly_review | ``writers.record_weekly`` + ``news.runs.evaluation`` | the newest ``weekly`` News log line |
| news_source_review | ``news.runs.evaluation(record_history=True)`` | the newest monthly-review mark (``run_notes``) |
| triage_retry | ``dealflow.triage.auto.run_retry`` (the triage run lock, review 035b) | the newest retry run |
| watch_checks | ``watch.run.run_checks(scheduled=True)`` (its check lock, 037b) | ``watch_check_state.job_runs`` |

The scan job runs machine triage of what it found right after the scan committed, synchronously, inside the job's
900 seconds (review 035b, decision e); a triage failure never fails the scan, and the note gains the old "machine
triage PARTIAL: ..." when the run was not done. The WATCH checks (review 037b) run with the 600-second budget; their
note is the old one plus " · N page(s) left for the next run" when the budget left pages. The other three active jobs
are not ported (decision b): ``REAL`` holds no entry for them, so they never run.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql

from projectzero.core import occurrence
from projectzero.core.db import schema_ident, transaction
from projectzero.dealflow.scan import run as dealflow_scan
from projectzero.dealflow.triage import auto as triage_auto
from projectzero.events import scan
from projectzero.health.catalog import JOBS as JOB_ROWS
from projectzero.jobs import store, writers
from projectzero.jobs.ported import PORTED
from projectzero.network.view import berlin_today
from projectzero.news import refresh, runs
from projectzero.watch import run as watch_run

Guard = Callable[[psycopg.Connection[Any], str], None]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JobDeps:
    """What a job reaches the outside world through. ``None``: the production default (the network). Tests and the
    route pass the fixture fetchers / transports (the same seams the Events and News routes take)."""

    events_fetcher: Any = None
    events_transport: Any = None
    events_resolver: Any = None
    events_deadline_s: float = scan.SCAN_DEADLINE_S
    dealflow_transport: Any = None
    dealflow_resolver: Any = None
    dealflow_options: Mapping[str, Any] = field(default_factory=dict)  # budgets / worker count (tests)
    news_transport: Any = None
    news_resolver: Any = None
    new_hex: Callable[[], str] | None = None
    card_gateway: Mapping[str, Any] | None = None
    watch_transport: Any = None  # review 037b: the WATCH page checks' fixtures
    watch_resolver: Any = None
    watch_budget_s: float = watch_run.JOB_BUDGET_S
    triage: Any = None  # review 035b: the machine-triage ``auto.Deps`` (gateway injectables, hooks); None: production
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


def deal_flow_scan_occurrence(conn: psycopg.Connection[Any], schema: str) -> Any:
    return _one(conn, schema, "select max(id) from {s}.scan_runs")


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
SCAN_JOB_BUDGET_S = 900.0  # the old scheduler's wait for the scan and its machine triage together


def scan_note(res: Mapping[str, Any], tri: Mapping[str, Any] | None) -> str:
    """The old ``_run_scan`` note: never hide a triage run that stopped behind a "successful" scan."""
    note = f"{res.get('new', 0)} genuinely new · {res.get('baseline', 0)} baseline"
    if tri and tri.get("state") not in (None, "done"):
        why = str(tri.get("stopped") or tri.get("summary") or "")[:160]
        state = str(tri.get("state")).upper()
        note += f" · machine triage {state}: {tri.get('triaged', 0)} of {tri.get('selected', 0)} — {why}"
    return note


def _triage_deps(ctx: JobContext, deadline: float | None, still_due: occurrence.StillDue | None = None) -> Any:
    base = ctx.deps.triage if ctx.deps.triage is not None else triage_auto.Deps()
    return replace(base, clock=base.clock or (lambda: ctx.now), deadline=deadline, still_due=still_due)


def _run_scan(ctx: JobContext) -> str:
    """The old ``_run_scan``: the scan (the config's ``catch_up_scan_days``, else 7), then machine triage of what it
    found (review 035b, decision e: after the scan committed, synchronously, inside the job's 900 s; a triage
    failure never fails the scan), and the old note."""
    d = ctx.deps
    t0 = time.monotonic()
    with transaction(ctx.db_url) as conn:
        cfg = store.config(conn, ctx.schema)
    days = int((cfg if isinstance(cfg, dict) else {}).get("catch_up_scan_days") or dealflow_scan.DEFAULT_DAYS)
    try:
        res = dealflow_scan.scan(ctx.db_url, ctx.schema, days=days, clock=lambda: ctx.now,
                                 transport=d.dealflow_transport, resolver=d.dealflow_resolver,
                                 still_due=ctx.still_due, trigger=ctx.source,
                                 **dict(d.dealflow_options))  # fmt: skip
    except dealflow_scan.ScanBusy:
        return dealflow_scan.ALREADY_RUNNING_JOB
    tri: Mapping[str, Any] | None = None
    try:
        deps = _triage_deps(ctx, t0 + SCAN_JOB_BUDGET_S)
        out = triage_auto.after_scan(ctx.db_url, ctx.schema, str(res.get("run_id") or ""), deps)
        tri = out if "state" in out else None
    except Exception:  # the scan job never fails because of triage (the old try/except)
        logger.exception("machine triage after the scan job failed (scan unaffected)")
    return scan_note(res, tri)


def triage_retry_occurrence(conn: psycopg.Connection[Any], schema: str) -> Any:
    return _one(conn, schema, "select max(id) from {s}.triage_auto_runs where kind = 'retry'")


def _run_triage_retry(ctx: JobContext) -> str:
    """The old ``_run_triage_retry``: ``run_retry()``'s summary or reason (decision d: no run while paid is off)."""
    out = triage_auto.run_retry(ctx.db_url, ctx.schema, deps=_triage_deps(ctx, None, ctx.still_due))
    return triage_auto.retry_note(out)


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


def watch_checks_occurrence(conn: psycopg.Connection[Any], schema: str) -> Any:
    return watch_run.job_runs(conn, schema)


def _run_watch(ctx: JobContext) -> str:
    """The old ``_run_watch``: every watched company's checks, and the old note (review 037b; the busy note while
    another check runs)."""
    d = ctx.deps
    try:
        out = watch_run.run_checks(ctx.db_url, ctx.schema, clock=lambda: ctx.now, transport=d.watch_transport,
                                   resolver=d.watch_resolver, budget=d.watch_budget_s, scheduled=True,
                                   still_due=ctx.still_due)  # fmt: skip
    except watch_run.CheckBusy:
        return watch_run.JOB_BUSY_NOTE
    return watch_run.note(out)


_ENTRY: dict[str, tuple[Callable[[JobContext], str], Callable[[psycopg.Connection[Any], str], Any]]] = {
    "deal_flow_scan": (_run_scan, deal_flow_scan_occurrence),
    "event_scan": (_run_events, event_scan_occurrence),
    "validation_snapshot": (_run_snapshot, snapshot_occurrence),
    "news_refresh": (_run_news, news_log_occurrence("runs")),
    "news_weekly_review": (_run_news_weekly, news_log_occurrence("weekly")),
    "news_source_review": (_run_news_sources_monthly, source_review_occurrence),
    "triage_retry": (_run_triage_retry, triage_retry_occurrence),
    "watch_checks": (_run_watch, watch_checks_occurrence),
}
assert set(_ENTRY) == PORTED

# the runnable jobs, keyed by id, with the old rows' labels, intervals and plan readers
REAL: dict[str, Job] = {
    r["id"]: Job(r["id"], r["label"], float(r["interval_h"]), _ENTRY[r["id"]][0], _ENTRY[r["id"]][1], r["last"])
    for r in JOB_ROWS
    if r["id"] in _ENTRY
}
