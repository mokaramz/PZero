"""Review 037b acceptance tests for the WATCH checks (the two sensors, Check now, the job and the news bridge), against
the hosted project in throw-away ``pz_itest_*`` schemas imported by the PRODUCTION importer. Invented names only. No
model, and no live network: every page is the fixture transport's recorded bytes behind the fixture resolver, and the
system resolver answers only the database's host.

* one check at a time: a second check (Check now, a direct run, the job) gets the busy answer while one runs;
* a crash between a page's fetch and its commit leaves no snapshot, no trigger and no check record; the next run fires
  them once;
* revision 2: a URL removed during a paused fetch that would fire ``pilot`` writes nothing (its baseline, a row or the
  archive, the log and its check history untouched; nothing in Today) and fires against the old baseline once re-added;
  a company leaving the watched set during the fetch (its candidate rejected, no active target) writes nothing for its
  pages, nor for its re-hits;
* the archived lines' dedupe keys block a re-fire (037a's note);
* revision 4's table, exactly: four budget-limited / fitting runs, their skipped counts (answer and note), visit
  orders (distinct predicates in the trigger log) and resume points, run 4 equal to the OLD ``run_checks`` on the same
  bytes (the oracle);
* a private host is a failed check; nothing is fetched or written before the import (the news bridge included);
* the job runs once under the 032c rules (and gives the busy note while a check runs);
* the news bridge fires each news trigger once, inside the news run's own transaction.
"""

from __future__ import annotations

import copy
import json
import socket
import threading
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from itertools import count
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from projectzero.api.app import create_app
from projectzero.core import net
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.dealflow.intake.postgres import IntakeClosedError, ensure_intake_open
from projectzero.jobs import runner
from projectzero.jobs.catalog import JobDeps
from projectzero.network.view import BERLIN
from projectzero.news import runs as news_runs
from projectzero.news import store as news_store
from projectzero.ops import parity_watch_sensors as pws
from projectzero.ops.parity_news import FEED_URLS, item, rfc, rss
from projectzero.ops.parity_news import FixtureTransport as FeedTransport
from projectzero.ops.parity_news import fixture_resolver as feed_resolver
from projectzero.ops.parity_ranking import OLD_REPO
from projectzero.ops.parity_validation import _fingerprint
from projectzero.ops.scratch_import import drop_schema, files_of, import_world
from projectzero.watch import log as watch_log
from projectzero.watch import run as watch_run
from projectzero.watch import sensors, writes
from projectzero.watch import targets as watch_targets

pytestmark = pytest.mark.hosted
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=BERLIN)
OLD_PY = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"


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
def world(settings: Settings) -> Iterator[Callable[..., str]]:
    made: list[str] = []

    def build(docs: dict[str, Any] | None = None) -> str:
        name = import_world(settings.db_url, copy.deepcopy(docs or pws.world_docs()))
        made.append(name)
        return name

    yield build
    for name in made:
        drop_schema(settings.db_url, name)


def client_of(settings: Settings, schema: str, transport: Any, *, resolver: Any = pws.fixture_resolver,
              now: datetime = NOW, budget: float | None = None, hooks: watch_run.Hooks | None = None) -> TestClient:  # fmt: skip
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = lambda: now
    app.state.watch_transport, app.state.watch_resolver = transport, resolver
    if budget is not None:
        app.state.watch_budget_s = budget
    if hooks is not None:
        app.state.watch_hooks = hooks
    return TestClient(app, base_url="http://127.0.0.1:8177", raise_server_exceptions=False)


def q(settings: Settings, schema: str, query: str, params: Any = ()) -> list[tuple[Any, ...]]:
    with transaction(settings.db_url) as conn:
        return conn.execute(query.replace("{s}", schema).encode(), params).fetchall()


def fingerprint(settings: Settings, schema: str) -> dict[str, Any]:
    with transaction(settings.db_url) as conn:
        return _fingerprint(conn, schema)


def state(settings: Settings, schema: str) -> dict[str, Any]:
    with transaction(settings.db_url) as conn:
        return {"log": watch_log.log_text(conn, schema).splitlines(),
                "targets": watch_targets.effective_targets(conn, schema),
                "snapshots": pws.snapshots_of(conn, schema),
                "rows": [str(r[0]) for r in conn.execute(f"select id from {schema}.watch_page_snapshots order by id".encode()).fetchall()],
                "resume": watch_run.resume_point(conn, schema)}  # fmt: skip


def triggers(settings: Settings, schema: str) -> list[dict[str, Any]]:
    """The trigger rows written since the import, in ``seq`` order."""
    rows = q(settings, schema, "select line::text from {s}.watch_events where kind = 'trigger' order by seq")
    return [json.loads(r[0]) for r in rows]


def check(settings: Settings, schema: str, transport: Any, pages: dict[str, Any], **kw: Any) -> dict[str, Any]:
    transport.responses = dict(pages)
    with client_of(settings, schema, transport, **kw) as client:
        r = client.post("/api/watch_check", json={})
        assert r.status_code == 200, r.text
        out: dict[str, Any] = r.json()
        return out


def watch_actions(settings: Settings, schema: str) -> list[dict[str, Any]]:
    with client_of(settings, schema, pws.PageTransport()) as client:
        return [a for a in client.get("/api/today").json()["actions"] if a["type"] == "WATCH_TRIGGER"]


BASE = pws.script()[1]["pages"]  # every page as in the parity's first full check
PILOT = {**BASE, pws.COR: {"body": pws.page(*pws.COR_BASE, pws.COR_PILOT)}}


# ------------------------------------------------------------------ (a) one check at a time
def test_two_checks_at_once_the_second_gets_the_busy_answer(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()
    transport = pws.PageTransport(BASE)
    entered, release = threading.Event(), threading.Event()
    transport.pause[pws.COR] = (entered, release)
    result: dict[str, Any] = {}

    def first() -> None:
        with client_of(settings, schema, transport) as client:
            result["r"] = client.post("/api/watch_check", json={})

    t = threading.Thread(target=first)
    t.start()
    try:
        assert entered.wait(30)
        with client_of(settings, schema, pws.PageTransport(BASE)) as other:  # Check now in another request
            r = other.post("/api/watch_check", json={"name": "Dunmore Sensors"})
            assert (r.status_code, r.json()) == (409, {"ok": False, "error": "A WATCH check is already running."})
        with pytest.raises(watch_run.CheckBusy, match="already running"):  # another session's run
            watch_run.run_checks(
                settings.db_url, schema, transport=pws.PageTransport(BASE), resolver=pws.fixture_resolver
            )
        rows = runner.run_due(settings.db_url, schema, source="cli", now=NOW.replace(tzinfo=None), only=["watch_checks"],
                              deps=JobDeps(watch_transport=pws.PageTransport(BASE), watch_resolver=pws.fixture_resolver))  # fmt: skip
        assert [(r["job"], r["note"]) for r in rows] == [
            ("watch_checks", "skipped — A WATCH check is already running.")
        ]
    finally:
        release.set()
        t.join(60)
    assert result["r"].status_code == 200 and len(result["r"].json()["pages"]) == 5  # the first check completed


def test_the_check_lock_is_derived_from_the_schema_and_a_holder_makes_the_route_busy(
    settings: Settings, world: Callable[..., str]
) -> None:
    schema = world()
    assert watch_run.LOCK == "{schema}.watch.check" and "pz." not in watch_run.LOCK
    holder = connect(settings.db_url, autocommit=True)
    transport = pws.PageTransport(BASE)
    try:
        holder.execute("select pg_advisory_lock(hashtext(%s))", (watch_run.LOCK.format(schema=schema),))
        with client_of(settings, schema, transport) as client:
            r = client.post("/api/watch_check", json={})
        assert r.status_code == 409 and r.json()["error"] == watch_run.BUSY
        assert transport.asked == [] and triggers(settings, schema) == []
    finally:
        holder.close()
    assert len(check(settings, schema, transport, BASE)["pages"]) == 5  # released with its session


# ------------------------------------------------------------------ (b) a page's write is atomic
def test_a_crash_between_fetch_and_commit_leaves_nothing_and_the_next_run_fires_once(
    settings: Settings, world: Callable[..., str]
) -> None:
    schema = world()
    transport = pws.PageTransport()
    check(settings, schema, transport, BASE)  # the baselines
    before = state(settings, schema)
    fired_before = triggers(settings, schema)

    def crash(key: str, url: str) -> None:
        if url == pws.COR:
            raise RuntimeError("an invented crash before the commit")

    transport.responses = dict(PILOT)
    with client_of(settings, schema, transport, hooks=watch_run.Hooks(before_commit=crash)) as client:
        assert client.post("/api/watch_check", json={}).status_code == 500
    after = state(settings, schema)
    assert after["snapshots"] == before["snapshots"] and after["log"] == before["log"]  # no snapshot, no trigger
    assert after["targets"] == before["targets"]  # no check record
    assert triggers(settings, schema) == fired_before
    out = check(settings, schema, transport, PILOT)
    pilot = [
        t for t in triggers(settings, schema) if t["predicate"] == "pilot" and t["entity_key"] == "corvane robotics"
    ]
    assert out["fired"] == 1 and len(pilot) == 1 and pilot[0]["evidence"] == pws.COR_PILOT
    assert check(settings, schema, transport, PILOT)["fired"] == 0  # once


# ------------------------------------------------------------------ revision 2: eligibility at commit
def _paused_check(settings: Settings, schema: str, transport: pws.PageTransport, url: str,
                  during: Callable[[], None]) -> dict[str, Any]:  # fmt: skip
    entered, release = threading.Event(), threading.Event()
    transport.pause[url] = (entered, release)
    result: dict[str, Any] = {}

    def run() -> None:
        with client_of(settings, schema, transport) as client:
            result["r"] = client.post("/api/watch_check", json={})

    t = threading.Thread(target=run)
    t.start()
    try:
        assert entered.wait(30)
        during()
    finally:
        release.set()
        t.join(60)
        transport.pause.pop(url, None)
    assert result["r"].status_code == 200, result["r"].text
    out: dict[str, Any] = result["r"].json()
    return out


def _save(settings: Settings, schema: str, body: dict[str, Any]) -> None:
    with client_of(settings, schema, pws.PageTransport()) as client:
        r = client.post("/api/watch_target", json=body)
        assert r.status_code == 200, r.text


def test_a_url_removed_during_the_fetch_writes_nothing_and_fires_later_against_the_old_baseline(
    settings: Settings, world: Callable[..., str]
) -> None:
    docs = pws.world_docs()  # without the legacy trigger line (no url, no source): Today's WATCH section reads it whole
    kept = [x for x in docs["watch/triggers.jsonl"].splitlines() if "wt-legacy" not in x]
    docs["watch/triggers.jsonl"] = "".join(f"{x}\n" for x in kept)
    schema = world(docs)
    transport = pws.PageTransport()
    check(settings, schema, transport, BASE)  # the row baselines
    before, today_before = state(settings, schema), watch_actions(settings, schema)
    assert [a for a in today_before if "Corvane" in a["title"]]  # the section reads (the re-hits are open)
    keep = {"name": "Corvane Robotics GmbH", "urls": [pws.COR_JOBS], "candidate_id": "wsn-cor"}
    transport.responses = dict(PILOT)
    out = _paused_check(settings, schema, transport, pws.COR, lambda: _save(settings, schema, keep))
    assert pws.COR not in [p["url"] for p in out["pages"]] and out["fired"] == 0
    after = state(settings, schema)
    name = watch_run.snapshot_name("corvane robotics", pws.COR)
    assert after["snapshots"][name] == before["snapshots"][name]  # the old baseline (a row) unchanged
    assert after["log"] == before["log"]  # no pilot trigger
    checks = after["targets"]["corvane robotics"]["checks"]
    assert checks[pws.COR] == before["targets"]["corvane robotics"]["checks"][pws.COR]  # its check history untouched
    assert checks[pws.COR_JOBS]["last_state"] == "unchanged"  # the page still listed was checked as usual
    assert after["targets"]["corvane robotics"]["urls"] == [pws.COR_JOBS]
    assert watch_actions(settings, schema) == today_before  # nothing in Today
    _save(settings, schema, {**keep, "urls": [pws.COR, pws.COR_JOBS]})  # re-added
    again = check(settings, schema, transport, PILOT)
    row = next(p for p in again["pages"] if p["url"] == pws.COR)
    assert row["state"] == "changed" and [t["predicate"] for t in row["fired"]] == ["pilot"]  # against the old baseline


def test_a_url_removed_during_the_fetch_keeps_an_archived_baseline(
    settings: Settings, world: Callable[..., str]
) -> None:
    schema = world()
    transport = pws.PageTransport()
    funding = "Garrow Marine raises an invented seed round led by an invented fund"
    pages = {**BASE, pws.GAR: {"body": pws.page(*pws.GAR_ARCHIVED, funding)}}
    name = watch_run.snapshot_name("garrow marine", pws.GAR)
    before = state(settings, schema)
    assert name in before["snapshots"] and f"{name[:-5]}" not in before["rows"]  # the archive only
    transport.responses = dict(pages)
    _paused_check(settings, schema, transport, pws.GAR,
                  lambda: _save(settings, schema, {"name": "Garrow Marine", "urls": []}))  # fmt: skip
    after = state(settings, schema)
    assert name[:-5] not in after["rows"] and after["snapshots"][name] == pws.GAR_ARCHIVED  # still the archive
    assert not [t for t in triggers(settings, schema) if t["entity_key"] == "garrow marine"]
    assert after["targets"]["garrow marine"]["checks"] == before["targets"]["garrow marine"]["checks"]
    _save(settings, schema, {"name": "Garrow Marine", "urls": [pws.GAR]})
    again = check(settings, schema, transport, pages)
    row = next(p for p in again["pages"] if p["url"] == pws.GAR)
    assert row["state"] == "changed" and [t["predicate"] for t in row["fired"]] == ["funding"]


def _reject(settings: Settings, schema: str, cid: str) -> None:
    with client_of(settings, schema, pws.PageTransport()) as client:
        r = client.post(f"/api/deal-flow/candidates/{cid}/decision", json={"status": "rejected"})
        assert r.status_code == 200, r.text


def test_a_company_leaving_the_watched_set_during_the_fetch_writes_nothing(
    settings: Settings, world: Callable[..., str]
) -> None:
    schema = world()
    transport = pws.PageTransport()
    transport.responses = dict(BASE)
    before = state(settings, schema)
    out = _paused_check(settings, schema, transport, pws.ELS, lambda: _reject(settings, schema, "wsn-els"))
    assert pws.ELS not in [p["url"] for p in out["pages"]]  # Elstree: an inactive target, its candidate rejected
    after = state(settings, schema)
    assert watch_run.snapshot_name("elstree analytics", pws.ELS) not in after["snapshots"]
    assert after["targets"]["elstree analytics"] == before["targets"]["elstree analytics"]  # no check record
    assert not [t for t in triggers(settings, schema) if t["entity_key"] == "elstree analytics"]


def test_a_company_leaving_before_its_rehits_fires_none(settings: Settings, world: Callable[..., str]) -> None:
    docs = pws.world_docs()
    docs["watch/targets.json"]["targets"]["corvane robotics"]["active"] = False  # watched only as a candidate
    schema = world(docs)
    transport = pws.PageTransport(BASE)
    with client_of(settings, schema, transport,
                   hooks=watch_run.Hooks(after_read=lambda: _reject(settings, schema, "wsn-cor"))) as client:  # fmt: skip
        out = client.post("/api/watch_check", json={}).json()
    assert not [t for t in triggers(settings, schema) if t["entity_key"] == "corvane robotics"]  # no re-hit
    assert not [p for p in out["pages"] if p["url"] in (pws.COR, pws.COR_JOBS)]
    assert state(settings, schema)["targets"]["corvane robotics"]["checks"] == {}
    control = world(docs)  # the same world, the candidate still watched: its three re-hits fire
    with client_of(settings, control, pws.PageTransport(BASE)) as client:
        client.post("/api/watch_check", json={})
    assert len([t for t in triggers(settings, control) if t["source_kind"] == "scan_rehit"]) == 3


# ------------------------------------------------------------------ 037a's note: the archived keys
def test_the_archived_dedupe_keys_block_a_re_fire(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()
    transport = pws.PageTransport()
    out = check(settings, schema, transport, BASE)
    gar = next(p for p in out["pages"] if p["url"] == pws.GAR)
    assert gar["state"] == "changed" and [t["predicate"] for t in gar["fired"]] == ["team_growth"]  # not the pilot
    archived = next(e for e in watch_log.parse_text(pws.archived_log()) if e.get("predicate") == "pilot")
    with transaction(settings.db_url) as conn:
        writes.begin(conn, schema)
        assert writes.fire(conn, schema, [watch_log.line({**archived, "first_observed": "2026-11-13T12:00:00"})]) == []
    assert archived["dedupe_key"] not in {t["dedupe_key"] for t in triggers(settings, schema)}


# ------------------------------------------------------------------ revision 4: the resume point
A, B, C = (
    "https://kestrel.invented.example/news",
    "https://kestrel.invented.example/jobs",
    "https://lumen-yard.invented.example/",
)
LINES = {  # page -> run -> the new line (each a DISTINCT predicate)
    A: {3: "Invented Kestrel Works launches an invented inspection drone", 4: "Invented Kestrel Works posts an invented preprint on arxiv"},
    B: {2: "Invented Kestrel Works starts a pilot with an invented utility", 3: "Invented Kestrel Works partners with an invented lab",
        4: "Invented Kestrel Works is now ISO 9001 certified"},
    C: {2: "Invented Lumen Yard signed a contract with an invented retailer", 3: "Invented Lumen Yard files an invented patent application",
        4: "Invented Lumen Yard presents at an invented demo day"},
}  # fmt: skip
EXPECT = {A: {3: "launch", 4: "paper"}, B: {2: "pilot", 3: "partnership", 4: "certification"},
          C: {2: "customer", 3: "patent", 4: "demo_day"}}  # fmt: skip
BASE_LINES = {A: ["Invented Kestrel Works news", "Invented inspection robots for invented bridges."],
              B: ["Invented Kestrel Works jobs", "Work with us in an invented town."],
              C: ["Invented Lumen Yard", "Invented yard robotics for invented ports."]}  # fmt: skip


BUDGET = 10.0  # the budget-limited runs: room for the reads, the re-hits and two page writes; A outlasts it


def resume_docs() -> dict[str, Any]:
    cand = pws._c("rsm-kes", "Invented Kestrel Works", also_seen=[])
    return {
        "inbox.json": {"candidates": [cand], "last_run": "2026-10-20 08:00:00", "reprocess_v": 3},
        "watch/targets.json": {"targets": {
            "invented kestrel works": {"name": "Invented Kestrel Works", "added_at": "2026-10-02T09:00:00", "checks": {},
                                       "urls": [A, B], "candidate_id": "rsm-kes", "active": True, "updated_at": "2026-10-02T09:00:00"},
            "invented lumen yard": {"name": "Invented Lumen Yard", "added_at": "2026-10-03T09:00:00", "checks": {}, "urls": [C],
                                    "candidate_id": "", "active": True, "updated_at": "2026-10-03T09:00:00"}}},
    }  # fmt: skip


def run_pages(run: int, *, slow_a: bool) -> dict[str, Any]:
    """Each page: its base lines plus every new line up to ``run`` (so each run brings ONE fresh line per page)."""
    out: dict[str, Any] = {}
    for url in (A, B, C):
        lines = BASE_LINES[url] + [LINES[url][r] for r in sorted(LINES[url]) if r <= run]
        out[url] = {"body": pws.page(*lines)}
    if slow_a:
        out[A] = {"slow": 120}
    return out


def test_revision_4_the_resume_point_table(settings: Settings, world: Callable[..., str]) -> None:
    for url, runs_ in LINES.items():  # every new line fires exactly its predicate
        assert {r: sensors.classify(x) for r, x in runs_.items()} == EXPECT[url]
    schema = world(resume_docs())
    transport = pws.PageTransport()
    clocks = (NOW + timedelta(minutes=i) for i in count())

    def go(pages: dict[str, Any], budget: float) -> tuple[dict[str, Any], list[str], list[str]]:
        transport.responses, transport.asked = pages, []
        seen = len(triggers(settings, schema))
        at = next(clocks)
        out = watch_run.run_checks(settings.db_url, schema, clock=lambda: at, transport=transport,
                                   resolver=pws.fixture_resolver, budget=budget, scheduled=True)  # fmt: skip
        return out, [q["url"] for q in transport.asked], [t["predicate"] for t in triggers(settings, schema)[seen:]]

    go(run_pages(1, slow_a=False), 60)  # the baselines (run 0)
    go({**run_pages(1, slow_a=False), A: {"error": "invented reset"}}, 60)  # A fails once: its streak is 1
    a_record = state(settings, schema)["targets"]["invented kestrel works"]["checks"][A]
    assert a_record["failures_in_row"] == 1
    observed = []
    # run 1: starts at A (no resume point); A cut at the deadline; B, C not reached
    out, asked, fired = go(run_pages(2, slow_a=True), BUDGET)
    s1 = state(settings, schema)
    observed.append({"run": 1, "asked": asked, "fired": fired, "skipped": out["skipped"], "resume": s1["resume"],
                     "note": watch_run.note(out)})  # fmt: skip
    assert asked == [A] and fired == [] and out["skipped"] == 3 and out["pages"] == []
    assert (
        watch_run.note(out) == "0 new trigger(s) · 0 page(s) checked · 0 failure(s) · 3 page(s) left for the next run"
    )
    assert s1["resume"] == ("invented kestrel works", B)
    assert s1["targets"]["invented kestrel works"]["checks"][A] == a_record  # A's record and streak unchanged
    # run 2: starts at B; B, C checked (in that order), then A cut
    out, asked, fired = go(run_pages(2, slow_a=True), BUDGET)
    s2 = state(settings, schema)
    observed.append({"run": 2, "asked": asked, "fired": fired, "skipped": out["skipped"], "resume": s2["resume"],
                     "note": watch_run.note(out)})  # fmt: skip
    assert asked == [B, C, A] and fired == ["pilot", "customer"] and out["skipped"] == 1
    assert (
        watch_run.note(out) == "2 new trigger(s) · 2 page(s) checked · 0 failure(s) · 1 page(s) left for the next run"
    )
    assert s2["resume"] == ("invented kestrel works", B)  # A's successor
    assert s2["targets"]["invented kestrel works"]["checks"][A] == a_record
    # run 3: A now quick; starts at B; B, C, A (the ROTATED order), everything fits
    out, asked, fired = go(run_pages(3, slow_a=False), 60)
    s3 = state(settings, schema)
    observed.append({"run": 3, "asked": asked, "fired": fired, "skipped": out["skipped"], "resume": s3["resume"],
                     "note": watch_run.note(out)})  # fmt: skip
    assert asked == [B, C, A] and fired == ["partnership", "patent", "launch"] and out["skipped"] == 0
    assert watch_run.note(out) == "3 new trigger(s) · 3 page(s) checked · 0 failure(s)" and s3["resume"] is None
    assert s3["targets"]["invented kestrel works"]["checks"][A]["failures_in_row"] == 0
    # run 4: no resume point; A, B, C (the OLD order), equal to the old run_checks on the same bytes
    before4 = state(settings, schema)
    pages4 = run_pages(4, slow_a=False)
    out, asked, fired = go(pages4, 60)
    s4 = state(settings, schema)
    observed.append({"run": 4, "asked": asked, "fired": fired, "skipped": out["skipped"], "resume": s4["resume"],
                     "note": watch_run.note(out)})  # fmt: skip
    assert asked == [A, B, C] and fired == ["paper", "certification", "demo_day"] and out["skipped"] == 0
    assert s4["resume"] is None
    with transaction(settings.db_url) as conn:
        assert watch_run.job_runs(conn, schema) == 6  # every scheduled run finished
    print("[037b-rev4]", json.dumps(observed, ensure_ascii=False))
    if OLD_PY.exists():  # the OLD run_checks over the same state and bytes
        docs = {**resume_docs(), "watch/targets.json": {"targets": before4["targets"]},
                "watch/triggers.jsonl": "\n".join(before4["log"]) + "\n",
                **{f".watch/{k}": v for k, v in before4["snapshots"].items()}}  # fmt: skip
        step = {"clock": (NOW + timedelta(minutes=5)).replace(tzinfo=None).isoformat(), "op": "check", "pages": pages4}
        old = pws.oracle_files(files_of(docs), [step])["steps"][0]
        assert old["fetched"] == [A, B, C]
        old_new = str(old["log"]).splitlines()[len(before4["log"]) :]
        assert [json.loads(x)["predicate"] for x in old_new] == fired
        assert s4["log"][len(before4["log"]) :] == old_new  # byte for byte (the same frozen clock)
        assert old["answer"]["fired"] == out["fired"] and old["answer"]["pages"] == out["pages"]


def test_a_duplicate_url_never_strands_the_page_after_it(settings: Settings, world: Callable[..., str]) -> None:
    """Codex H-391: a stored list ``[A, A, B]`` whose A always exhausts the budget. Run 1 cuts A and resumes at B
    (not at the second A, which the rotation would resolve to the first A again); run 2 reaches B."""
    docs = resume_docs()
    docs["watch/targets.json"]["targets"]["invented kestrel works"]["urls"] = [A, A, B]
    del docs["watch/targets.json"]["targets"]["invented lumen yard"]
    schema = world(docs)
    with transaction(settings.db_url) as conn:  # saved as given (037a): the duplicate stays in the stored list
        assert watch_targets.effective_targets(conn, schema)["invented kestrel works"]["urls"] == [A, A, B]
    transport = pws.PageTransport()
    pages = {A: {"slow": 120}, B: {"body": pws.page(*BASE_LINES[B])}}
    observed = []
    for run_no in (1, 2):
        transport.responses, transport.asked = dict(pages), []
        at = NOW + timedelta(minutes=run_no)
        out = watch_run.run_checks(settings.db_url, schema, clock=lambda at=at: at, transport=transport,
                                   resolver=pws.fixture_resolver, budget=BUDGET, scheduled=True)  # fmt: skip
        s = state(settings, schema)
        observed.append({"run": run_no, "asked": [q["url"] for q in transport.asked], "skipped": out["skipped"],
                         "resume": s["resume"], "checked": [p["url"] for p in out["pages"]],
                         "b_record": s["targets"]["invented kestrel works"]["checks"].get(B)})  # fmt: skip
    print("[037b-H391]", json.dumps(observed, ensure_ascii=False))
    one, two = observed
    assert one["asked"] == [A] and one["skipped"] == 2 and one["resume"] == ("invented kestrel works", B)
    assert one["checked"] == [] and one["b_record"] is None
    assert two["asked"] == [B, A] and two["checked"] == [B] and two["skipped"] == 1
    assert two["b_record"]["last_state"] == "baseline" and two["resume"] == ("invented kestrel works", B)
    assert watch_run.snapshot_name("invented kestrel works", B) in state(settings, schema)["snapshots"]


# ------------------------------------------------------------------ (c) the network rules
def test_a_private_host_is_a_failed_check(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()
    inner = "https://intranet.invented.example/news"
    _save(settings, schema, {"name": "Dunmore Sensors", "urls": [inner], "candidate_id": "wsn-dun"})

    def resolver(host: str) -> list[str]:
        return ["10.0.0.7"] if host == "intranet.invented.example" else [pws.FIXTURE_IP]

    transport = pws.PageTransport()
    out = check(settings, schema, transport, {**BASE, inner: {"body": pws.page("never served")}}, resolver=resolver)
    row = next(p for p in out["pages"] if p["url"] == inner)
    assert row["state"] == "failed" and row["error"].startswith("UnsafeURLError: refused")
    assert "non-public address (10.0.0.7)" in row["error"] and out["failures"] == 1
    assert inner not in [a["url"] for a in transport.asked]  # refused before anything was sent
    record = state(settings, schema)["targets"]["dunmore sensors"]["checks"][inner]
    assert record["failures_in_row"] == 1 and record["last_state"] == "failed" and "last_ok" not in record
    assert watch_run.snapshot_name("dunmore sensors", inner) not in state(settings, schema)["snapshots"]


# ------------------------------------------------------------------ (g) nothing before the import
def test_nothing_is_fetched_or_written_before_the_import(
    settings: Settings, world: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = world()
    with transaction(settings.db_url) as conn:  # the import marker goes: this scratch schema is "before the import"
        conn.execute(sql.SQL("delete from {}.documents where key = 'ops/legacy_import'").format(sql.Identifier(schema)))

    def guarded(conn: psycopg.Connection[Any], s: str, *, live: str = "pz") -> None:
        ensure_intake_open(conn, s, live=s)  # the production guard, pointed at this scratch name

    monkeypatch.setattr(writes, "ensure_intake_open", guarded)
    before = fingerprint(settings, schema)
    transport = pws.PageTransport(BASE)
    with client_of(settings, schema, transport) as client:
        r = client.post("/api/watch_check", json={})
        assert r.status_code == 409 and "legacy import" in r.json()["error"]
    assert transport.asked == []
    with pytest.raises(IntakeClosedError), transaction(settings.db_url) as conn:  # the news bridge's write too
        watch_run.news_bridge(conn, schema, NOW)(pws.news_events())
    assert fingerprint(settings, schema) == before


# ------------------------------------------------------------------ the job (032c)
def test_the_job_runs_once_under_the_runner(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()
    now = datetime(2026, 11, 13, 9, 0)
    deps = JobDeps(watch_transport=pws.PageTransport(BASE), watch_resolver=pws.fixture_resolver)
    rows = runner.run_due(settings.db_url, schema, source="cli", now=now, only=["watch_checks"], deps=deps)
    assert [(r["job"], r["ok"], r["note"]) for r in rows] == [
        ("watch_checks", True, "4 new trigger(s) · 5 page(s) checked · 0 failure(s)")  # 3 re-hits + Garrow's hiring
    ]
    assert runner.run_due(settings.db_url, schema, source="cli", now=now, only=["watch_checks"], deps=deps) == []
    plan = {p["id"]: p for p in runner.status(settings.db_url, schema, now=now)["plan"]}
    assert "availability" not in plan["watch_checks"] and plan["watch_checks"]["overdue"] is False
    with transaction(settings.db_url) as conn:
        assert watch_run.job_runs(conn, schema) == 1
    assert len(triggers(settings, schema)) == 4  # ran once
    later = runner.run_due(settings.db_url, schema, source="cli", now=now + timedelta(days=1, minutes=1),
                           only=["watch_checks"], deps=deps)  # fmt: skip
    assert [(r["job"], r["note"]) for r in later] == [
        ("watch_checks", "0 new trigger(s) · 5 page(s) checked · 0 failure(s)")
    ]


# ------------------------------------------------------------------ scope 6: the news bridge
NEWS_FEEDS = {
    FEED_URLS["Sifted"]: {"body": rss([
        item("Invented Birch Photonics raises €6M seed", "https://sifted.eu/articles/invented-birch", rfc(1),
             "The Lyon team builds lidar chips."),
    ])},
}  # fmt: skip
NEWS_NOW = datetime(2026, 11, 12, 10, 0, tzinfo=BERLIN)


def news_docs() -> dict[str, Any]:
    birch = pws._c("nws-birch", "Invented Birch Photonics", also_seen=[])
    return {"inbox.json": {"candidates": [birch], "last_run": "2026-10-20 08:00:00", "reprocess_v": 3}}


def _news_run(settings: Settings, schema: str, start: int) -> dict[str, Any]:
    hexes = count(start)
    return news_runs.refresh_run(settings.db_url, schema, NEWS_NOW, transport=FeedTransport(NEWS_FEEDS),
                                 resolver=feed_resolver, new_hex=lambda: f"{next(hexes):016x}")  # fmt: skip


def _run_lines(settings: Settings, schema: str) -> list[dict[str, Any]]:
    rows = q(settings, schema, "select line from {s}.news_logs where log = 'runs' order by seq")
    return [json.loads(r[0]) for r in rows]


def test_the_news_bridge_fires_each_trigger_once_in_the_news_runs_transaction(
    settings: Settings, world: Callable[..., str]
) -> None:
    schema = world(news_docs())
    first = _news_run(settings, schema, 100)
    assert first["last"]["watch_triggers"] == 1
    (t,) = triggers(settings, schema)
    assert (t["entity_key"], t["source_kind"], t["predicate"], t["url"]) == (
        "invented birch photonics",
        "news",
        "funding",
        "https://sifted.eu/articles/invented-birch",
    )
    assert t["dedupe_key"] == sensors._sha(
        "invented birch photonics", "news", "https://sifted.eu/articles/invented-birch"
    )
    notes = q(settings, schema, "select line from {s}.news_logs where log = 'run_notes' order by seq")
    assert json.loads(notes[0][0])["deferred"] == []  # the watch bridge is no longer deferred
    second = _news_run(settings, schema, 200)
    assert second["last"]["watch_triggers"] == 0 and len(triggers(settings, schema)) == 1  # once
    assert [r["watch_triggers"] for r in _run_lines(settings, schema)] == [1, 0]


def test_the_news_bridge_commits_or_rolls_back_with_the_news_run(
    settings: Settings, world: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = world(news_docs())
    original = news_store.append_log

    def failing(conn: Any, s: str, log: str, line: str) -> Any:
        if log == "run_notes":  # after the bridge, inside the same write transaction
            raise RuntimeError("an invented failure after the bridge")
        return original(conn, s, log, line)

    monkeypatch.setattr(news_store, "append_log", failing)
    with pytest.raises(RuntimeError, match="after the bridge"):
        _news_run(settings, schema, 100)
    assert triggers(settings, schema) == [] and _run_lines(settings, schema) == []  # rolled back together
    monkeypatch.setattr(news_store, "append_log", original)
    assert _news_run(settings, schema, 300)["last"]["watch_triggers"] == 1 and len(triggers(settings, schema)) == 1
