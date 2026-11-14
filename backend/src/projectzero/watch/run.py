"""The WATCH checks (review 037b): the old ``watch.run_checks(only)`` (``POST /api/watch_check`` and the 24-hour
``watch_checks`` job), in phases so no transaction is open while the network is used.

1. **read** (one short transaction, closed before any fetch): ``ensure_intake_open`` (decision g: nothing is fetched
   or written before the import), the watched set and the effective targets (037a's ``watch.targets``), the resume
   point (``watch_check_state``) and the archived log's dedupe keys.
2. **the re-hit sensor** (no network): per watched company, in the old order, ONE short write transaction under 037a's
   ``<schema>.watch`` lock that re-reads the CURRENT watched set (a company that left it fires nothing) and fires its
   re-hits (the cut ``scan_rehits``). For EVERY company, even for "Check now" on one (decision e, the old quirk).
3. **the pages**, in the old traversal (each watched company in order, each URL of its effective target in order;
   ``only``: that company's), starting AT the resume point and wrapping around (revision 2; "Check now" for one company
   neither starts there nor moves it). Per page:

   * **fetch** (no transaction): ``core/net`` with the old browser headers, the old 20-second timeout, the 8 MB cap,
     at most 5 redirects, verified TLS only (decision c: the old unverified retry is dropped; a private host is refused
     at fetch and is a failed check), and the run's ABSOLUTE monotonic deadline (decision d: 600 s for the job, 120 s
     for Check now). A page the deadline cuts, or one not reached before it, is ``skipped``: no snapshot, no trigger,
     its check record unchanged (its failure streak and baseline kept); it is checked by the next run.
   * **write** (ONE transaction, under the ``<schema>.watch`` lock, revision 2): the company must still be watched and
     the URL still in its CURRENT effective list, else NOTHING is written for the page (its old baseline, the trigger
     log and its check history stay as they were). Otherwise the baseline is resolved AT CHECK TIME (its
     ``watch_page_snapshots`` row, else the archived ``.watch/wt-<id>.json``, else none: a first check records it), the
     cut ``check_page`` classifies the new lines, and the new snapshot, its triggers (``writes.fire``: the archived keys
     and the unique index) and the page's check record (the old ``last_checked`` / ``last_state`` / ``last_ok`` /
     ``failures_in_row`` / ``last_error``) commit together (decision b: the old code saved the snapshot first, so a
     crash in between lost those triggers for good).

4. **the resume point** (a run over every page, the job's or Check now for all): a run that ended at the deadline
   resumes AFTER the last page it reached (a page cut mid-fetch WAS reached: it moves to the end of the next rotation);
   a run that reached every page clears it, so the next run follows the old order.

One check at a time (decision a): a SESSION advisory lock ``<schema>.watch.check`` on a dedicated autocommit connection,
released on every path; a second caller gets ``CheckBusy`` ("A WATCH check is already running."). ``still_due``: the
runner's occurrence check (032c), on the lock's connection right after the lock is taken.

The high-value case refresh (decision f) is case preparation's and is not run; nothing is recorded for it.
"""

from __future__ import annotations

import contextlib
import copy
import json
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.core import net, occurrence
from projectzero.core.db import connect, schema_ident, transaction
from projectzero.dealflow.ranking.names import norm_company
from projectzero.dealflow.scan import parsers
from projectzero.network.view import BERLIN, berlin_now
from projectzero.watch import sensors, writes
from projectzero.watch import targets as watch_targets

LOCK = "{schema}.watch.check"
BUSY = "A WATCH check is already running."
JOB_BUSY_NOTE = "skipped — " + BUSY
JOB_BUDGET_S = 600.0  # decision (d): inside the runner's 900 s
CHECK_NOW_BUDGET_S = 120.0
REQUEST_TIMEOUT_S = 20.0  # the old ``PZ_TIMEOUT``
WRITE_TIMEOUT = "30s"  # one write transaction's lock / statement waits
Clock = Callable[[], datetime]
Page = tuple[str, str]  # (company key, url)
cut: Any = parsers  # the cut old code is untyped (``dealflow/scan/parsers.py``): its ``_uid`` goes through this alias

_STATE = "select resume_key, resume_url from {}.watch_check_state where id"
_SAVE_STATE = (
    "insert into {s}.watch_check_state (id, resume_key, resume_url, job_runs) values (true, %s, %s, %s) "
    "on conflict (id) do update set resume_key = excluded.resume_key, resume_url = excluded.resume_url, "
    "job_runs = {s}.watch_check_state.job_runs + excluded.job_runs, updated_at = now()"
)
_SNAPSHOT = "select lines from {}.watch_page_snapshots where id = %s"
_ARCHIVED_SNAPSHOT = "select parsed from {}.legacy_documents where path = %s"
_SAVE_SNAPSHOT = (
    "insert into {}.watch_page_snapshots (id, entity_key, url, lines) values (%s, %s, %s, %s::jsonb) "
    "on conflict (id) do update set entity_key = excluded.entity_key, url = excluded.url, lines = excluded.lines, "
    "updated_at = now()"
)


class CheckBusy(Exception):
    """Another check holds the one-check-at-a-time lock."""

    def __init__(self) -> None:
        super().__init__(BUSY)


# ------------------------------------------------------------------ pure
def ts_of(now: datetime) -> str:
    """The old ``ledger.now_ts()`` of the run's clock (a naive clock is Berlin wall time)."""
    return writes.now_ts(now if now.tzinfo is not None else now.replace(tzinfo=BERLIN))


def snapshot_name(key: str, url: str) -> str:
    """The old snapshot file name ``wt-<sha1(key|url)[:12]>.json`` (its stem is the row's id)."""
    uid: str = cut._uid(key, url)
    return "wt-" + uid + ".json"


def traversal(watched: Mapping[str, Any], targets: Mapping[str, Any], only: str | None) -> list[Page]:
    """The old order: each watched company (``only``: the one whose key is ``norm_company(only)``), each URL of its
    effective target, in order (an inactive target's URLs included when its company is watched: decision e).

    Each (company key, URL) pair is visited ONCE per run (Codex H-391, declared): a URL listed twice in a company's
    stored list keeps its FIRST position only, so the resume point's successor and the rotation work on unique pages
    (the old ``run_checks`` checked a duplicate twice, the second visit seeing an unchanged page). The stored list is
    never changed (037a saves it as given)."""
    out: list[Page] = []
    for key in watched:
        if only and key != norm_company(only):
            continue
        for url in (targets.get(key) or {}).get("urls") or []:
            if (key, url) not in out:
                out.append((key, url))
    return out


def rotate(pages: list[Page], resume: Page | None) -> list[Page]:
    """The traversal started AT the resume point, wrapping around (revision 2). A resume page no longer listed: its
    company's first page, else the first page."""
    if resume is None or not pages:
        return list(pages)
    same_company = (n for n, p in enumerate(pages) if p[0] == resume[0])
    i = pages.index(resume) if resume in pages else next(same_company, 0)
    return pages[i:] + pages[:i]


def successor(pages: list[Page], page: Page) -> Page:
    """The page after ``page`` in the old (cyclic) order."""
    i = pages.index(page)
    return pages[(i + 1) % len(pages)]


def recorded(record: Mapping[str, Any], url: str, state: str, ok: bool, err: str, ts: str) -> dict[str, Any]:
    """The old per-URL check record, written into a COPY of the company's effective target record."""
    t = copy.deepcopy(dict(record))
    chk = t.setdefault("checks", {}).setdefault(url, {})
    chk["last_checked"] = ts
    chk["last_state"] = state
    if ok:
        chk["last_ok"] = chk["last_checked"]
        chk["failures_in_row"] = 0
    else:
        chk["failures_in_row"] = int(chk.get("failures_in_row") or 0) + 1
        chk["last_error"] = err
    return t


@dataclass
class PageOutcome:
    res: dict[str, Any]  # the old ``check_page`` answer (or the failed one)
    ok: bool
    err: str  # the old ``"Type: msg[:120]"``
    lines: list[str]  # the trigger lines the page fired, in order
    saved: dict[str, list[str]]  # snapshot name -> the page's new lines
    case_refresh: list[Any] = field(default_factory=list)


def check_one(
    key: str,
    w: Mapping[str, Any],
    url: str,
    page: Any,
    *,
    baselines: Mapping[str, Any],
    fired: set[str],
    proposals: Mapping[str, Any],
    ts: str,
    today: date,
) -> PageOutcome:
    """The cut ``check_page`` over the fetched ``page`` (its text, or the exception the fetch raised), as the old
    ``run_checks`` called it: an exception is the failed check (``fired`` is mutated, as before)."""
    ctx = sensors.Context(ts=ts, today=today, fired=fired, proposals=dict(proposals), page=page,
                          baselines=dict(baselines))  # fmt: skip
    with sensors.context(ctx):
        try:
            res: dict[str, Any] = sensors.check_page(key, dict(w), url, fired)
            ok, err = True, ""
        except Exception as e:  # a failing page never stops the others
            res, ok, err = {"url": url, "state": "failed", "fired": []}, False, f"{type(e).__name__}: {str(e)[:120]}"
    return PageOutcome(res, ok, err, list(ctx.lines), dict(ctx.saved), list(ctx.case_refresh))


@dataclass
class RehitOutcome:
    rows: list[dict[str, Any]]  # the fired rows, in order
    lines: list[str]  # their lines
    case_refresh: list[Any] = field(default_factory=list)


def rehits_of(
    key: str, w: Mapping[str, Any], *, fired: set[str], proposals: Mapping[str, Any], ts: str, today: date
) -> RehitOutcome:
    """The cut ``scan_rehits`` for ONE company (``fired`` is mutated, as before)."""
    ctx = sensors.Context(ts=ts, today=today, watched={key: dict(w)}, fired=fired, proposals=dict(proposals))
    with sensors.context(ctx):
        rows: list[dict[str, Any]] = sensors.scan_rehits()
    return RehitOutcome(rows, list(ctx.lines), list(ctx.case_refresh))


def bridge_lines(
    events: Mapping[str, Any],
    watched: Mapping[str, Any],
    *,
    fired: set[str],
    proposals: Mapping[str, Any],
    ts: str,
    today: date,
) -> tuple[int, list[str]]:
    """The cut news bridge (the old ``news._watch_bridge``) over the news run's events: (its count, its lines)."""
    ctx = sensors.Context(ts=ts, today=today, watched=copy.deepcopy(dict(watched)), fired=fired,
                          proposals=dict(proposals), news_events=dict(events))  # fmt: skip
    with sensors.context(ctx):
        n: int = sensors._watch_bridge()
    return n, list(ctx.lines)


def kept(rows: list[dict[str, Any]], appended: list[str]) -> list[dict[str, Any]]:
    """The fired rows whose lines were actually appended (a row the unique index refused is not new)."""
    keys = {json.loads(x)["dedupe_key"] for x in appended}
    return [r for r in rows if r["dedupe_key"] in keys]


def note(result: Mapping[str, Any]) -> str:
    """The old ``_run_watch`` note, plus the pages left for the next run (only when some were)."""
    out = f"{result['fired']} new trigger(s) · {len(result['pages'])} page(s) checked · {result['failures']} failure(s)"
    if result.get("skipped"):
        out += f" · {result['skipped']} page(s) left for the next run"
    return out


# ------------------------------------------------------------------ the database
@dataclass(frozen=True)
class Current:
    watched: dict[str, dict[str, Any]]
    targets: dict[str, Any]
    proposals: dict[str, Any]


def current(conn: psycopg.Connection[Any], schema: str) -> Current:
    """The CURRENT watched set, effective targets and proposals (037a's readers), on the caller's transaction."""
    candidates, proposals = watch_targets.watch_candidates(conn, schema)
    targets = watch_targets.effective_targets(conn, schema)
    return Current(watch_targets.watched(candidates, targets), targets, proposals)


def resume_point(conn: psycopg.Connection[Any], schema: str) -> Page | None:
    row = conn.execute(sql.SQL(_STATE).format(schema_ident(schema))).fetchone()
    return (str(row[0]), str(row[1])) if row is not None and row[0] is not None else None


def save_state(conn: psycopg.Connection[Any], schema: str, resume: Page | None, *, job_run: bool) -> None:
    conn.execute(
        sql.SQL(_SAVE_STATE).format(s=schema_ident(schema)),
        (resume[0] if resume else None, resume[1] if resume else None, 1 if job_run else 0),
    )


def job_runs(conn: psycopg.Connection[Any], schema: str) -> int:
    """The finished scheduled checks (the runner's occurrence of ``watch_checks``)."""
    row = conn.execute(
        sql.SQL("select job_runs from {}.watch_check_state where id").format(schema_ident(schema))
    ).fetchone()
    return int(row[0]) if row is not None else 0


def baseline(conn: psycopg.Connection[Any], schema: str, name: str) -> list[Any] | None:
    """A page's baseline AT CHECK TIME: its row, else the archived ``.watch/<name>`` (a JSON list), else none."""
    s = schema_ident(schema)
    row = conn.execute(sql.SQL(_SNAPSHOT).format(s), (name.removesuffix(".json"),)).fetchone()
    if row is not None:
        return list(row[0])
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL(_ARCHIVED_SNAPSHOT).format(s), (f".watch/{name}",))
        doc = cur.fetchone()
    return list(doc["parsed"]) if doc is not None and isinstance(doc["parsed"], list) else None


def save_snapshot(conn: psycopg.Connection[Any], schema: str, name: str, key: str, url: str, lines: list[str]) -> None:
    conn.execute(
        sql.SQL(_SAVE_SNAPSHOT).format(schema_ident(schema)),
        (name.removesuffix(".json"), key, url, json.dumps(lines, ensure_ascii=False)),
    )


def take_lock(db_url: str, schema: str) -> psycopg.Connection[Any]:
    """The check lock on a dedicated autocommit SESSION; ``CheckBusy`` when another holds it."""
    conn = connect(db_url, autocommit=True)
    row = conn.execute("select pg_try_advisory_lock(hashtext(%s))", (LOCK.format(schema=schema),)).fetchone()
    if not (row and row[0]):
        conn.close()
        raise CheckBusy
    return conn


def release_lock(conn: psycopg.Connection[Any], schema: str) -> None:
    try:
        with contextlib.suppress(Exception):
            conn.execute("select pg_advisory_unlock(hashtext(%s))", (LOCK.format(schema=schema),))
    finally:
        conn.close()


@contextlib.contextmanager
def _write(conn: psycopg.Connection[Any], schema: str) -> Iterator[psycopg.Connection[Any]]:
    """ONE write transaction on the run's write session: bounded lock and statement waits, the write boundary and
    the watch lock first."""
    with conn.transaction():
        conn.execute(sql.SQL("set local lock_timeout = {}").format(sql.Literal(WRITE_TIMEOUT)))
        conn.execute(sql.SQL("set local statement_timeout = {}").format(sql.Literal(WRITE_TIMEOUT)))
        writes.begin(conn, schema)
        yield conn


def fetch_page(
    url: str, deadline: float, transport: net.Transport | None, resolver: net.Resolver | None
) -> tuple[Any, bool]:
    """(the page text or the exception, cut by the deadline?) through ``core/net`` (decision c)."""
    try:
        r = net.fetch(url, headers=net.BROWSER_HEADERS, timeout=REQUEST_TIMEOUT_S, deadline=deadline,
                      transport=transport, resolver=resolver)  # fmt: skip
        return r.text(), False
    except Exception as e:
        cut = time.monotonic() >= deadline or (isinstance(e, net.FetchError) and "deadline" in str(e))
        return e, cut


@dataclass
class Hooks:
    """Test seams: ``after_read()`` after phase 1 (before the re-hits); ``after_fetch(key, url)`` between a page's
    fetch and its write; ``before_commit(key, url)`` inside the page's write transaction, after everything was
    written."""

    after_read: Callable[[], None] | None = None
    after_fetch: Callable[[str, str], None] | None = None
    before_commit: Callable[[str, str], None] | None = None


def run_checks(
    db_url: str,
    schema: str,
    *,
    only: str | None = None,
    clock: Clock | None = None,
    transport: net.Transport | None = None,
    resolver: net.Resolver | None = None,
    budget: float = JOB_BUDGET_S,
    scheduled: bool = False,
    still_due: occurrence.StillDue | None = None,
    hooks: Hooks | None = None,
) -> dict[str, Any]:
    """One check; returns ``{fired, pages, failures, skipped}`` (the old answer's three keys, plus ``skipped``).
    Raises ``CheckBusy`` while another check runs, ``IntakeClosedError`` before the import."""
    now = clock or (lambda: datetime.now(BERLIN))
    hk = hooks or Hooks()
    held = take_lock(db_url, schema)
    try:
        occurrence.check(still_due, held)
        deadline = time.monotonic() + max(0.0, float(budget))
        with transaction(db_url) as conn:  # phase 1, closed before any fetch
            writes.guard(conn, schema)
            first = current(conn, schema)
            resume = resume_point(conn, schema)
            archived = writes.archived_keys(conn, schema)
        everything = only is None
        pages_all = traversal(first.watched, first.targets, only)
        order = rotate(pages_all, resume) if everything else pages_all
        if hk.after_read is not None:
            hk.after_read()
        rehits: list[dict[str, Any]] = []
        out: dict[str, Any] = {"fired": 0, "pages": [], "failures": 0, "skipped": 0}
        last: Page | None = None
        with connect(db_url, autocommit=True) as wconn:
            for key in first.watched:  # phase 2: every company's re-hits (decision e), each in its own transaction
                with _write(wconn, schema):
                    cur = current(wconn, schema)
                    w = cur.watched.get(key)
                    if w is None:
                        continue  # it left the watched set: it fires nothing
                    at = now()
                    r = rehits_of(key, w, fired=writes.fired_keys(wconn, schema, archived), proposals=cur.proposals,
                                  ts=ts_of(at), today=berlin_now(at).date())  # fmt: skip
                    rehits += kept(r.rows, writes.fire(wconn, schema, r.lines, archived))
            for i, (key, url) in enumerate(order):  # phase 3: the pages
                if time.monotonic() >= deadline:
                    out["skipped"] += len(order) - i  # not reached
                    break
                page, cut = fetch_page(url, deadline, transport, resolver)
                last = (key, url)
                if cut:
                    out["skipped"] += len(order) - i  # cut at the deadline: it and the rest are left
                    break
                if hk.after_fetch is not None:
                    hk.after_fetch(key, url)
                entry = _write_page(wconn, schema, key, url, page, archived, now, hk)
                if entry is None:
                    continue  # no longer eligible: nothing was written
                out["pages"].append(entry)
                if entry["state"] == "failed":
                    out["failures"] += 1
        if everything:  # phase 4: the resume point (Check now for one company never moves it)
            nxt = None if not out["skipped"] else successor(pages_all, last) if last else (order[0] if order else None)
            with transaction(db_url) as conn:
                writes.guard(conn, schema)
                save_state(conn, schema, nxt, job_run=scheduled)
        out["fired"] = len(rehits) + sum(len(p["fired"]) for p in out["pages"])
        return out
    finally:
        release_lock(held, schema)


def news_bridge(conn: psycopg.Connection[Any], schema: str, now: datetime) -> Callable[[dict[str, Any]], int]:
    """The news refresh's watch bridge (review 037b, scope 6) in the news run's OWN write transaction (``conn``, under
    the News lock): a savepoint under the watch lock, the CURRENT watched set, and the old bridge's triggers through
    ``writes.fire``. Answers how many it appended (the old ``watch_triggers``); a failure rolls back the savepoint
    only, and the run counts 0 (``refresh.apply``)."""

    def bridge(events: dict[str, Any]) -> int:
        with conn.transaction():  # a savepoint: a failure never aborts the news run's own writes
            writes.begin(conn, schema)
            cur = current(conn, schema)
            archived = writes.archived_keys(conn, schema)
            _n, lines = bridge_lines(events, cur.watched, fired=writes.fired_keys(conn, schema, archived),
                                     proposals=cur.proposals, ts=ts_of(now), today=berlin_now(now).date())  # fmt: skip
            return len(writes.fire(conn, schema, lines, archived))

    return bridge


def _write_page(
    conn: psycopg.Connection[Any],
    schema: str,
    key: str,
    url: str,
    page: Any,
    archived: set[str],
    now: Clock,
    hk: Hooks,
) -> dict[str, Any] | None:
    """ONE page's write transaction (revision 2); ``None``: the page lost its eligibility, nothing was written."""
    with _write(conn, schema):
        cur = current(conn, schema)
        w = cur.watched.get(key)
        record = cur.targets.get(key)
        if w is None or not isinstance(record, dict) or url not in (record.get("urls") or []):
            return None
        name = snapshot_name(key, url)
        found = baseline(conn, schema, name)
        at = now()
        ts = ts_of(at)
        o = check_one(key, w, url, page, baselines={name: found} if found is not None else {},
                      fired=writes.fired_keys(conn, schema, archived), proposals=cur.proposals, ts=ts,
                      today=berlin_now(at).date())  # fmt: skip
        for snap, lines in o.saved.items():
            save_snapshot(conn, schema, snap, key, url, lines)
        appended = writes.fire(conn, schema, o.lines, archived)
        res = {**o.res, "fired": kept(list(o.res.get("fired") or []), appended)}
        watch_targets.save_record(conn, schema, key, recorded(record, url, res["state"], o.ok, o.err, ts))
        if hk.before_commit is not None:
            hk.before_commit(key, url)
        return {"entity": w["name"], **res, "error": o.err}
