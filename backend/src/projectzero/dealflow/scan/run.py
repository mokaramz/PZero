"""The Deal Flow scan (review 034a): the old ``run_scan_job`` -> ``connectors.run_registry_concurrent`` ->
``discovery.ingest_scan`` in three phases, as the Events scan (``events/scan.py``), so no transaction is open while the
network is used:

1. **read** (one short transaction): ``ensure_intake_open`` (decision f: nothing is fetched for a scan that could not
   be written), the stored registry as the old ``load_registry()`` gave it, and each page watcher's baseline,
   resolved AT SCAN TIME (revision 2): its ``scan_watch_snapshots`` row, else the archived ``.watch/<uid(url)>.json``
   in ``legacy_documents``, else none (a first run, its lines become the baseline). No backfill.
2. **fetch** (no transaction): the old bounded pool, the old budgets (6 workers; 240 s in all, 90 s per source, 20 s
   per request), a cooperative deadline per worker, a HARD cutoff of the collection at the budget (a late source is
   the old "timeout" row, its late result discarded), the cut ``_scan_one`` for each source on a COPY, then the cut
   ``_resolve_batch``. Every request goes through ``core/net`` (decision e: the TLS-insecure retry is dropped).
3. **write** (ONE ``bounded_transaction``, ``ingest.write``): the deliveries through the intake on THIS connection,
   the run record, the sources' runtime keys (a toggle made mid-scan survives) and the new baselines, together.

One scan at a time: a SESSION advisory lock ``<schema>.dealflow.scan`` on a dedicated autocommit connection, released
on every path. ``start_scan`` (the route) answers the old busy body when this process or another session holds it.
``still_due``: the runner's occurrence check (032c), run on the lock's connection right after the lock is taken.
No machine triage is started (decision d): the summary's ``triage`` says it arrives with the triage port.
"""

from __future__ import annotations

import contextlib
import copy
import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.core import net, occurrence
from projectzero.core.db import connect, schema_ident, transaction
from projectzero.dealflow.intake.postgres import ensure_intake_open
from projectzero.dealflow.scan import parsers, seams
from projectzero.dealflow.scan.ingest import Fetched, SourceResult, batch_hosts, write
from projectzero.dealflow.sources.normalize import load_registry
from projectzero.dealflow.sources.store import SourcesStore
from projectzero.events.edits import EventsError
from projectzero.events.scan import bounded_transaction
from projectzero.network.view import BERLIN, berlin_now

cut: Any = parsers  # the cut old code is untyped (see parsers.py): every call goes through this alias
MAX_WORKERS = 6
TIME_BUDGET_S = 240  # the old ``scan_time_budget``: the whole fetch
SOURCE_BUDGET_S = 90  # the old ``scan_source_budget``: one source
REQUEST_TIMEOUT_S = 20  # the old ``PZ_TIMEOUT`` (``parsers.TIMEOUT``)
WRITE_BUDGET_S = 60.0  # the write phase after the fetch (the old ingest had no bound; the job's 900 s covers both)
DEFAULT_DAYS = 7
LOCK = "{schema}.dealflow.scan"
BUSY_NOTE = "scan already running — progress below"
ALREADY_RUNNING_JOB = "skipped — a scan is already running"  # the old scheduler's note
ProgressCb = Callable[[int, int, dict[str, Any]], None]


WRITE_DEADLINE = (
    "the scan's deadline passed before its results could be written (the database was busy) — nothing was saved; "
    "scan again"
)


class ScanBusy(Exception):
    """Another scan holds the scan lock."""


class ScanWriteDeadline(RuntimeError):
    """Phase 3 could not finish within its budget: it rolled back, nothing was saved."""


# ------------------------------------------------------------------------------------------------ phase 1
def read(conn: psycopg.Connection[Any], schema: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    ensure_intake_open(conn, schema)
    sources = load_registry({"sources": SourcesStore(conn, schema).stored()})["sources"]
    watched = {cut._uid(str(s.get("url") or "")): str(s.get("url") or "") for s in sources
               if isinstance(s, dict) and s.get("parser") == "page_diff"}  # fmt: skip
    baselines: dict[str, dict[str, Any]] = {}
    if watched:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                sql.SQL("select uid, lines from {}.scan_watch_snapshots where uid = any(%s)").format(
                    schema_ident(schema)
                ),
                (list(watched),),
            )
            for r in cur.fetchall():
                baselines[r["uid"] + ".json"] = {"lines": r["lines"], "seeded_from": None}
            missing = {f".watch/{uid}.json": uid for uid in watched if uid + ".json" not in baselines}
            if missing:
                cur.execute(
                    sql.SQL("select path, parsed from {}.legacy_documents where path = any(%s)").format(
                        schema_ident(schema)
                    ),
                    (list(missing),),
                )
                for r in cur.fetchall():
                    if isinstance(r["parsed"], list):
                        baselines[missing[r["path"]] + ".json"] = {"lines": r["parsed"], "seeded_from": r["path"]}
    return [s for s in sources if isinstance(s, dict)], baselines


# ------------------------------------------------------------------------------------------------ phase 2
def fetch(
    sources: list[dict[str, Any]],
    baselines: dict[str, dict[str, Any]],
    *,
    days: int,
    today: date,
    now_stamp: str,
    transport: net.Transport | None = None,
    resolver: net.Resolver | None = None,
    max_workers: int = MAX_WORKERS,
    time_budget: float = TIME_BUDGET_S,
    source_budget: float = SOURCE_BUDGET_S,
    progress_cb: ProgressCb | None = None,
) -> Fetched:
    """The old ``run_registry_concurrent`` up to its persistence (which is phase 3's)."""
    snapshot = copy.deepcopy(sources)
    t0 = time.time()
    global_dl = t0 + max(1, int(time_budget))
    per_src = max(1, int(source_budget))
    lock = threading.Lock()
    cands: list[dict[str, Any]] = []
    report: list[dict[str, Any]] = []
    done: dict[int, SourceResult] = {}
    timeout_ids: list[str] = []
    total = len(snapshot)
    lines = {k: v.get("lines") for k, v in baselines.items()}

    def note_progress(row: dict[str, Any]) -> None:
        if progress_cb:
            with contextlib.suppress(Exception):
                progress_cb(len(report), total, row)

    def task(i: int, src_copy: dict[str, Any]) -> tuple[int, dict[str, Any], Any, seams.SourceContext]:
        dl = min(global_dl, time.time() + per_src)
        ctx = seams.SourceContext(today=today, transport=transport, resolver=resolver, baselines=lines, deadline=dl)
        cut._set_deadline(dl)
        try:
            with seams.source(ctx):
                return i, src_copy, cut._scan_one(src_copy, days, now_stamp), ctx
        finally:
            cut._set_deadline(None)

    pool = ThreadPoolExecutor(max_workers=max(1, int(max_workers)), thread_name_prefix="pz-dealflow-scan")
    futs = {pool.submit(task, i, copy.deepcopy(s)): i for i, s in enumerate(snapshot)}
    pending = set(futs)

    def collect(fin: set[Any]) -> None:
        for fut in fin:
            ctx: seams.SourceContext | None
            try:
                i, src_copy, (c, row), ctx = fut.result()
            except Exception as e:
                i = futs[fut]
                src_copy, c, ctx = None, [], None
                s = snapshot[i]
                row = {"source": s["name"], "tier": s["kind"], "status": "failed",
                       "note": f"{type(e).__name__}: {str(e)[:70]}", "geo": s.get("geo", []),
                       "source_id": s["id"], "url": s.get("url", ""), "raw": 0, "count": 0}  # fmt: skip
            with lock:
                done[i] = SourceResult(i, src_copy, ctx)
                cands.extend(c)
                report.append(row)
            note_progress(row)

    try:
        while pending:
            left = global_dl - time.time()
            if left <= 0:
                break  # HARD cutoff: stop collecting at the budget
            fin, pending = wait(pending, timeout=min(1.0, left), return_when=FIRST_COMPLETED)
            collect(fin)
        fin, pending = wait(pending, timeout=0)  # zero-cost sweep: futures already finished pre-cutoff
        collect(fin)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # never wait for stragglers; cooperative deadlines end them
    for i, s in enumerate(snapshot):
        if i in done:
            continue
        if s.get("enabled"):
            timeout_ids.append(s["id"])
            row = {"source": s["name"], "tier": s["kind"], "status": "failed", "geo": s.get("geo", []),
                   "source_id": s["id"], "url": s.get("url", ""), "raw": 0, "count": 0,
                   "note": f"timeout — scan budget ({time_budget}s) hit; unfinished, fully retryable next scan "
                           "(HWM untouched, late result discarded)"}  # fmt: skip
        else:
            row = {"source": s["name"], "tier": s["kind"], "status": "off", "note": s.get("notes", "disabled"),
                   "geo": s.get("geo", [])}  # fmt: skip
        report.append(row)
        note_progress(row)
    kept = {id(c) for c in cands}
    every = [rec for r in done.values() if r.ctx is not None for rec, _key in r.ctx.records if id(rec) in kept]
    host_of = batch_hosts(cands)
    merged = cut._resolve_batch(cands, report)
    return Fetched(snapshot, baselines, done, report, merged, host_of, every, timeout_ids, now_stamp, days,
                   round(time.time() - t0, 1))  # fmt: skip


# ------------------------------------------------------------------------------------------------ the whole scan
def _berlin_clock(clock: Callable[[], datetime] | None) -> Callable[[], datetime]:
    """An AWARE Berlin clock (a naive instant is Berlin wall time, as the runner's ``now`` may be)."""
    if clock is None:
        return lambda: berlin_now(datetime.now().astimezone())
    given = clock

    def aware() -> datetime:
        t = given()
        return berlin_now(t) if t.tzinfo is not None else t.replace(tzinfo=BERLIN)

    return aware


def take_lock(db_url: str, schema: str) -> psycopg.Connection[Any]:
    """The scan lock on a dedicated autocommit SESSION; ``ScanBusy`` when another holds it."""
    conn = connect(db_url, autocommit=True)
    row = conn.execute("select pg_try_advisory_lock(hashtext(%s))", (LOCK.format(schema=schema),)).fetchone()
    if not (row and row[0]):
        conn.close()
        raise ScanBusy
    return conn


def release_lock(conn: psycopg.Connection[Any], schema: str) -> None:
    try:
        with contextlib.suppress(Exception):
            conn.execute("select pg_advisory_unlock(hashtext(%s))", (LOCK.format(schema=schema),))
    finally:
        conn.close()


def scan(
    db_url: str,
    schema: str,
    *,
    days: int = DEFAULT_DAYS,
    clock: Callable[[], datetime] | None = None,
    transport: net.Transport | None = None,
    resolver: net.Resolver | None = None,
    max_workers: int = MAX_WORKERS,
    time_budget: float = TIME_BUDGET_S,
    source_budget: float = SOURCE_BUDGET_S,
    write_budget: float = WRITE_BUDGET_S,
    progress_cb: ProgressCb | None = None,
    still_due: occurrence.StillDue | None = None,
    trigger: str = "app",
    lock: psycopg.Connection[Any] | None = None,
    after_fetch: Callable[[Fetched], None] | None = None,
) -> dict[str, Any]:
    """The whole scan; returns the old summary. ``lock``: a scan-lock session the caller already took (``start_scan``);
    it is released here on every path. ``after_fetch``: a test seam between phases 2 and 3."""
    now = _berlin_clock(clock)
    held = lock if lock is not None else take_lock(db_url, schema)
    try:
        occurrence.check(still_due, held)
        start = now()
        t0 = time.monotonic()
        with bounded_transaction(db_url, t0 + 30.0, time.monotonic) as conn:  # phase 1, closed before any fetch
            sources, baselines = read(conn, schema)
        fetched = fetch(sources, baselines, days=days, today=start.date(), now_stamp=start.strftime("%Y-%m-%d %H:%M"),
                        transport=transport, resolver=resolver, max_workers=max_workers, time_budget=time_budget,
                        source_budget=source_budget, progress_cb=progress_cb)  # fmt: skip
        if after_fetch is not None:
            after_fetch(fetched)
        try:
            with bounded_transaction(db_url, time.monotonic() + write_budget, time.monotonic) as conn:  # phase 3
                return write(conn, schema, fetched, clock=now, trigger=trigger)
        except EventsError as exc:  # the bounded transaction's deadline: nothing was saved
            if exc.status != 503:
                raise
            raise ScanWriteDeadline(WRITE_DEADLINE) from exc
    finally:
        release_lock(held, schema)


# ------------------------------------------------------------------------------------------------ the route's job
# The old in-process job state (``discovery.SCAN_JOB``): one per (database, schema) of this process.
_JOBS: dict[tuple[str, str], dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


def _fresh() -> dict[str, Any]:
    return {"running": False, "done": 0, "total": 0, "rows": [], "result": None, "error": "", "started": ""}


def _job(db_url: str, schema: str) -> dict[str, Any]:
    return _JOBS.setdefault((db_url, schema), _fresh())


def scan_status(db_url: str, schema: str) -> dict[str, Any]:
    """The old ``GET /api/find_status`` body."""
    with _JOBS_LOCK:
        return copy.deepcopy(_job(db_url, schema))


def _busy(job: dict[str, Any]) -> dict[str, Any]:
    return {"running": True, "done": job["done"], "total": job["total"], "note": BUSY_NOTE}


def start_scan(
    db_url: str,
    schema: str,
    days: int,
    *,
    clock: Callable[[], datetime] | None = None,
    transport: net.Transport | None = None,
    resolver: net.Resolver | None = None,
    options: dict[str, Any] | None = None,
    wait_for: bool = False,
) -> dict[str, Any]:
    """The old ``start_scan`` (``POST /api/find``): the scan runs in a background thread, ``{"started": true}``; the old
    busy body while one runs, here or in another session (the scan lock). ``wait_for``: join the thread (tests)."""
    now = _berlin_clock(clock)
    with transaction(db_url) as conn:  # decision f: before the import, refused at once (IntakeClosedError)
        ensure_intake_open(conn, schema)
    with _JOBS_LOCK:
        job = _job(db_url, schema)
        if job["running"]:
            return _busy(job)
        try:
            held = take_lock(db_url, schema)
        except ScanBusy:
            return _busy(job)
        job.update(_fresh())
        job.update({"running": True, "started": now().strftime("%H:%M:%S")})

    def prog(done: int, total: int, row: dict[str, Any]) -> None:
        with _JOBS_LOCK:
            job["done"] = done
            job["total"] = total
            job["rows"].append(row)

    def body() -> None:
        try:
            summary = scan(db_url, schema, days=days, clock=clock, transport=transport, resolver=resolver,
                           progress_cb=prog, lock=held, **(options or {}))  # fmt: skip
            with _JOBS_LOCK:
                job["result"] = summary
                job["running"] = False
        except Exception as e:  # the old job: the error is shown, the next scan can start
            with _JOBS_LOCK:
                job["error"] = type(e).__name__ + ": " + str(e)[:160]
                job["running"] = False

    thread = threading.Thread(target=body, daemon=True, name="pz-dealflow-scan")
    thread.start()
    if wait_for:
        thread.join()
    return {"started": True}
