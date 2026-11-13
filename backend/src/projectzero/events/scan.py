"""The event source scan (review 017): the old ``domain/event_sources.py`` ``scan()`` (rev 6c739b9) in three phases,
so no transaction is open while the network is used (Codex H-113):

1. **read** (one short transaction, then closed): the registry (``registry.prepare``: repairs and newly offered
   default sources are computed BEFORE fetching, so a new source takes part in this scan), the previous health rows
   (``last_ok``) and each watcher's baseline (its ``event_watch_snapshots`` row, else ONCE its archived
   ``.watch/ev-<uid(url)>.json``);
2. **fetch** (no transaction): every source through the ``Fetcher``, each request bounded by its timeout AND by the
   scan's wall-clock budget (``budget``: DNS, connects and every read, through ``core.net``); a source the deadline
   cuts off is "failed" with that reason, and the sources after it are not fetched;
3. **write** (ONE transaction under the events lock): the CURRENT events and leads are re-read (a decision committed
   during the fetch is kept), then ``promotion.promote_structured`` and ``add_leads`` are applied and written through
   the 016 write model (``attrs.record``, mirrored columns, ``event_history``), the watcher baselines that were
   fetched successfully are stored, the registry is written if ``prepare`` changed it, and the new
   ``event_health.json``. A failure here rolls back the whole write phase.

One scan at a time: a SESSION advisory lock (``<schema>.events.scan``) taken with ``pg_try_advisory_lock`` on a
dedicated autocommit connection, released on every exit path; a second scan is refused at once (409).
"""

from __future__ import annotations

import contextlib
import math
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from projectzero.core import net, occurrence
from projectzero.core.db import connect, schema_ident
from projectzero.dealflow.intake.postgres import ensure_intake_open
from projectzero.events import engine, registry
from projectzero.events.collectors import Collected, Fetcher, collect, stamp, uid
from projectzero.events.columns import LEAD_DECISIONS, lead_columns
from projectzero.events.edits import EventsError
from projectzero.events.promotion import add_leads, promote_structured
from projectzero.events.store import load as load_events
from projectzero.events.writes import EventsWriter

SCAN_DEADLINE_S = 240.0  # the whole scan, wall clock (the old one took about 60 s for 33 sources)
REQUEST_TIMEOUT_S = 20.0  # one request (the old PZ_TIMEOUT default)
WRITE_RESERVE_S = 30.0  # kept back from fetching for the write phase (at most a quarter of the deadline)
ALREADY_RUNNING = "an event source scan is already running — wait for it to finish"
DEADLINE_NOTE = "scan deadline reached — this source was not fetched"
WRITE_DEADLINE = (
    "the scan's deadline passed before its results could be written (the events were busy) — nothing was saved; "
    "scan again"
)


def budget(t0: float, deadline_s: float) -> tuple[float, float]:
    """(when fetching must stop, when the whole scan must be done): one shared wall-clock budget (Codex H-115)."""
    return t0 + deadline_s - min(WRITE_RESERVE_S, deadline_s / 4), t0 + deadline_s


class NetFetcher:
    """The production fetcher: ``core.net`` (pinned, verified TLS) with the old browser headers, every request
    bounded by the scan deadline."""

    def __init__(
        self, deadline: float, transport: net.Transport | None = None, resolver: net.Resolver | None = None
    ) -> None:
        self.deadline = deadline
        self.transport = transport
        self.resolver = resolver

    def get_text(self, url: str) -> str:
        return net.fetch(
            url,
            headers=net.BROWSER_HEADERS,
            timeout=REQUEST_TIMEOUT_S,
            deadline=self.deadline,
            transport=self.transport,
            resolver=self.resolver,
        ).text()


@dataclass
class Fetched:
    src: dict[str, Any]
    row: dict[str, Any]
    result: Collected | None = None
    items: list[dict[str, Any]] = field(default_factory=list)


def _row(src: dict[str, Any], prev: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": src["id"],
        "name": src["name"],
        "kind": src.get("kind"),
        "url": src.get("url", ""),
        "city": src.get("city", ""),
        "status": "",
        "route": "",
        "note": "",
        "raw": 0,
        "future": 0,
        "accepted": 0,
        "review": 0,
        "past": 0,
        "dups": 0,
        "last_ok": (prev.get(src["id"]) or {}).get("last_ok", ""),
        "seconds": 0,
    }


def _q(schema: str, query: str) -> sql.Composed:
    return sql.SQL(query).format(s=schema_ident(schema))


def _read(
    conn: psycopg.Connection[Any], schema: str, now: datetime
) -> tuple[registry.Registry, dict[Any, Any], dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            _q(schema, "select key, body from {s}.documents where key = any(%s)"),
            (["event_sources.json", "event_health.json"],),
        )
        docs = {r["key"]: r["body"] for r in cur.fetchall()}
        reg = registry.prepare(docs.get("event_sources.json"), now)
        health = docs.get("event_health.json")
        prev = {s.get("id"): s for s in ((health or {}).get("sources") or []) if isinstance(s, dict)}
        watchers = [s for s in reg.sources if s.get("kind") == "watcher"]
        baselines: dict[str, Any] = {}
        if watchers:
            cur.execute(
                _q(schema, "select source_id, lines from {s}.event_watch_snapshots where source_id = any(%s)"),
                ([s["id"] for s in watchers],),
            )
            baselines = {r["source_id"]: {"lines": r["lines"], "seeded_from": None} for r in cur.fetchall()}
            missing = {
                f".watch/ev-{uid(str(s.get('url', '')))}.json": s["id"] for s in watchers if s["id"] not in baselines
            }
            if missing:
                cur.execute(
                    _q(schema, "select path, parsed from {s}.legacy_documents where path = any(%s)"), (list(missing),)
                )
                for r in cur.fetchall():
                    if isinstance(r["parsed"], list):
                        baselines[missing[r["path"]]] = {"lines": r["parsed"], "seeded_from": r["path"]}
    return reg, prev, baselines


def _fetch_all(
    sources: list[dict[str, Any]],
    prev: dict[str, Any],
    baselines: dict[str, Any],
    fetcher: Fetcher,
    now: datetime,
    deadline: float,
    clock: Callable[[], float],
) -> list[Fetched]:
    out = []
    for src in sources:
        f = Fetched(src, _row(src, prev))
        st = clock()
        if st >= deadline:
            f.row["status"], f.row["note"] = "failed", DEADLINE_NOTE
            out.append(f)
            continue
        try:
            base = baselines.get(src["id"])
            r = collect(src, fetcher, now, base["lines"] if base else None)
            f.result, f.items = r, r.items
            f.row["status"], f.row["note"], f.row["route"], f.row["raw"] = r.status, r.note, r.route, len(r.items)
            if r.status == "ok":
                f.row["last_ok"] = stamp(now)
        except Exception as exc:  # the old scan: one failing source never stops the others
            f.row["status"], f.row["note"] = "failed", f"{type(exc).__name__}: {str(exc)[:120]}"
        f.row["seconds"] = round(clock() - st, 1)
        out.append(f)
    return out


def _insert_lead(w: EventsWriter, rec: dict[str, Any]) -> None:
    c = lead_columns(rec, today=w.today).columns
    attrs = {**c["attrs"], "record": rec}
    w._rows(
        "insert into {s}.event_leads (id, title, source, url, city, type, lead_date, date_raw, confidence, detected_on,"
        " decision, note, attrs, created_at) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, clock_timestamp())",
        (
            rec["id"],
            c["title"],
            c["source"],
            c["url"],
            c["city"],
            c["type"],
            c["lead_date"],
            c["date_raw"],
            c["confidence"],
            c["detected_on"],
            c["decision"] if c["decision"] in LEAD_DECISIONS else "new",
            c["note"],
            Jsonb(attrs),
        ),
    )
    w._history(
        lead_id=rec["id"], action="scan_lead", before=None, after=rec, detail={"source_id": rec.get("source_id")}
    )


def registry_cities(reg: registry.Registry) -> dict[Any, str]:
    """source id -> city of the registry this scan uses (the old listing read the file ``load_sources`` had just
    repaired)."""
    return {s.get("id"): s.get("city", "") for s in reg.document.get("sources") or [] if isinstance(s, dict)}


@dataclass
class Plan:
    """Everything a scan writes, computed in memory from the CURRENT records (pure: the goldens run this exact code)."""

    created: list[dict[str, Any]]
    merged: dict[str, dict[str, Any]]
    leads: list[dict[str, Any]]  # new leads, newest first (the old order)
    snapshots: list[tuple[dict[str, Any], list[str]]]  # (watcher source, its new baseline)
    health: dict[str, Any]


def compute(
    fetched: list[Fetched],
    events: list[dict[str, Any]],
    leads: list[dict[str, Any]],
    source_city: dict[Any, str],
    pins: dict[str, Any],
    now: datetime,
    today: Any,
    seconds: float,
) -> Plan:
    """The old ``scan()`` after its fetch loop: promotion, leads, per-source counts, totals and the health document.
    ``events`` / ``leads`` are the CURRENT records in their stored order."""

    def is_review(it: dict[str, Any]) -> bool:
        return it.get("provenance") == "watcher" or it.get("confidence") == "low"

    structured = [(it, f.row) for f in fetched for it in f.items if not is_review(it)]
    review = [(it, f.row) for f in fetched for it in f.items if is_review(it)]
    res = promote_structured([it for it, _ in structured], events, today)
    for (_it, row), tag in zip(structured, res.tags, strict=True):
        if tag in ("accepted", "past", "dups"):
            row[tag] += 1
        if tag in ("accepted", "dups"):
            row["future"] += 1
        row["ingested"] = row["accepted"]
    after = [res.merged.get(str(e.get("id")), e) for e in events] + res.created  # the old events.json after promotion
    intake = add_leads([it for it, _ in review], leads, after, today) if review else None
    for _it, row in review:
        row["review"] += 1
    rws = [f.row for f in fetched]
    totals: dict[str, Any] = {
        "attempted": len(rws),
        "ok": sum(1 for r in rws if r["status"] == "ok"),
        "failed": sum(1 for r in rws if r["status"] == "failed"),
        "config_required": sum(1 for r in rws if r["status"] == "config_required"),
        "productive": sum(1 for r in rws if r["status"] == "ok" and r["future"] > 0),
        "watch_only": sum(1 for r in rws if r["status"] == "ok" and r["future"] == 0),
        "raw": sum(r["raw"] for r in rws),
        "parsed": len(structured),
        "future": sum(r["future"] for r in rws),
        "ingested": res.accepted,
        "watcher_review": intake.added if intake else 0,
        "policy_rejected": res.rejected,
        "past": res.past + (intake.dropped_past if intake else 0),
        "dups": res.dups + (intake.dropped_dupe if intake else 0),
        "seconds": seconds,
    }
    totals["accepted"] = totals["ingested"]
    totals["review"] = totals["watcher_review"]  # backward-compatible keys
    fut = [x for x in engine.listing(after, today, source_city, pins) if not x.get("past")]
    totals.update({
        "structured_future": len(fut),
        "high_signal": sum(1 for x in fut if x["eligibility"]["tier"] == "HIGH-SIGNAL"),
        "rejected_irrelevant": sum(1 for x in fut if x["eligibility"]["tier"] == "REJECTED"),
        "needs_review": sum(1 for x in fut if x["eligibility"]["tier"] == "NEEDS REVIEW"),
        "missing_price": sum(1 for x in fut if x["price_state"] == "price unknown"),
        "missing_location": sum(1 for x in fut if not (x.get("city") or x.get("venue"))),
        "missing_organizer": sum(1 for x in fut if x["organizer"] == "UNKNOWN"),
    })  # fmt: skip
    health = {
        "scan_time": stamp(now),
        "totals": totals,
        "sources": rws,
        "note": ""
        if totals["accepted"]
        else "No source returned a structured future event in this scan — the per-source reasons below say why.",
    }
    snapshots = [
        (f.src, f.result.watch_lines) for f in fetched if f.result is not None and f.result.watch_lines is not None
    ]
    return Plan(res.created, res.merged, intake.new if intake else [], snapshots, health)


def run(conn: psycopg.Connection[Any], schema: str, fetched: list[Fetched], reg: registry.Registry,
        baselines: dict[str, Any], now: datetime, t0: float, clock: Callable[[], float]) -> dict[str, Any]:  # fmt: skip
    """Phase 3, in the caller's ONE transaction: re-read the CURRENT records under the events lock, ``compute``,
    write."""
    w = EventsWriter(conn, schema, now)
    w._lock()
    by_id, rows, _order = w._events()
    data = load_events(conn, schema, w.today, people=False)
    plan = compute(fetched, list(by_id.values()), data.leads, registry_cities(reg), data.pins, now, w.today,
                   round(clock() - t0, 1))  # fmt: skip
    for ev in plan.created:
        sources = sorted({str(s.get("source_id", "")) for s in ev["sources"]})
        w._write_event(str(ev["id"]), None, None, ev, "scan_create", {"source_ids": sources})
    for eid, ev in plan.merged.items():
        w._write_event(eid, by_id[eid], rows[eid], ev, "scan_merge", {})
    for rec in reversed(plan.leads):  # oldest first, so the newest gets the latest created_at (listed first)
        _insert_lead(w, rec)
    for src, new_lines in plan.snapshots:  # only fetched watchers: a failed fetch keeps the last good baseline
        w._rows(
            "insert into {s}.event_watch_snapshots (source_id, url, lines, seeded_from) values (%s, %s, %s, %s) "
            "on conflict (source_id) do update set url = excluded.url, lines = excluded.lines, updated_at = now()",
            (src["id"], src.get("url", ""), Jsonb(new_lines), (baselines.get(src["id"]) or {}).get("seeded_from")),
        )
    if reg.changed:
        w._rows(
            "insert into {s}.documents (key, body) values ('event_sources.json', %s) on conflict (key) do update "
            "set body = excluded.body, updated_at = now()",
            (Jsonb(reg.document),),
        )
    w._rows(
        "insert into {s}.documents (key, body) values ('event_health.json', %s) on conflict (key) do update "
        "set body = excluded.body, updated_at = now()",
        (Jsonb(plan.health),),
    )
    return plan.health


class _Late(Exception):
    """The deadline passed before a bounded transaction could commit."""


CANCEL_EVERY_S = 0.1  # after the deadline, how often the canceller cancels again until the transaction exits

# a test hook (``None`` in production): called after a statement passed the deadline check and before it is sent
_after_check: Callable[[Any, float], None] | None = None


class _InFlight:
    """Whether a statement of this transaction is on its way to, or running on, the server."""

    def __init__(self) -> None:
        self.busy = False


def _deadline_cursor(done_by: float, clock: Callable[[], float], flight: _InFlight) -> type[psycopg.Cursor[Any]]:
    """A cursor class whose every statement first refuses an expired budget (Codex H-119); a statement that passes the
    check but reaches the server after the deadline is cancelled by ``_Canceller``, which keeps cancelling until the
    transaction exits (Codex H-121)."""

    class DeadlineCursor(psycopg.Cursor[Any]):
        def execute(
            self, query: Any, params: Any = None, *, prepare: bool | None = None, binary: bool | None = None
        ) -> Any:
            if clock() >= done_by:
                raise _Late
            flight.busy = True  # from here until it returns, a late statement is cancelled
            try:
                if _after_check is not None:
                    _after_check(query, done_by)
                return psycopg.Cursor.execute(self, query, params, prepare=prepare, binary=binary)
            finally:
                flight.busy = False

    return DeadlineCursor


class _Canceller:
    """From ``done_by`` until stopped, cancel the connection's statement every ``CANCEL_EVERY_S`` WHILE one is in
    flight: a statement dispatched after the deadline (even one that passed the cursor check just before it) is
    cancelled within that interval, whatever timeout it was given. While the connection is idle nothing is sent (a
    cancel opens a connection of its own)."""

    def __init__(
        self, conn: psycopg.Connection[Any], done_by: float, clock: Callable[[], float], flight: _InFlight
    ) -> None:
        self._conn, self._done_by, self._clock, self._flight = conn, done_by, clock, flight
        self._stop = threading.Event()
        self.cancels = 0
        self._thread = threading.Thread(target=self._run, name="pz-scan-canceller", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        if self._stop.wait(max(0.0, self._done_by - self._clock())):
            return
        while not self._stop.is_set():
            if self._flight.busy:
                with contextlib.suppress(Exception):  # a cancel that cannot be delivered is retried on the next tick
                    self._conn.cancel_safe(timeout=2.0)
                    self.cancels += 1
            if self._stop.wait(CANCEL_EVERY_S):
                return

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3.0)


MIN_CONNECT_S = 2  # libpq treats any connect_timeout below 2 s as 2 s


def _connect(db_url: str, *, connect_timeout: int) -> psycopg.Connection[Any]:
    """The connection ``bounded_transaction`` opens (a seam: a test delays it deterministically)."""
    return connect(db_url, connect_timeout=connect_timeout)


@contextmanager
def bounded_transaction(db_url: str, done_by: float, clock: Callable[[], float]) -> Iterator[psycopg.Connection[Any]]:
    """A transaction that cannot outlive ``done_by`` (Codex H-117 / H-119 / H-121): the connect waits at most the time
    left; the statement and lock waits are limited to the time left at entry; no statement starts after the deadline
    (``_deadline_cursor``); from the deadline on, ``_Canceller`` cancels whatever is running until the transaction
    exits (cumulative work, and a statement that slipped past the check); and the deadline is checked again before
    commit, so a late write rolls back. Any of these is a 503 that saved nothing."""
    left = done_by - clock()
    # Codex H-284: libpq's smallest connect timeout is 2 s, so a new connection that cannot fit in the time left is not
    # attempted at all, and any timeout is rounded DOWN to the time left (never past the deadline)
    if left < MIN_CONNECT_S:
        raise EventsError(503, WRITE_DEADLINE)
    try:
        conn = _connect(db_url, connect_timeout=math.floor(left))
    except psycopg.OperationalError as exc:
        if done_by - clock() <= 0:
            raise EventsError(503, WRITE_DEADLINE) from exc
        raise
    flight = _InFlight()
    conn.cursor_factory = _deadline_cursor(done_by, clock, flight)
    canceller = _Canceller(conn, done_by, clock, flight)
    try:
        with conn.transaction():
            ms = int((done_by - clock()) * 1000)
            if ms <= 0:
                raise _Late
            conn.execute(sql.SQL("set local lock_timeout = {}").format(sql.Literal(f"{ms}ms")))
            conn.execute(sql.SQL("set local statement_timeout = {}").format(sql.Literal(f"{ms}ms")))
            yield conn
            if clock() >= done_by:  # before commit: a write that finished late is rolled back
                raise _Late
    except (_Late, psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled) as exc:
        raise EventsError(503, WRITE_DEADLINE) from exc
    finally:
        canceller.stop()
        conn.close()


def scan(
    db_url: str,
    schema: str,
    now: datetime,
    fetcher: Fetcher | None = None,
    *,
    deadline_s: float = SCAN_DEADLINE_S,
    clock: Callable[[], float] = time.monotonic,
    transport: net.Transport | None = None,
    resolver: net.Resolver | None = None,
    still_due: occurrence.StillDue | None = None,
) -> dict[str, Any]:
    """The whole scan (see the module docstring). Returns the new health document. Every blocking wait is bounded by
    ONE wall-clock budget: fetching stops at ``budget()[0]`` (DNS, connects and reads included, through
    ``core.net``), and the write phase's lock and statement waits are limited to the time left before
    ``budget()[1]``; a write cut off by the deadline saves nothing (503). The scan lock is released on every path.
    ``still_due``: the background-jobs runner's occurrence check (review 032c), run on the lock's connection right
    after the scan lock is taken and before anything is read or fetched; ``False`` raises ``AlreadyRan`` and the scan
    does nothing (``None``: no check)."""
    key = f"{schema}.events.scan"
    lock = connect(db_url, autocommit=True)  # a dedicated SESSION for the scan lock
    try:
        if not lock.execute("select pg_try_advisory_lock(hashtext(%s))", (key,)).fetchone()[0]:  # type: ignore[index]
            raise EventsError(409, ALREADY_RUNNING)
        try:
            occurrence.check(still_due, lock)
            t0 = clock()
            stop_fetching, done_by = budget(t0, deadline_s)
            with bounded_transaction(db_url, done_by, clock) as conn:  # phase 1, closed before any fetch
                ensure_intake_open(conn, schema)  # never fetch for a scan that could not be written
                reg, prev, baselines = _read(conn, schema, now)
            source = fetcher or NetFetcher(stop_fetching, transport, resolver)
            fetched = _fetch_all(reg.sources, prev, baselines, source, now, stop_fetching, clock)
            with bounded_transaction(db_url, done_by, clock) as conn:  # phase 3
                return run(conn, schema, fetched, reg, baselines, now, t0, clock)
        finally:
            lock.execute("select pg_advisory_unlock(hashtext(%s))", (key,))
    finally:
        lock.close()


def find_answer(health: dict[str, Any]) -> dict[str, Any]:
    """The old ``event_find`` body around a health document."""
    t = health.get("totals", {})
    return {
        "added": t.get("review", 0),
        "accepted": t.get("accepted", 0),
        "dropped_past": t.get("past", 0),
        "dropped_dupe": t.get("dups", 0),
        "health": health,
        "report": [
            {"source": r["name"], "status": r["status"], "kind": r["kind"], "note": r["note"]}
            for r in health["sources"]
        ],
    }
