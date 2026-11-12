"""Review 028c acceptance tests (plan revision 2, Codex H-257 / H-259) against the hosted project, in throw-away scratch
schemas, with invented names only. No live network: every feed is answered by the fixture transport, and the system
resolver refuses every host except the database's.

* a run commits its rows (the new story, the run line, the documents) and the readers show them even though OLDER
  archives exist: the refresh status (``last``), the stories and the Sources view;
* a backcast committed WHILE the run fetches is kept: the run re-reads under the News lock, so the stored event has
  both the operator's signal and the run's merged source, with both history rows in order;
* one run at a time (409 for a second refresh or evaluation while the run lock is held; the status shows it running);
* a run whose write phase cannot get the News lock before its deadline is a 503 that wrote nothing, and the next run
  succeeds;
* the standalone evaluation stores the source state and metrics, read back by the Sources view.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import socket
from collections.abc import Iterator
from itertools import count, pairwise
from typing import Any
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from projectzero.api.app import create_app
from projectzero.core import net
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.news import runs
from projectzero.news import store as news_store
from projectzero.ops.db_check import _scratch_sql
from projectzero.ops.parity_founder_calls import utc_instant
from projectzero.ops.parity_news import FEED_URLS, FixtureTransport, day, ev, fixture_resolver, item, rfc, rss, src

pytestmark = pytest.mark.hosted
NOW = utc_instant("2026-11-12T10:00:00")
ALDER = ev("nw-alder", "Invented Alder Robotics", "Invented Alder Robotics raises €4M seed", "funding", day(3),
           "MEDIUM", rnd="seed", amount=4.0,
           sources=[src("Tech.eu", "alder-t", day(3), "Invented Alder Robotics raises €4M seed")])  # fmt: skip
OLD_RUN = {"run_id": "news-20261101-070000-aaaa", "at": "2026-11-01T07:00:00", "status": "ok", "items": 10}


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


def _archive(conn: Any, schema: str, path: str, text: str) -> None:
    raw = text.encode("utf-8")
    conn.execute(f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values "
                 "(%s, %s, %s, %s, %s::jsonb)".encode(),
                 (path, hashlib.sha256(raw).hexdigest(), len(raw), raw, text if path.endswith(".json") else None))  # fmt: skip


@pytest.fixture
def make(settings: Settings) -> Iterator[Any]:
    made: list[str] = []

    def build() -> tuple[TestClient, str]:
        name = f"pz_itest_{secrets.token_hex(4)}"
        with connect(settings.db_url, autocommit=True) as admin:
            admin.execute(re.sub(r"\bpz\b", name, _scratch_sql("pz")).encode())
        made.append(name)
        doc = {"events": {"nw-alder": ALDER}, "seeded": ["nw-case-robco-unicorn-2026-10"]}
        with transaction(settings.db_url) as conn:  # an existing installation with OLDER archives
            _archive(conn, name, "news/events.json", json.dumps(doc, indent=1))
            _archive(conn, name, "news/runs.jsonl", json.dumps(OLD_RUN, sort_keys=True) + "\n")
            _archive(conn, name, "news/source_metrics.json", json.dumps({"at": "2026-11-01T07:00:00", "windows": {}}))
            conn.execute(f"select {name}.backfill_news(), {name}.backfill_news_files()".encode())
        app = create_app(Settings(db_url=settings.db_url, schema=name))
        app.state.clock = lambda: NOW
        hexes = count()
        app.state.new_hex = lambda: f"{next(hexes):016x}"
        app.state.news_transport = FixtureTransport(FEEDS)
        app.state.news_resolver = fixture_resolver
        return TestClient(app, base_url="http://127.0.0.1:8177", raise_server_exceptions=False), name

    yield build
    for name in made:
        with connect(settings.db_url, autocommit=True) as admin:
            admin.execute(f"drop schema if exists {name} cascade".encode())


FEEDS = {
    FEED_URLS["Sifted"]: {"body": rss([
        item("Invented Alder Robotics raises €4M seed round", "https://sifted.eu/articles/invented-alder", rfc(2),
             "The Munich team builds robot arms."),  # merges into nw-alder (same company, type, within 10 days)
        item("Invented Birch Photonics raises €6M seed", "https://sifted.eu/articles/invented-birch", rfc(1),
             "The Lyon team builds lidar chips."),  # a new story
    ])},
}  # fmt: skip


def _run(settings: Settings, schema: str, **kw: Any) -> dict[str, Any]:
    hexes = count(100)
    return runs.refresh_run(settings.db_url, schema, NOW, transport=FixtureTransport(FEEDS), resolver=fixture_resolver,
                            new_hex=lambda: f"{next(hexes):016x}", **kw)  # fmt: skip


def _history(settings: Settings, schema: str, event_id: str) -> list[str]:
    with transaction(settings.db_url) as conn:
        rows = conn.execute(f"select action from {schema}.news_event_history where event_id = %s order by id".encode(),
                            (event_id,)).fetchall()  # fmt: skip
    return [r[0] for r in rows]


def test_a_run_commits_and_every_reader_shows_it_over_older_archives(settings: Settings, make: Any) -> None:
    c, schema = make()
    assert c.get("/api/news/refresh_status").json()["last"]["run_id"] == OLD_RUN["run_id"]
    r = c.post("/api/news/refresh")
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["started"] is True and answer["job"]["running"] is False
    status = c.get("/api/news/refresh_status").json()
    assert status["last"]["run_id"] == answer["run_id"] != OLD_RUN["run_id"]  # the committed run, not the archive
    assert status["events_total"] == answer["events_total"] == 2  # alder (merged) and birch (new); the case is seeded
    headlines = [s["headline"] for s in c.get("/api/news").json()["stories"]]
    assert "Invented Birch Photonics raises €6M seed" in headlines
    metrics_at = c.get("/api/news/sources").json()["evaluated_at"]
    assert metrics_at != "2026-11-01T07:00:00"  # the run's evaluation, not the archived cache
    with transaction(settings.db_url) as conn:
        notes = conn.execute(f"select line from {schema}.news_logs where log = 'run_notes'".encode()).fetchall()
    assert json.loads(notes[0][0])["deferred"]  # what the run deferred is recorded per run


def test_a_backcast_committed_during_the_fetch_is_kept(settings: Settings, make: Any) -> None:
    c, schema = make()
    signal = {
        "event_id": "nw-alder",
        "date": "2025-06",
        "url": "https://evidence.invented.example/alder",
        "text": "Invented lab spin-out",
    }

    def operator_writes() -> None:  # between the fetch and the write phase
        assert c.post("/api/news/backcast", json=signal).status_code == 200

    _run(settings, schema, after_fetch=operator_writes)
    with transaction(settings.db_url) as conn:
        rec = conn.execute(f"select record from {schema}.news_events where event_id = 'nw-alder'".encode()).fetchone()
    assert rec is not None
    assert "Invented lab spin-out" in [s.get("text") for s in rec[0]["backcast"]]  # the operator's signal
    assert "https://sifted.eu/articles/invented-alder" in [s["url"] for s in rec[0]["sources"]]  # the run's merge
    history = _history(settings, schema, "nw-alder")
    assert history[0] == "backcast" and "ingest" in history[1:]  # both, in commit order


def test_one_run_at_a_time(settings: Settings, make: Any) -> None:
    c, schema = make()
    holder = connect(settings.db_url, autocommit=True)
    try:
        holder.execute("select pg_advisory_lock(hashtext(%s))", (news_store.RUN_LOCK.format(schema=schema),))
        assert c.get("/api/news/refresh_status").json()["job"]["running"] is True
        for path in ("/api/news/refresh", "/api/news/sources/evaluate"):
            r = c.post(path)
            assert (r.status_code, r.json()) == (409, {"ok": False, "error": "A news refresh is already running."})
    finally:
        holder.close()
    assert c.get("/api/news/refresh_status").json()["job"]["running"] is False


def test_a_write_phase_that_cannot_lock_before_the_deadline_writes_nothing(settings: Settings, make: Any) -> None:
    _c, schema = make()
    with transaction(settings.db_url) as conn:
        before = conn.execute(f"select (select count(*) from {schema}.news_events), (select count(*) from {schema}.news_logs)".encode()).fetchone()  # fmt: skip
    blocker = connect(settings.db_url)
    try:
        blocker.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"{schema}.news",))  # a News write in progress
        with pytest.raises(runs.RunRefused) as refused:
            _run(settings, schema, deadline_s=6.0)
        assert refused.value.status == 503 and str(refused.value) == runs.WRITE_DEADLINE
    finally:
        blocker.rollback()
        blocker.close()
    with transaction(settings.db_url) as conn:
        after = conn.execute(f"select (select count(*) from {schema}.news_events), (select count(*) from {schema}.news_logs)".encode()).fetchone()  # fmt: skip
    assert after == before  # nothing written
    assert _run(settings, schema)["started"] is True  # the run lock was released: the next run succeeds


def test_the_standalone_evaluation_stores_state_and_metrics(settings: Settings, make: Any) -> None:
    c, _schema = make()
    r = c.post("/api/news/sources/evaluate")
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    assert c.get("/api/news/sources").json()["evaluated_at"] == r.json()["evaluated_at"]


def test_a_planning_read_blocked_past_the_deadline_is_a_503_that_fetches_and_writes_nothing(
    settings: Settings, make: Any
) -> None:
    """Codex H-261 (1): phase 1 is bounded too; the run lock is not held past the deadline."""
    _c, schema = make()
    with transaction(settings.db_url) as conn:
        before = conn.execute(f"select count(*) from {schema}.news_logs".encode()).fetchone()
    transport = FixtureTransport(FEEDS)
    blocker = connect(settings.db_url)
    try:
        blocker.execute(f"lock table {schema}.news_documents in access exclusive mode".encode())
        with pytest.raises(runs.RunRefused) as refused:
            hexes = count(200)
            runs.refresh_run(settings.db_url, schema, NOW, transport=transport, resolver=fixture_resolver,
                             new_hex=lambda: f"{next(hexes):016x}", deadline_s=6.0)  # fmt: skip
        assert refused.value.status == 503 and str(refused.value) == runs.PLAN_DEADLINE  # while the lock is held
        assert transport.requests == []  # nothing fetched
        probe = connect(settings.db_url, autocommit=True)
        try:
            assert news_store.run_active(probe, schema) is False  # the run lock was released
        finally:
            probe.close()
    finally:
        blocker.rollback()
        blocker.close()
    with transaction(settings.db_url) as conn:
        assert conn.execute(f"select count(*) from {schema}.news_logs".encode()).fetchone() == before  # nothing written
    assert _run(settings, schema)["started"] is True  # the retry succeeds


def test_each_pass_of_a_run_keeps_its_own_state_in_the_history(settings: Settings, make: Any) -> None:
    """Codex H-261 (2): an event changed by several passes has one history row per pass with THAT pass's state;
    the rows chain, and the last after-image is the stored record."""
    _c, schema = make()
    _run(settings, schema)
    with transaction(settings.db_url) as conn:
        rows = conn.execute(f"select event_id, action, before, after from {schema}.news_event_history order by id".encode()).fetchall()  # fmt: skip
        stored = dict(conn.execute(f"select event_id, record from {schema}.news_events".encode()).fetchall())
    by_event: dict[str, list[Any]] = {}
    for eid, action, before, after in rows:
        by_event.setdefault(eid, []).append((action, before, after))
    multi = {eid: hist for eid, hist in by_event.items() if len(hist) > 1}
    assert multi, "the fixture run changes at least one event in more than one pass"
    for eid, hist in multi.items():
        for (_a, _b, prev_after), (_a2, before, _after) in pairwise(hist):
            assert before == prev_after  # continuity between the rows
        assert hist[-1][2] == stored[eid]  # the last after-image is the stored event
        assert len({json.dumps(h[2], sort_keys=True) for h in hist}) == len(hist)  # each pass left its own state
    cards = [hist for hist in multi.values() if [h[0] for h in hist][-1] == "card"]
    assert cards and all(
        h[0][2].get("card") is None and h[-1][2].get("card") for h in cards
    )  # the card is the card pass's
