"""Review 032c acceptance tests (plan revisions 2 and 3, Codex H-321 / H-323 / H-325) against the hosted project, in
throw-away ``pz_itest_*`` scratch schemas, with invented names only. No live network and no model: the jobs are FAKE
(a counted, non-idempotent effect under the job's own lock), or the real ones with fixture fetchers / transports.

* two runners at once never run the same job; the second records ``skipped``; ``--lock-status`` reports the holder;
* revision 2: A pauses inside J1, ONLY its lock connection is terminated: the lock is gone at once, B recovers J1
  (interrupted) and runs J1 and J2; A resumes: its completion is refused and it dispatches nothing more;
* revision 3, with a COUNTED effect: the commit between plan and dispatch (counter 1, B records "skipped — already
  ran"); the reverse order (counter 1, nothing recorded by A); concurrent same-date snapshot writers (one line);
* every ported job once through the runner with fixture transports; the six unported jobs never run (b);
* the live refusal (a): before the import marker nothing runs and nothing is written, by any entry point;
* the runner overlay: a new run under one source updates that entry while the imported other-source entry stays, in
  the System health diagnostics and in ``GET /api/catchup``; the routes' answers.

The counted results are printed (``-s``) for the review.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import secrets
import socket
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from itertools import count
from typing import Any
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from projectzero.api.app import create_app
from projectzero.core import net
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.core.occurrence import ALREADY_RAN, AlreadyRan
from projectzero.dealflow.intake.postgres import IntakeClosedError, ensure_intake_open
from projectzero.events.registry import NEW_DEFAULTS
from projectzero.health import core as health_core
from projectzero.jobs import __main__ as cli
from projectzero.jobs import runner, store, writers
from projectzero.jobs.catalog import REAL, Job, JobContext, JobDeps
from projectzero.jobs.ported import NOT_PORTED, PORTED
from projectzero.ops.db_check import _scratch_sql
from projectzero.ops.parity_events_scan import RecordedFetcher
from projectzero.ops.parity_news import FEED_URLS, FixtureTransport, fixture_resolver, item, rfc, rss
from projectzero.ops.parity_validation import _fingerprint

pytestmark = pytest.mark.hosted
NOW = datetime(2026, 11, 13, 8, 0, tzinfo=UTC)  # 09:00 in Berlin
WAIT_S = 120.0
LD = {
    "id": "s-ld",
    "name": "Invented LD Source",
    "kind": "jsonld",
    "url": "https://ld.example.com/",
    "city": "Karlsruhe",
}


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture(autouse=True)
def only_the_database(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No live network: the system resolver answers only the database's host."""
    db_host = urlsplit(settings.db_url).hostname or ""
    real = socket.getaddrinfo

    def guarded(host: Any, *a: Any, **k: Any) -> Any:
        if host != db_host:
            raise AssertionError(f"the network was used: {host}")
        return real(host, *a, **k)

    monkeypatch.setattr(socket, "getaddrinfo", guarded)
    monkeypatch.setattr(net, "default_resolver", lambda host: (_ for _ in ()).throw(AssertionError(host)))
    yield


@pytest.fixture
def make(settings: Settings) -> Iterator[Callable[[], str]]:
    """A fresh scratch schema (every migration; no import marker is needed: only ``pz`` is guarded)."""
    made: list[str] = []

    def build() -> str:
        name = f"pz_itest_{secrets.token_hex(4)}"
        with connect(settings.db_url, autocommit=True) as admin:
            admin.execute(_scratch_sql(name).encode())
            admin.execute(f"create table {name}.itest_counter (id bigserial primary key, job text, who text)".encode())
            admin.execute(f"create table {name}.itest_keyed (key text primary key, who text)".encode())
        made.append(name)
        return name

    yield build
    with connect(settings.db_url, autocommit=True) as admin:
        for name in made:
            admin.execute(f"drop schema if exists {name} cascade".encode())


def q(settings: Settings, schema: str, query: str, params: Any = ()) -> list[tuple[Any, ...]]:
    with transaction(settings.db_url) as conn:
        return conn.execute(query.replace("{s}", schema).encode(), params).fetchall()


def wait_for(cond: Callable[[], bool], what: str) -> None:
    t0 = time.monotonic()
    while not cond():
        if time.monotonic() - t0 > WAIT_S:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(0.05)


def _wait(barrier: threading.Barrier) -> None:
    barrier.wait()


def _pause(inside: threading.Event, go: threading.Event) -> Callable[[], None]:
    """A hook that signals it is inside the job, then waits to be released."""

    def hook() -> None:
        inside.set()
        go.wait(WAIT_S)

    return hook


def _hook(ctx: JobContext, name: str) -> None:
    fn = ctx.deps.extra.get(name)
    if fn is not None:
        fn()


def counted(jid: str) -> Job:
    """A fake job with a COUNTED, NON-idempotent effect (one counter row per execution), its own lock (a
    transaction-scoped advisory lock held to commit) and a ``last()`` the effect updates (the job's counter rows)."""

    def occurrence(conn: Any, schema: str) -> Any:
        return conn.execute(f"select count(*) from {schema}.itest_counter where job = %s".encode(), (jid,)).fetchone()

    def run(ctx: JobContext) -> str:
        _hook(ctx, f"{jid}:before_lock")
        with transaction(ctx.db_url) as conn:
            conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"{ctx.schema}.itest.{jid}",))
            if not ctx.still_due(conn):
                raise AlreadyRan
            conn.execute(
                f"insert into {ctx.schema}.itest_counter (job, who) values (%s, %s)".encode(), (jid, ctx.source)
            )
            _hook(ctx, f"{jid}:in_effect")  # paused here: the job lock is held, the effect not yet committed
        return "1 new"

    return Job(jid, f"Invented {jid}", 24.0, run, occurrence)


def keyed(jid: str) -> Job:
    """Revision 2's fake: idempotent by key (one row per job and date), no job lock."""

    def run(ctx: JobContext) -> str:
        _hook(ctx, f"{jid}:in_effect")
        with transaction(ctx.db_url) as conn:
            conn.execute(f"insert into {ctx.schema}.itest_keyed (key, who) values (%s, %s) on conflict do nothing".encode(),
                         (f"{jid}:2026-11-13", ctx.source))  # fmt: skip
        return "1 new"

    return Job(jid, f"Invented {jid}", 24.0, run, lambda conn, schema: None)


def lock_backend(settings: Settings, schema: str) -> int | None:
    rows = q(settings, schema, "select pid from pg_locks where locktype = 'advisory' and granted and objsubid = 1 and "
             "((classid::bigint << 32) | objid::bigint) = hashtext(%s)::bigint", (store.lock_key(schema),))  # fmt: skip
    return int(rows[0][0]) if rows else None


def cut_lock_connection(settings: Settings, schema: str) -> None:
    """Terminate ONLY the session holding the scheduler lock (the worker itself keeps running)."""
    pid = lock_backend(settings, schema)
    assert pid is not None
    with connect(settings.db_url, autocommit=True) as admin:
        admin.execute("select pg_terminate_backend(%s)", (pid,))
    wait_for(lambda: lock_backend(settings, schema) is None, "the lock to die with its connection")


def waiting_on(settings: Settings, schema: str, key: str) -> bool:
    rows = q(settings, schema, "select count(*) from pg_locks where locktype = 'advisory' and not granted and "
             "((classid::bigint << 32) | objid::bigint) = hashtext(%s)::bigint", (key,))  # fmt: skip
    return bool(rows[0][0])


def in_thread(fn: Callable[[], Any]) -> tuple[threading.Thread, dict[str, Any]]:
    out: dict[str, Any] = {}

    def work() -> None:
        try:
            out["result"] = fn()
        except BaseException as exc:  # surfaced by the test
            out["error"] = exc

    t = threading.Thread(target=work, daemon=True)
    t.start()
    return t, out


def history(settings: Settings, schema: str) -> list[tuple[Any, ...]]:
    return q(settings, schema, "select job, detail->>'source', detail->>'outcome', detail->>'note', outcome, "
             "finished_at is not null from {s}.job_runs order by id")  # fmt: skip


def record(settings: Settings, schema: str, jid: str) -> dict[str, Any]:
    rows = q(settings, schema, "select detail from {s}.job_state where job = %s", (jid,))
    return dict(rows[0][0]) if rows else {}


def counter(settings: Settings, schema: str) -> list[tuple[Any, ...]]:
    return q(settings, schema, "select job, who from {s}.itest_counter order by id")


def run(settings: Settings, schema: str, source: str, jobs: list[Job], **extra: Callable[[], None]) -> list[Any]:
    return runner.run_due(settings.db_url, schema, source=source, now=NOW, jobs=jobs, deps=JobDeps(extra=extra))


def lock_status_cli(settings: Settings, schema: str) -> tuple[int, dict[str, Any]]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(["--lock-status"], settings=Settings(db_url=settings.db_url, schema=schema), now=NOW)
    lines = buf.getvalue().splitlines()
    assert len(lines) == 1
    return code, json.loads(lines[0])


# ------------------------------------------------------------------ two runners, the lock, --lock-status
def test_two_runners_at_once_never_run_the_same_job_and_the_second_records_skipped(
    settings: Settings, make: Callable[[], str]
) -> None:
    schema = make()
    j1 = counted("solo")
    inside, go = threading.Event(), threading.Event()
    a, a_out = in_thread(lambda: run(settings, schema, "background", [j1], **{"solo:in_effect": _pause(inside, go)}))
    assert inside.wait(WAIT_S)
    code, held = lock_status_cli(settings, schema)
    assert code == cli.LOCK_HELD_EXIT and held["held"] is True and held["source"] == "background"
    assert list(held) == ["held", "source", "pid", "since"]
    with transaction(settings.db_url) as conn:
        before = _fingerprint(conn, schema)
    lock_status_cli(settings, schema)  # never takes the lock, never writes
    with transaction(settings.db_url) as conn:
        assert _fingerprint(conn, schema) == before
    second = run(settings, schema, "app", [j1])
    assert len(second) == 1 and second[0]["outcome"] == "skipped" and second[0]["job"] == "*"
    assert "another run is in progress (background, pid " in second[0]["note"]
    go.set()
    a.join(WAIT_S)
    assert "error" not in a_out and [r["outcome"] for r in a_out["result"]] == ["completed"]
    assert counter(settings, schema) == [("solo", "background")]  # executed exactly once
    runners = q(
        settings, schema, "select source, record->>'outcome', record->>'note' from {s}.job_runner order by source"
    )
    assert [(r[0], r[1]) for r in runners] == [("app", "skipped"), ("background", "ok")]
    assert run(settings, schema, "app", [j1]) == []  # and nothing is due afterwards
    assert lock_status_cli(settings, schema) == (0, {"held": False, "source": None, "pid": None, "since": None})


# ------------------------------------------------------------------ revision 2: the lock connection dies
def test_a_dead_lock_connection_frees_the_lock_and_the_stale_worker_completes_nothing(
    settings: Settings, make: Callable[[], str]
) -> None:
    schema = make()
    j1, j2 = keyed("j1"), keyed("j2")
    inside, go = threading.Event(), threading.Event()
    a, a_out = in_thread(lambda: run(settings, schema, "background", [j1, j2], **{"j1:in_effect": _pause(inside, go)}))
    assert inside.wait(WAIT_S)
    g_a = record(settings, schema, "j1")["generation"]
    cut_lock_connection(settings, schema)  # ONLY A's lock connection
    assert runner.lock_status(settings.db_url, schema, now=NOW) == {"held": False}  # no stale lock, ever
    fixed = runner.recover_on_start(settings.db_url, schema, now=NOW)  # B's start
    rec = record(settings, schema, "j1")
    assert fixed == ["j1"] and rec["state"] == "interrupted" and rec["note"] == runner.INTERRUPTED_NOTE
    b = run(settings, schema, "app", [j1, j2])
    assert [(r["job"], r["outcome"]) for r in b] == [("j1", "completed"), ("j2", "completed")]
    go.set()  # A resumes: its effect is a no-op by key, its completion is refused, it dispatches nothing more
    a.join(WAIT_S)
    assert "error" not in a_out and a_out["result"] == []
    rows = q(settings, schema, "select key, who from {s}.itest_keyed order by key")
    assert rows == [("j1:2026-11-13", "app"), ("j2:2026-11-13", "app")]  # j1's effect exists once; A never ran j2
    h = history(settings, schema)
    assert [(r[0], r[1]) for r in h] == [("j1", "app"), ("j2", "app")]  # no history line from A after the cut
    for jid in ("j1", "j2"):
        r = record(settings, schema, jid)
        assert r["source"] == "app" and r["state"] == "ok" and r["generation"] > g_a  # B's state stands
    print(
        f"\n[revision 2] generations A={g_a} B={record(settings, schema, 'j1')['generation']} keyed rows={rows} history={h}"
    )


# ------------------------------------------------------------------ revision 3: a COUNTED effect, both orders
def test_the_commit_between_plan_and_dispatch_runs_the_effect_once(settings: Settings, make: Callable[[], str]) -> None:
    schema = make()
    j1 = counted("j1")
    inside, go = threading.Event(), threading.Event()
    a, a_out = in_thread(lambda: run(settings, schema, "background", [j1], **{"j1:in_effect": _pause(inside, go)}))
    assert inside.wait(WAIT_S)  # A holds the job lock mid-effect (uncommitted)
    cut_lock_connection(settings, schema)
    at_lock = threading.Event()
    b, b_out = in_thread(lambda: run(settings, schema, "app", [j1], **{"j1:before_lock": at_lock.set}))
    assert at_lock.wait(WAIT_S)  # B planned (the old last()), claimed and reached the job lock
    wait_for(lambda: waiting_on(settings, schema, f"{schema}.itest.j1"), "B to wait on the job lock")
    go.set()  # A commits (counter 1, last() advanced) and releases the job lock
    a.join(WAIT_S)
    b.join(WAIT_S)
    assert "error" not in a_out and "error" not in b_out
    rows, h = counter(settings, schema), history(settings, schema)
    print(f"\n[revision 3, order 1: commit between plan and dispatch] counter={len(rows)} rows={rows} history={h} "
          f"A results={a_out['result']} B results={[(r['job'], r['outcome'], r['note']) for r in b_out['result']]}")  # fmt: skip
    assert len(rows) == 1 and rows == [("j1", "background")]
    assert a_out["result"] == []  # A's completion was refused (a larger generation took over)
    assert [(r["outcome"], r["note"]) for r in b_out["result"]] == [("skipped", ALREADY_RAN)]
    rec = record(settings, schema, "j1")
    assert rec["source"] == "app" and rec["outcome"] == "skipped" and rec["note"] == ALREADY_RAN
    assert h == [("j1", "app", "skipped", ALREADY_RAN, "ok", True)]


def test_a_stale_worker_reaching_the_job_after_the_replacement_finished_does_nothing(
    settings: Settings, make: Callable[[], str]
) -> None:
    schema = make()
    j1, j2 = counted("j1"), counted("j2")
    claimed, go = threading.Event(), threading.Event()
    a, a_out = in_thread(
        lambda: run(settings, schema, "background", [j1, j2], **{"j1:before_lock": _pause(claimed, go)})
    )
    assert claimed.wait(WAIT_S)  # A claimed j1 and pauses before the job lock
    cut_lock_connection(settings, schema)
    b = run(settings, schema, "app", [j1, j2])  # B takes over, runs j1 (counter 1) and j2, and finishes
    assert [(r["job"], r["outcome"]) for r in b] == [("j1", "completed"), ("j2", "completed")]
    go.set()  # A resumes: still_due fails (generation and last()) under the job lock; its completion is refused
    a.join(WAIT_S)
    assert "error" not in a_out
    rows, h = counter(settings, schema), history(settings, schema)
    print(f"\n[revision 3, order 2: stale A after B finished] counter={len(rows)} rows={rows} history={h} "
          f"A results={a_out['result']}")  # fmt: skip
    assert rows == [("j1", "app"), ("j2", "app")]  # each effect exactly once, none by A
    assert a_out["result"] == [] and all(r[1] == "app" for r in h)  # nothing recorded by A
    assert [(r[0], r[2]) for r in h] == [("j1", "completed"), ("j2", "completed")]
    runners = dict(q(settings, schema, "select source, record->>'outcome' from {s}.job_runner"))
    assert runners == {"background": "running", "app": "ok"}  # A's final runner record was refused too


def test_concurrent_same_date_snapshot_writers_write_exactly_one_line(
    settings: Settings, make: Callable[[], str]
) -> None:
    schema = make()
    barrier = threading.Barrier(2, timeout=WAIT_S)
    results: list[bool] = []

    def writer() -> None:
        results.append(writers.record_snapshot(settings.db_url, schema, NOW, before_lock=lambda: _wait(barrier)))

    threads = [threading.Thread(target=writer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(WAIT_S)
    lines = q(settings, schema, "select line from {s}.validation_log where log = 'snapshots'")
    print(f"\n[revision 3, concurrent snapshot writers] results={sorted(results)} snapshot lines={len(lines)}")
    assert sorted(results) == [False, True] and len(lines) == 1
    assert json.loads(lines[0][0])["date"] == "2026-11-13"
    barrier2 = threading.Barrier(2, timeout=WAIT_S)
    weekly: list[bool] = []

    def week() -> None:
        weekly.append(writers.record_weekly(settings.db_url, schema, NOW, before_lock=lambda: _wait(barrier2)))

    threads = [threading.Thread(target=week) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(WAIT_S)
    assert sorted(weekly) == [False, True]
    assert q(settings, schema, "select count(*) from {s}.news_logs where log = 'weekly'") == [(1,)]


# ------------------------------------------------------------------ the real jobs, once, with fixtures
FEEDS = {FEED_URLS["Sifted"]: {"body": rss([item("Invented Birch Photonics raises €6M seed",
                                                 "https://sifted.eu/articles/invented-birch", rfc(1),
                                                 "The Lyon team builds lidar chips.")])}}  # fmt: skip


def deps() -> JobDeps:
    page = ('<script type="application/ld+json">{"@type": "Event", "name": "Invented Robotics Night", "startDate": '
            '"2026-12-04", "location": {"@type": "Place", "name": "Hall A", "address": {"addressLocality": "Karlsruhe"}}}</script>')  # fmt: skip
    hexes = count(100)
    return JobDeps(events_fetcher=RecordedFetcher({LD["url"]: {"text": page}}), news_transport=FixtureTransport(FEEDS),
                   news_resolver=fixture_resolver, new_hex=lambda: f"{next(hexes):016x}")  # fmt: skip


def test_every_ported_job_runs_once_through_the_runner_and_the_unported_never_run(
    settings: Settings, make: Callable[[], str]
) -> None:
    schema = make()
    with transaction(settings.db_url) as conn:
        conn.execute(f"insert into {schema}.documents (key, body) values ('event_sources.json', %s)".encode(),
                     (Jsonb({"sources": [LD], "offered_defaults": NEW_DEFAULTS}),))  # fmt: skip
    unported = sorted({j["id"] for j in health_core.active_jobs()} - PORTED)
    assert len(unported) == 6 and not set(unported) & set(REAL)
    assert runner.run_due(settings.db_url, schema, source="cli", now=NOW, only=unported, deps=deps()) == []  # (b)
    rows = runner.run_due(settings.db_url, schema, source="cli", now=NOW, deps=deps())
    print("\n[ported jobs] " + " | ".join(f"{r['job']}: [{r['outcome']}] {r['note']}" for r in rows))
    assert [r["job"] for r in rows] == ["event_scan", "validation_snapshot", "news_refresh", "news_weekly_review",
                                        "news_source_review"]  # fmt: skip
    assert all(r["ok"] for r in rows), rows
    assert not [r for r in rows if r["outcome"] == "skipped"], rows  # an earlier job of the run is no "already ran"
    marks = q(settings, schema, "select count(*) from {s}.news_logs where log = 'run_notes' and line like %s",
              ('%"source_review": true%',))  # fmt: skip
    assert marks == [(1,)]
    assert q(settings, schema, "select count(*) from {s}.validation_log where log = 'snapshots'") == [(1,)]
    # the weekly evaluation writes the first history line (the old "none yet" rule), the monthly review its own
    for log, n in (("runs", 1), ("weekly", 1), ("source_history", 2)):
        assert q(settings, schema, "select count(*) from {s}.news_logs where log = %s", (log,)) == [(n,)], log
    assert q(
        settings, schema, "select body->>'scan_time' is not null from {s}.documents where key = 'event_health.json'"
    ) == [(True,)]
    assert sorted(r[0] for r in q(settings, schema, "select job from {s}.job_state")) == sorted(PORTED)
    assert runner.run_due(settings.db_url, schema, source="cli", now=NOW, deps=deps()) == []  # nothing due twice
    plan = runner.status(settings.db_url, schema, now=NOW)["plan"]
    assert {p["id"] for p in plan if p.get("availability") == NOT_PORTED} == set(unported)
    assert not [p for p in plan if p["id"] in unported and p["overdue"]]
    h = q(settings, schema, "select job, started_at <= finished_at from {s}.job_runs order by id")
    assert [r[1] for r in h] == [True] * 5  # the real start and finish of every new history row


# ------------------------------------------------------------------ (a) the live refusal
def test_before_the_import_marker_nothing_runs_and_nothing_is_written(
    settings: Settings, make: Callable[[], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = make()

    def guard(conn: Any, s: str) -> None:  # the production guard, pointed at this scratch name (no marker here)
        ensure_intake_open(conn, s, live=s)

    with transaction(settings.db_url) as conn:
        before = _fingerprint(conn, schema)
    j1 = counted("j1")
    with pytest.raises(IntakeClosedError):
        runner.run_due(settings.db_url, schema, source="app", now=NOW, jobs=[j1], guard=guard)
    with pytest.raises(IntakeClosedError):
        runner.recover_on_start(settings.db_url, schema, now=NOW, guard=guard)
    holder = connect(settings.db_url, autocommit=True)  # another runner holds the lock: still no skipped record
    try:
        assert store.try_lock(holder, schema)
        with pytest.raises(IntakeClosedError):
            runner.run_due(settings.db_url, schema, source="app", now=NOW, jobs=[j1], guard=guard)
        assert lock_status_cli(settings, schema)[0] == cli.LOCK_HELD_EXIT  # --lock-status reads, never writes
    finally:
        holder.close()
    monkeypatch.setenv("PZ_CATCHUP", "1")
    assert runner.start_catch_up(settings.db_url, schema, guard=guard)["reason"] == runner.IMPORT_REFUSED
    assert runner.start_manual(settings.db_url, schema, None, guard=guard) == {
        "started": False,
        "reason": runner.IMPORT_REFUSED,
    }
    for argv in (["--background"], ["--run-due"]):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(
                argv, settings=Settings(db_url=settings.db_url, schema=schema), now=NOW, jobs=[j1], guard=guard
            )
        assert code == 3 and buf.getvalue().startswith("REFUSED: "), argv
    with transaction(settings.db_url) as conn:
        assert _fingerprint(conn, schema) == before  # nothing written anywhere: no lease, record, runner row
    assert counter(settings, schema) == []


# ------------------------------------------------------------------ the overlay and the routes
def _archive(settings: Settings, schema: str, path: str, text: str) -> None:
    raw = text.encode("utf-8")
    with transaction(settings.db_url) as conn:
        conn.execute(f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values (%s, %s, %s, %s, %s)".encode(),
                     (path, hashlib.sha256(raw).hexdigest(), len(raw), raw, Jsonb(json.loads(text))))  # fmt: skip


def test_a_new_run_overlays_its_source_and_the_imported_other_source_stays(
    settings: Settings, make: Callable[[], str]
) -> None:
    schema = make()
    imported = ('{"background": {"at": "2026-11-12T22:00:00", "outcome": "ok", "pid": 4242, "ran": 1, "failed": 0}, '
                '"app": {"at": "2026-11-12T08:00:00", "outcome": "skipped", "note": "skipped — another run is in progress"}}')  # fmt: skip
    _archive(settings, schema, "schedule/runner.json", imported)
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = lambda: NOW
    with TestClient(app, base_url="http://127.0.0.1:8177") as client:
        before = client.get("/api/catchup").json()
        assert before["runners"] == json.loads(imported)
        run(settings, schema, "app", [counted("j1")])  # the first new run, as the app
        diag = client.get("/api/system_health").json()["job_runner"]["runners"]
        status = client.get("/api/catchup").json()
    for runners in (diag, status["runners"]):
        assert list(runners) == ["background", "app"]  # in its place
        assert runners["background"] == json.loads(imported)["background"]  # unchanged
        assert (
            runners["app"]["outcome"] == "ok"
            and runners["app"]["ran"] == 1
            and runners["app"]["at"] == "2026-11-13T09:00:00"
        )
        assert list(runners["app"])[:3] == ["at", "outcome", "note"]  # the imported entry updated (the old merge)
    run(settings, schema, "cli", [counted("j1")])  # a source written for the first time is listed after them
    assert list(store_runners(settings, schema)) == ["background", "app", "cli"]
    assert list(status) == ["running", "queue", "current", "done", "started", "finished", "enabled", "plan", "lock",
                            "runners"]  # fmt: skip
    assert status["lock"] == {"held": False} and status["enabled"] is False  # PZ_CATCHUP=0 under tests


def store_runners(settings: Settings, schema: str) -> dict[str, Any]:
    with transaction(settings.db_url) as conn:
        return store.runner_records(conn, schema)


def test_the_catchup_routes_answer_the_old_bodies(settings: Settings, make: Callable[[], str]) -> None:
    schema = make()
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = lambda: NOW
    app.state.jobs_deps = deps()
    with TestClient(app, base_url="http://127.0.0.1:8177") as client:
        r = client.post("/api/catchup_run", json={"only": ["validation_snapshot"]})
        assert r.json() == {"started": True}
        wait_for(lambda: not runner.running(schema), "the manual run to finish")
        status = client.get("/api/catchup").json()
        assert [d["job"] for d in status["done"]] == ["validation_snapshot"] and status["running"] is False
        assert status["runners"]["app"]["outcome"] == "ok"
        with runner._lock:
            runner._state(schema)["running"] = True  # a run of this app is in progress
        try:
            assert client.post("/api/catchup_run", json={}).json() == {"started": False, "reason": "already running"}
        finally:
            with runner._lock:
                runner._state(schema)["running"] = False
        assert client.post("/api/catchup_run", content=b"[1]").status_code == 400
        health = client.get("/api/system_health").json()
        assert {j["id"] for j in health["jobs"] if j.get("availability") == NOT_PORTED} == set(
            {j["id"] for j in health_core.active_jobs()} - PORTED
        )
        assert health["job_runner"]["lock"] == {"held": False}


# ------------------------------------------------------------------ after the build (Claude): two OS processes, and a stale runner record
def test_a_second_os_process_finds_the_lock_held_and_records_skipped(
    settings: Settings, make: Callable[[], str]
) -> None:
    """The plan's two runners as two PROCESSES: while this process holds the lock inside a job, the CLI in a separate
    process (``python -m projectzero.jobs --run-due``) skips with exit 0, records its own ``skipped`` runner record
    and runs nothing."""
    import os
    import subprocess
    import sys

    schema = make()
    j1 = counted("solo")
    inside, go = threading.Event(), threading.Event()
    a, a_out = in_thread(lambda: run(settings, schema, "background", [j1], **{"solo:in_effect": _pause(inside, go)}))
    assert inside.wait(WAIT_S)
    try:
        env = {**os.environ, "PZ_SCHEMA": schema, "PZ_CATCHUP": "1"}
        proc = subprocess.run([sys.executable, "-m", "projectzero.jobs", "--run-due"], env=env, capture_output=True,
                              text=True, timeout=300)  # fmt: skip
    finally:
        go.set()
        a.join(WAIT_S)
    assert proc.returncode == 0, proc.stderr[-2000:]
    rows = q(settings, schema, "select source, record->>'outcome' from {s}.job_runner order by source")
    assert ("cli", "skipped") in [(r[0], r[1]) for r in rows]
    assert counter(settings, schema) == [("solo", "background")]  # the job ran once, in this process only
    assert "error" not in a_out


def test_recovery_marks_a_stale_runner_record_interrupted(settings: Settings, make: Callable[[], str]) -> None:
    """A runner whose lock died left its own record ``running`` (any source): the next recovery, holding the lock
    with a newer generation, marks it ``interrupted`` so the diagnostics never show a run that will never finish.
    The imported (archived) records are not touched."""
    schema = make()
    with transaction(settings.db_url) as conn:
        store.write_runner(conn, schema, "cli", {"at": "2026-11-13T08:00:00", "outcome": "running", "pid": 1})
    runner.recover_on_start(settings.db_url, schema, source="app")
    rows = q(settings, schema, "select source, record->>'outcome', record->>'note' from {s}.job_runner order by source")
    cli_row = next(r for r in rows if r[0] == "cli")
    assert cli_row[1] == "interrupted" and cli_row[2] == runner.INTERRUPTED_NOTE


HOLDER = """
import sys
from projectzero.core.db import connect
from projectzero.jobs import store
conn = connect(sys.argv[1], autocommit=True)
assert store.try_lock(conn, sys.argv[2])
print("held", flush=True)
sys.stdin.readline()
"""


def test_the_manual_route_answers_busy_while_another_process_holds_the_lock(
    settings: Settings, make: Callable[[], str]
) -> None:
    """Codex H-327: the route takes the scheduler lock BEFORE it answers. While a separate OS process holds the lock,
    ``POST /api/catchup_run`` answers ``{started: false, reason: "already running"}``, dispatches nothing (no job record,
    no history row) and writes the old busy record (``app: skipped``)."""
    import subprocess
    import sys

    schema = make()
    holder = subprocess.Popen([sys.executable, "-c", HOLDER, settings.db_url, schema], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, text=True)  # fmt: skip
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        jobs_before = q(settings, schema, "select job, detail::text from {s}.job_state order by job")
        runs_before = q(settings, schema, "select count(*) from {s}.job_runs")
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            r = client.post("/api/catchup_run", json={})
        assert r.status_code == 200 and r.json() == {"started": False, "reason": "already running"}
        assert q(settings, schema, "select job, detail::text from {s}.job_state order by job") == jobs_before
        assert q(settings, schema, "select count(*) from {s}.job_runs") == runs_before  # zero dispatches
        rows = q(settings, schema, "select source, record->>'outcome', record->>'note' from {s}.job_runner")
        app_row = next(r for r in rows if r[0] == "app")
        assert app_row[1] == "skipped" and app_row[2].startswith("skipped — another run is in progress")
        assert not runner.running(schema)  # the in-process flag is cleared again
    finally:
        if holder.stdin is not None:
            holder.stdin.write("\n")
            holder.stdin.flush()
        holder.wait(timeout=60)
    with TestClient(create_app(Settings(db_url=settings.db_url, schema=schema)), base_url="http://127.0.0.1:8177") as c:
        assert c.post("/api/catchup_run", json={"only": ["no-such-job"]}).json() == {"started": True}  # free again
