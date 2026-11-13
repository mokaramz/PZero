"""The background-jobs runner (review 032c): the old ``services/scheduler.py`` ``run_due`` / ``dry_run`` /
``status`` / ``recover_on_start`` / ``start_catch_up`` over the database, line for line where it is protocol.

What is the old protocol, kept: the due list is computed INSIDE the lock (``health.core.plan``, the one plan); jobs
run one after another in ``JOBS`` order and one failure never stops the rest; each result is classified
(``classify``) and recorded (``fails_in_row``, ``last_ok`` only on success, the history line); a missed interval runs
once; a busy lock records the old ``skipped`` runner record and runs nothing; the in-process ``STATE`` (per schema)
and its thread lock keep overlapping catch-ups inside one process apart (decision g).

What is new:

* **(a) the import marker first.** ``guard`` (``ensure_intake_open``) runs before ANY dispatch or bookkeeping:
  recovery, a busy run's ``skipped`` record and the runner records included. Before the import nothing is written to
  ``pz`` (``IntakeClosedError``; the CLI, the route and the catch-up answer ``IMPORT_REFUSED``).
* **The lock** is a session advisory lock on a dedicated connection (``store.try_lock``), never stale.
* **The fencing generation (revision 2).** Taking the lock increments ``job_lease.generation`` (``G``). Claiming a
  job and completing it are each ONE transaction that reads the lease ``FOR UPDATE`` and proceeds only if it is still
  ``G`` (completing: and only if the job's record is still ``running`` with ``"generation": G``). The runner records
  are conditional the same way. A stale worker (its lock connection died; a larger generation took over) writes
  nothing more and dispatches nothing more (``Stale``).
* **The occurrence check (revision 3).** Planning records each due job's ``last_seen`` (its occurrence reader's
  value) with ``G``; the job's entry point calls ``still_due(conn)`` right after taking its OWN lock and before any
  work: the lease is still ``G`` and the occurrence still ``last_seen``. Otherwise the job does nothing
  (``AlreadyRan``) and its result is the old ``skipped`` note ``"skipped — already ran"``.
* **(b)** the six unported jobs are never dispatched (``catalog.REAL`` has no entry; their plan rows are never
  overdue). **(e)** no backup (``background_backup`` is 032b's).
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from projectzero.core.db import connect, read_only_transaction, transaction
from projectzero.core.occurrence import ALREADY_RAN, AlreadyRan, StillDue
from projectzero.dealflow.intake.postgres import IntakeClosedError, ensure_intake_open
from projectzero.dealflow.scan import history as scan_history
from projectzero.events.when import BERLIN
from projectzero.health import core as health_core
from projectzero.health.catalog import classify
from projectzero.health.inputs_model import HealthInputs
from projectzero.jobs import store
from projectzero.jobs.catalog import REAL, Job, JobContext, JobDeps
from projectzero.jobs.ported import RUNNER, JobsRunner
from projectzero.network.view import berlin_now
from projectzero.news import store as news_store
from projectzero.news.inputs_model import base_from_docs
from projectzero.validation.core import ts

log = logging.getLogger(__name__)
IMPORT_REFUSED = (
    "the live import has not run yet: the background jobs run nothing and record nothing before it "
    "(run `python -m projectzero.ops.legacy apply --confirm` first)"
)
INTERRUPTED_NOTE = "interrupted by an app restart — runs again when due"
Guard = Callable[[psycopg.Connection[Any], str], None]
Clock = Callable[[], datetime]

_lock = threading.Lock()
_STATES: dict[str, dict[str, Any]] = {}


def _state(schema: str) -> dict[str, Any]:
    """The old in-process ``STATE`` of one schema (call with ``_lock`` held)."""
    return _STATES.setdefault(
        schema, {"running": False, "queue": [], "current": None, "done": [], "started": None, "finished": None}
    )


class Stale(Exception):
    """This runner no longer owns the scheduler: a larger generation took over (its lock connection died)."""


def _clock(now: datetime | None, clock: Clock | None) -> Clock:
    if clock is not None:
        return clock
    if now is not None:
        return lambda: now
    return lambda: datetime.now(BERLIN)


def _naive(t: datetime) -> datetime:
    """The plan's clock: naive Berlin wall time."""
    return berlin_now(t).replace(tzinfo=None)


# ------------------------------------------------------------------------------------------------ switches
def env_enabled() -> bool:
    return os.environ.get("PZ_CATCHUP", "1").strip().lower() not in ("0", "false", "no", "off")


def enabled(config: Any) -> bool:
    """The old ``enabled()``: ``PZ_CATCHUP`` off, or ``config.json`` ``catch_up.enabled`` false, disables it."""
    if not env_enabled():
        return False
    return ((config if isinstance(config, dict) else {}).get("catch_up") or {}).get("enabled", True) is not False


def import_open(conn: psycopg.Connection[Any], schema: str, guard: Guard = ensure_intake_open) -> bool:
    try:
        guard(conn, schema)
    except IntakeClosedError:
        return False
    return True


# ------------------------------------------------------------------------------------------------ the plan
@dataclass(frozen=True)
class Catalog:
    rows: list[dict[str, Any]]  # the plan's job rows, in order
    runnable: dict[str, Job]  # the jobs the runner can dispatch
    runner: JobsRunner


def catalog(jobs: Sequence[Job] | None = None) -> Catalog:
    """The real jobs (the active ``JOBS`` rows; only ``REAL`` runnable), or the given (fake) jobs, all runnable."""
    if jobs is None:
        return Catalog(health_core.active_jobs(), dict(REAL), RUNNER)
    return Catalog([j.row() for j in jobs], {j.id: j for j in jobs}, RUNNER.over(j.id for j in jobs))


def plan_inputs(conn: psycopg.Connection[Any], schema: str) -> HealthInputs:
    """Only what the plan reads (``health.core.plan``): the job records, ``config.json``, and the three ``last``
    readers' stores (the archived scan history, ``event_health.json``, the News runs log)."""
    scans = store.archived(conn, schema, "scan_history.json")  # overlaid by the new runs (review 034a, the ONE reader)
    return HealthInputs(
        job_state=store.job_records(conn, schema),
        config=store.config(conn, schema),
        scan_history=scan_history.scan_history(conn, schema, scans if isinstance(scans, dict) else {"scans": []}),
        event_health=store.document(conn, schema, "event_health.json") or {},
        news=base_from_docs(news_store.log_texts(conn, schema, ("runs",))),
    )


def plan(
    conn: psycopg.Connection[Any], schema: str, now: datetime, cat: Catalog, generation: int | None
) -> list[dict[str, Any]]:
    """The old ``plan(now)`` (``now``: naive Berlin wall time) with the runner seen at ``generation``."""
    return health_core.plan(plan_inputs(conn, schema), now, cat.runner.holding(generation), cat.rows)


# ------------------------------------------------------------------------------------------------ the lease
@dataclass
class Lease:
    conn: psycopg.Connection[Any]  # the dedicated lock session
    schema: str
    generation: int
    holder: dict[str, Any]

    def release(self) -> None:
        with contextlib.suppress(Exception):  # a connection that died has released its lock already
            store.unlock(self.conn, self.schema)
        with contextlib.suppress(Exception):
            self.conn.close()


def acquire(db_url: str, schema: str, source: str, now: datetime) -> Lease | None:
    """Take the scheduler lock and a new generation, or ``None`` when another runner holds it."""
    conn = connect(db_url, autocommit=True)
    try:
        if not store.try_lock(conn, schema):
            conn.close()
            return None
        holder = {"source": source, "pid": os.getpid(), "since": ts(now)}
        return Lease(conn, schema, store.take_lease(conn, schema, holder), holder)
    except BaseException:
        conn.close()
        raise


def _record_busy(db_url: str, schema: str, source: str, at: datetime, guard: Guard) -> dict[str, Any]:
    """The old busy-lock outcome: ``source``'s runner record says ``skipped`` (who holds the lock, since when) and the
    one history-less ``*`` row is returned; nothing runs."""
    with transaction(db_url) as conn:
        guard(conn, schema)
        lk = store.lease(conn, schema)[1] or {}
        note = (f"skipped — another run is in progress ({lk.get('source', 'unknown')}, pid {lk.get('pid', '?')}, "
                f"since {lk.get('since', '?')})")  # fmt: skip
        _runner_record(conn, schema, source, at=ts(at), outcome="skipped", note=note)
    return {"job": "*", "label": "Job runner", "ok": True, "outcome": "skipped", "note": note, "seconds": 0.0,
            "at": ts(at), "source": source}  # fmt: skip


def _runner_record(conn: psycopg.Connection[Any], schema: str, source: str, **kw: Any) -> None:
    """The old ``_runner_record``: the source's record (the overlay's) updated with ``kw``."""
    current = store.runner_records(conn, schema).get(source)
    record = dict(current) if isinstance(current, dict) else {}
    record.update(kw)
    store.write_runner(conn, schema, source, record)


def _fenced_runner_record(db_url: str, schema: str, g: int, guard: Guard, source: str, **kw: Any) -> None:
    with transaction(db_url) as conn:
        guard(conn, schema)
        if store.lease_for_update(conn, schema) != g:
            raise Stale
        _runner_record(conn, schema, source, **kw)


def _still_due(schema: str, g: int, job: Job, last_seen: Any) -> StillDue:
    def check(conn: psycopg.Connection[Any]) -> bool:
        return store.lease(conn, schema)[0] == g and job.occurrence(conn, schema) == last_seen

    return check


def _claim(
    db_url: str, schema: str, g: int, job: Job, source: str, at: str, guard: Guard
) -> tuple[dict[str, Any], datetime]:
    """ONE transaction: the lease is still ``g`` -> the job's record becomes ``running`` with ``generation: g``."""
    with transaction(db_url) as conn:
        guard(conn, schema)
        if store.lease_for_update(conn, schema) != g:
            raise Stale
        prev = store.record_for_update(conn, schema, job.id) or {}
        record = dict(prev)
        record.update(state="running", started=at, pid=os.getpid(), source=source, generation=g)
        started_at = store.claim_record(conn, schema, job.id, job.interval_h, record)
        return prev, started_at


def _complete(
    db_url: str, schema: str, g: int, job: Job, fields: dict[str, Any], row: dict[str, Any], started_at: datetime,
    guard: Guard,
) -> None:  # fmt: skip
    """ONE transaction: the lease is still ``g`` AND the record is still ``running`` under ``g`` -> the outcome, the
    history line and ``fails_in_row`` are written. Otherwise nothing is (``Stale``)."""
    with transaction(db_url) as conn:
        guard(conn, schema)
        if store.lease_for_update(conn, schema) != g:
            raise Stale
        cur = store.record_for_update(conn, schema, job.id)
        if cur is None or cur.get("state") != "running" or cur.get("generation") != g:
            raise Stale
        record = dict(cur)
        record.update(fields)
        finished_at = store.complete_record(conn, schema, job.id, record, str(fields["outcome"]))
        store.append_run(conn, schema, job.id, started_at, finished_at, bool(row["ok"]), row)


# ------------------------------------------------------------------------------------------------ run_due
def run_due(
    db_url: str,
    schema: str,
    *,
    source: str = "app",
    only: list[str] | None = None,
    now: datetime | None = None,
    clock: Clock | None = None,
    jobs: Sequence[Job] | None = None,
    deps: JobDeps | None = None,
    monotonic: Callable[[], float] = time.time,
    guard: Guard = ensure_intake_open,
    lease: Lease | None = None,
) -> list[dict[str, Any]]:
    """Run every overdue job once, sequentially, holding the scheduler lock (the old ``run_due``). The due list is
    computed INSIDE the lock, so a job another runner has just finished is never run again. A busy lock returns one
    ``skipped`` row and runs nothing. Raises ``IntakeClosedError`` before the import (nothing written). ``now`` /
    ``clock``: the run's clock (default: now in Berlin); ``jobs``: fake jobs (default: the real ones)."""
    clk = _clock(now, clock)
    cat = catalog(jobs)
    deps = deps or JobDeps()
    with transaction(db_url) as conn:
        guard(conn, schema)  # (a): before anything is written
    if lease is None:  # a caller (the manual route) may have taken the lock already, to answer truthfully
        lease = acquire(db_url, schema, source, clk())
    if lease is None:
        return [_record_busy(db_url, schema, source, clk(), guard)]
    g = lease.generation
    results: list[dict[str, Any]] = []
    t_run = monotonic()
    try:
        with transaction(db_url) as conn:
            guard(conn, schema)
            planned = [
                p for p in plan(conn, schema, _naive(clk()), cat, g) if p["overdue"] and (not only or p["id"] in only)
            ]
            due = [(p, cat.runnable[p["id"]]) for p in planned if p["id"] in cat.runnable]  # (b)
            seen = {job.id: job.occurrence(conn, schema) for _p, job in due}  # revision 3: the planned occurrences
        _fenced_runner_record(db_url, schema, g, guard, source, at=ts(clk()), started=ts(clk()), finished=None,
                              outcome="running", pid=os.getpid(), due=[p["id"] for p, _j in due], note="")  # fmt: skip
        with _lock:
            _state(schema).update(running=True, queue=[p["label"] for p, _j in due], done=[], started=ts(clk()),
                                  finished=None)  # fmt: skip
        for _p, job in due:
            with _lock:
                _state(schema)["current"] = job.label
            prev, started_at = _claim(db_url, schema, g, job, source, ts(clk()), guard)
            t0 = monotonic()
            error = ""
            ctx = JobContext(db_url, schema, clk(), _still_due(schema, g, job, seen[job.id]), deps, guard, source)
            try:
                note, ok = job.run(ctx), True
            except AlreadyRan:  # revision 3: this occurrence ran meanwhile, or this runner was replaced
                note, ok = ALREADY_RAN, True
            except Exception as e:  # one failing job never stops the rest
                log.exception("background job %s failed", job.id)
                error = f"{type(e).__name__}: {str(e)[:300]}"
                note, ok = f"failed: {error[:200]}", False
            outcome = classify(str(note), ok)
            seconds = round(monotonic() - t0, 1)
            fields: dict[str, Any] = {"state": "ok" if ok else "failed", "finished": ts(clk()), "note": note,
                                      "outcome": outcome, "seconds": seconds, "error": error,
                                      "fails_in_row": 0 if ok else int(prev.get("fails_in_row") or 0) + 1}  # fmt: skip
            if ok:
                fields["last_ok"] = fields["finished"]
            row = {"job": job.id, "label": job.label, "ok": ok, "outcome": outcome, "note": note, "seconds": seconds,
                   "at": fields["finished"], "source": source, **({"error": error} if error else {})}  # fmt: skip
            _complete(db_url, schema, g, job, fields, row, started_at, guard)
            results.append(row)
            with _lock:
                _state(schema)["done"].append(row)
        failed = sum(1 for r in results if not r["ok"])
        _fenced_runner_record(db_url, schema, g, guard, source, finished=ts(clk()),
                              seconds=round(monotonic() - t_run, 1),
                              outcome="failed" if failed else ("ok" if results else "nothing_due"),
                              ran=len(results), failed=failed)  # fmt: skip
    except Stale:  # revision 2: a larger generation took over; this worker writes and dispatches nothing more
        log.warning("background run %s (generation %s) was replaced; it stops here", source, g)
    finally:
        with _lock:
            _state(schema).update(running=False, current=None, finished=ts(clk()))
        lease.release()
    return results


# ------------------------------------------------------------------------------------------------ the rest
def dry_run(
    db_url: str, schema: str, *, now: datetime | None = None, jobs: Sequence[Job] | None = None
) -> dict[str, Any]:
    """What a run WOULD do now: nothing is executed and nothing is written (a read-only transaction)."""
    t = _naive(_clock(now, None)())
    cat = catalog(jobs)
    with read_only_transaction(db_url) as conn:
        pl = plan(conn, schema, t, cat, store.held_generation(conn, schema))
        return {"due": [p for p in pl if p["overdue"]], "not_due": [p for p in pl if not p["overdue"]],
                "lock": store.lock_status(conn, schema, t), "enabled": enabled(store.config(conn, schema))}  # fmt: skip


def lock_status(db_url: str, schema: str, *, now: datetime | None = None) -> dict[str, Any]:
    t = _naive(_clock(now, None)())
    with read_only_transaction(db_url) as conn:
        return store.lock_status(conn, schema, t)


def recover_on_start(
    db_url: str,
    schema: str,
    *,
    source: str = "app",
    now: datetime | None = None,
    guard: Guard = ensure_intake_open,
) -> list[str]:
    """The old ``recover_on_start``, under the lock: a record still ``running`` while no runner holds the lock is
    ``interrupted`` (the old note) and due again. Taking the lock takes a new generation, so a worker whose lock died
    can complete nothing it claimed. A held lock means a live runner: its records are its own (``[]``)."""
    t = _clock(now, None)()
    with transaction(db_url) as conn:
        guard(conn, schema)  # (a)
    lease = acquire(db_url, schema, source, t)
    if lease is None:
        return []
    try:
        fixed: list[str] = []
        with transaction(db_url) as conn:
            guard(conn, schema)
            if store.lease_for_update(conn, schema) != lease.generation:
                return []
            for jid, s in store.job_records(conn, schema).items():
                if isinstance(s, dict) and s.get("state") == "running":
                    rec = dict(s)
                    rec["state"] = "interrupted"
                    rec["note"] = INTERRUPTED_NOTE
                    store.write_record(conn, schema, jid, rec)
                    fixed.append(jid)
            # a runner whose lock died (a stale worker, of any source) left its own record ``running``: with no runner
            # holding the lock it is ``interrupted`` too, so the diagnostics never show a run that will never finish
            for src, r in store.new_runner_records(conn, schema).items():
                if isinstance(r, dict) and r.get("outcome") == "running":
                    store.write_runner(conn, schema, src, {**r, "outcome": "interrupted", "note": INTERRUPTED_NOTE})
        return fixed
    finally:
        lease.release()


def status(db_url: str, schema: str, *, now: datetime | None = None) -> dict[str, Any]:
    """The old ``status()`` (``GET /api/catchup``): the in-process run, the switch, the plan, the lock and the runner
    records (the ONE overlay reader)."""
    with _lock:
        st = _state(schema)
        s = dict(st)
        s["queue"] = list(st["queue"])
        s["done"] = list(st["done"])
    t = _naive(_clock(now, None)())
    with read_only_transaction(db_url) as conn:
        s["enabled"] = enabled(store.config(conn, schema))
        s["plan"] = plan(conn, schema, t, catalog(), store.held_generation(conn, schema))
        s["lock"] = store.lock_status(conn, schema, t)
        s["runners"] = store.runner_records(conn, schema)
    return s


def running(schema: str) -> bool:
    with _lock:
        return bool(_state(schema)["running"])


def start_manual(
    db_url: str,
    schema: str,
    only: list[str] | None,
    *,
    deps: JobDeps | None = None,
    clock: Clock | None = None,
    guard: Guard = ensure_intake_open,
) -> dict[str, Any]:
    """``POST /api/catchup_run``: the old answer ``{started: true}`` and the run in a thread (source ``app``), or
    ``{started: false, reason}`` when a run is in progress, in this process OR in another one, or before the import.
    Codex H-327: the scheduler lock is taken HERE, before the answer, and handed to the thread's run; when another
    runner holds it, the answer is ``already running`` with the old busy record (``app: skipped``) and nothing runs."""
    with read_only_transaction(db_url) as conn:
        if not import_open(conn, schema, guard):
            return {"started": False, "reason": IMPORT_REFUSED}
    with _lock:
        st = _state(schema)
        if st["running"]:
            return {"started": False, "reason": "already running"}
        st["running"] = True  # closes the gap before the thread's run marks itself
    try:
        lease = acquire(db_url, schema, "app", _clock(None, clock)())
        if lease is None:  # another process holds the scheduler lock
            _record_busy(db_url, schema, "app", _clock(None, clock)(), guard)
    except BaseException:
        with _lock:
            _state(schema)["running"] = False
        raise
    if lease is None:
        with _lock:
            _state(schema)["running"] = False
        return {"started": False, "reason": "already running"}
    held = lease

    def work() -> None:
        try:
            run_due(db_url, schema, source="app", only=only, deps=deps, clock=clock, guard=guard, lease=held)
        except Exception:
            log.exception("manual catch-up failed")
        finally:
            held.release()  # idempotent: run_due releases it too, but not when it raised before its own ``try``
            with _lock:
                _state(schema)["running"] = False

    threading.Thread(target=work, daemon=True, name="pz-catch-up-manual").start()
    return {"started": True}


def start_catch_up(
    db_url: str,
    schema: str,
    *,
    delay_s: float = 4.0,
    deps: JobDeps | None = None,
    clock: Clock | None = None,
    guard: Guard = ensure_intake_open,
    runner: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """The old ``start_catch_up``: called once at app start (after ``recover_on_start``). Never raises; the overdue
    jobs run in a thread after ``delay_s`` (the old 4 seconds)."""
    try:
        if not env_enabled():
            return {"started": False, "reason": "disabled"}
        with read_only_transaction(db_url) as conn:
            if not enabled(store.config(conn, schema)):
                return {"started": False, "reason": "disabled"}
            if not import_open(conn, schema, guard):
                return {"started": False, "reason": IMPORT_REFUSED}
        with _lock:
            st = _state(schema)
            if st["running"]:
                return {"started": False, "reason": "already running"}
            t = _naive(_clock(None, clock)())
            with read_only_transaction(db_url) as conn:
                due = [p["label"] for p in plan(conn, schema, t, catalog(), store.held_generation(conn, schema))
                       if p["overdue"]]  # fmt: skip
            if not due:
                return {"started": False, "reason": "nothing overdue"}
            st.update(running=True, queue=due, current=None, done=[])

        def work() -> None:
            time.sleep(delay_s)
            try:
                if runner is not None:
                    runner()
                else:
                    run_due(db_url, schema, source="app", deps=deps, clock=clock, guard=guard)
            except Exception:
                log.exception("catch-up failed")
            finally:
                with _lock:
                    _state(schema)["running"] = False

        threading.Thread(target=work, daemon=True, name="pz-catch-up").start()
        return {"started": True, "queue": due}
    except Exception as e:
        log.exception("could not start catch-up")
        return {"started": False, "reason": f"{type(e).__name__}"}


def app_start(db_url: str, schema: str, *, deps: JobDeps | None = None) -> dict[str, Any]:
    """The app's start (the old lifespan's two guarded steps): ``recover_on_start``, then ``start_catch_up``. Never
    raises; only with ``PZ_CATCHUP`` on (it is off under tests)."""
    if not env_enabled():
        return {"started": False, "reason": "disabled"}
    try:
        recover_on_start(db_url, schema)
    except IntakeClosedError:
        return {"started": False, "reason": IMPORT_REFUSED}
    except Exception:
        log.exception("background job recovery failed")
    return start_catch_up(db_url, schema, deps=deps)
