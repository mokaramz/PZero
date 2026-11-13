"""Review 034a acceptance tests for the Deal Flow scan, against the hosted project in throw-away ``pz_itest_*``
schemas imported by the PRODUCTION importer. The network is always the fixture transport (recorded bytes) and the
fixture resolver; the system resolver answers only the database's host.

* the old freshness tests (``tests/test_discovery_freshness.py`` 1-6 and 9), ported;
* one scan at a time: a second scan gets the old running answer (another session's lock, this process's job);
* the deadline: the fetch budget's hard cutoff, and a write phase cut off cleanly;
* phase 3 is atomic; nothing is written (or fetched) before the import; a toggle made mid-scan survives;
* the watch baselines in BOTH orders of migration and import;
* revision 3: a partial batch, its replay before the correction, a wholly refused delivery and its replay, the
  corrected retry — with the observed counts and cursor / snapshot values printed (``[034a-rev3]``);
* H-343: an imported UEI is reused by its source and isolated across sources;
* the runner's job runs once.
"""

from __future__ import annotations

import json
import re
import secrets
import socket
import tempfile
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from tests.hosted.test_conviction_hosted import scored

from projectzero.api.app import create_app
from projectzero.core import net
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.dealflow.intake.postgres import IntakeClosedError, ensure_intake_open
from projectzero.dealflow.scan import ingest, parsers, run
from projectzero.dealflow.sources.catalog import registry_entries
from projectzero.dealflow.sources.store import SourcesStore
from projectzero.jobs import runner
from projectzero.jobs.catalog import JobDeps
from projectzero.network.view import BERLIN
from projectzero.ops.db_check import MIGRATIONS
from projectzero.ops.legacy.apply import apply_plan
from projectzero.ops.legacy.plan import build_plan
from projectzero.ops.legacy.source import LegacySnapshot
from projectzero.ops.parity_scan import FixtureTransport, fixture_resolver, html, item, rss, src, uid
from projectzero.ops.scratch_import import FILLER, drop_schema, files_of, import_world

pytestmark = pytest.mark.hosted
T0 = datetime(2026, 11, 13, 9, 0, tzinfo=BERLIN)
FEED = "https://feed.invented.example/rss.xml"
FEED2 = "https://feed2.invented.example/rss.xml"
PAGE = "https://page.invented.example/spinoffs"
SBIR = "https://api.www.sbir.gov/public/api/awards"
CKAN = "https://ckan.invented.example/api/3/action/datastore_search"
SOURCES = [
    src("fx-feed", "Fixture Feed", FEED, "rss", "rss", "mixed", ["DACH"]),
    src("fx-feed2", "Fixture Feed Two", FEED2, "rss", "rss", "mixed", ["DACH"]),
    src("fx-page", "Fixture Spin-off Page", PAGE, "watcher", "page_diff", "pre_company", ["DACH"]),
]
PUB2 = "Tue, 20 Oct 2026 09:00:00 +0000"
# the registry's own default sources, present and OFF (the old test switched the real sources off), so the
# normalization appends nothing and nothing but the fixtures is fetched
DEFAULTS_OFF = [{**e, "enabled": False, "_repair_v": 2} for e in registry_entries()] + [
    {**src("ch-eth-dinfk", "ETH D-INFK spin-offs", "https://inf.ethz.ch/department/spin-offs/spin-offs-list.html",
           "watcher", "page_diff", "pre_company", ["CH"]), "enabled": False, "_repair_v": 2}]  # fmt: skip


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
    parsers._GTR_ORG_CACHE.clear()
    run._JOBS.clear()
    yield


@pytest.fixture
def world(settings: Settings) -> Iterator[Callable[..., str]]:
    made: list[str] = []

    def build(*sources: dict[str, Any], signals: list[dict[str, Any]] | None = None, **files: Any) -> str:
        docs = {"sources.json": {"sources": [*(sources or SOURCES), *DEFAULTS_OFF]}, "inbox.json": {"candidates": [], "reprocess_v": 3},
                "real_data.json": {"signals": signals or []}, **files}  # fmt: skip
        name = import_world(settings.db_url, docs)
        made.append(name)
        return name

    yield build
    for name in made:
        drop_schema(settings.db_url, name)


class Clock:
    def __init__(self) -> None:
        self.t = T0

    def __call__(self) -> datetime:
        return self.t

    def tick(self, minutes: int = 60) -> None:
        self.t += timedelta(minutes=minutes)


def q(settings: Settings, schema: str, query: str, params: Any = ()) -> list[tuple[Any, ...]]:
    with transaction(settings.db_url) as conn:
        return conn.execute(query.replace("{s}", schema).encode(), params).fetchall()


def scan(settings: Settings, schema: str, responses: dict[str, Any], clock: Clock, **kw: Any) -> dict[str, Any]:
    clock.tick()
    kw.setdefault("max_workers", 2)
    return run.scan(settings.db_url, schema, clock=clock, transport=FixtureTransport(responses),
                    resolver=fixture_resolver, **kw)  # fmt: skip


def feeds(
    feed: list[Any] | None = None, feed2: list[Any] | None = None, page: list[str] | None = None
) -> dict[str, Any]:
    return {FEED: {"body": rss(feed or [])}, FEED2: {"body": rss(feed2 or [])}, PAGE: {"body": html(page or [])}}


def scanned(settings: Settings, schema: str) -> list[tuple[str, str, dict[str, Any], str]]:
    """(name, status, scan record, id) of every candidate the scan created, in creation order."""
    rows = q(settings, schema, "select name, status, attrs->'scan_record', id from {s}.candidates "
             "where 'registry_scan' = any(origins) order by first_seen_at, id")  # fmt: skip
    return [(r[0], r[1], r[2], r[3]) for r in rows]


def this_run(settings: Settings, schema: str, run_id: str) -> list[str]:
    return sorted(n for n, st, rec, _ in scanned(settings, schema) if rec.get("run_id") == run_id and st != "baseline")


def client_of(settings: Settings, schema: str, clock: Clock) -> TestClient:
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = clock
    app.state.dealflow_resolver = fixture_resolver
    return TestClient(app, base_url="http://127.0.0.1:8177")


def fingerprint(settings: Settings, schema: str) -> dict[str, Any]:
    out = {}
    for t in ("candidates", "companies", "intake_submissions", "observations", "candidate_events", "scan_runs",
              "scan_watch_snapshots", "source_events"):  # fmt: skip
        out[t] = q(settings, schema, f"select count(*) from {{s}}.{t}")[0][0]
    out["sources"] = q(settings, schema, "select id, attrs from {s}.sources order by id")
    return out


# ------------------------------------------------------------------ the old freshness tests
def test_1_pipeline_companies_are_existing_never_new(settings: Settings, world: Callable[..., str]) -> None:
    schema = world(signals=[{"company": "Aereus", "website": "https://aereus.de", "status": "new"},
                            {"company": "Kyrok", "status": "new"}])  # fmt: skip
    s = scan(settings, schema, feeds([item("Aereus"), item("Kyrok"), item("Aurora Robotics")]), Clock())
    assert (s["new"], s["known_pipeline"]) == (1, 2)
    assert s["known_pipeline_names"] == ["Aereus", "Kyrok"]
    assert s["pipeline_label"] == "Existing pipeline — not discovered in this scan"
    assert [n for n, *_ in scanned(settings, schema)] == ["Aurora Robotics"]
    assert this_run(settings, schema, s["run_id"]) == ["Aurora Robotics"]
    row = q(settings, schema, "select report::text from {s}.scan_runs")[0][0]
    system = [r for r in json.loads(row) if r["source"].startswith("Entity resolution (inbox")]
    assert system[0]["known_pipeline"] == 2 and "existing pipeline" in system[0]["note"].lower()
    assert q(settings, schema, "select count(*) from {s}.intake_submissions")[0][0] == 1  # never submitted: 1 delivery


def test_2_first_scan_records_baseline_and_ledger(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()
    clock = Clock()
    page = [
        "Bravo Sensors GmbH – photonic sensor spin-off founded 2026",
        "Cobalt Drives – robotics spin-off founded 2026",
    ]
    s = scan(settings, schema, feeds([item("Aurora Robotics")], [], page), clock)
    assert (s["new"], s["baseline"], s["known_skipped"], s["known_pipeline"]) == (1, 2, 0, 0)
    assert (s["sources_attempted"], s["sources_ok"], s["sources_failed"]) == (3, 3, 0)
    assert s["raw_records"] == 3 and s["merged_cross_source"] == 0 and s["refused"] == 0
    assert "triage" not in s  # review 035b: the old summary (machine triage runs after the scan)
    n = s["new_companies"][0]
    assert n["name"] == "Aurora Robotics" and n["source_date"] == "2026-10-19"
    assert n["source_url"] == "https://feed.invented.example/news/aurora-robotics" and n["first_seen"] == "2026-11-13"
    assert {b["name"] for b in s["baseline_companies"]} == {"Bravo Sensors GmbH", "Cobalt Drives"}
    assert sorted(st for _, st, _, _ in scanned(settings, schema)) == ["baseline", "baseline", "new"]
    assert this_run(settings, schema, s["run_id"]) == ["Aurora Robotics"]
    with client_of(settings, schema, clock) as client:
        h = client.get("/api/deal-flow/scan_history").json()
        assert h["total"] == 1 and h["scans"][0]["run_id"] == s["run_id"]
        assert {x["source_id"] for x in h["scans"][0]["sources"]} >= {
            "fx-feed",
            "fx-feed2",
            "fx-page",
        }  # (+ the off ones)
        ib = client.get("/api/deal-flow/inbox").json()
        assert ib["last_summary"]["raw_records"] == 3 and ib["last_run"] == s["run_id"]
        page_row = next(r for r in ib["report"] if r.get("source_id") == "fx-page")
        assert (page_row["raw"], page_row["baseline"]) == (2, 2)
        aurora = next(c for c in ib["candidates"] if c["name"] == "Aurora Robotics")
        assert aurora["discovery_tier"] == "announcement" and aurora["run_id"] == s["run_id"]
        assert aurora["attention_v2"]["final"] is not None  # ranked from the full scan record


def test_3_unchanged_second_scan_is_zero_new(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()
    clock = Clock()
    r = feeds([item("Aurora Robotics"), item("Delta Grid")], [item("Echo Photonics", host="feed2.invented.example")],
              ["Bravo Sensors GmbH – spin-off founded 2026"])  # fmt: skip
    s1 = scan(settings, schema, r, clock)
    assert (s1["new"], s1["baseline"]) == (3, 1)
    s2 = scan(settings, schema, r, clock)
    assert (s2["new"], s2["baseline"], s2["known_skipped"], s2["merged_into_existing"], s2["merged_cross_source"]) == (
        0, 0, 3, 0, 0)  # fmt: skip
    assert s2["raw_records"] == 3 and s2["new_companies"] == []
    assert this_run(settings, schema, s2["run_id"]) == [] and len(scanned(settings, schema)) == 4
    rec = next(rec for n, _, rec, _ in scanned(settings, schema) if n == "Aurora Robotics")
    assert (rec["first_seen_run"], rec["last_observed"], rec["seen_runs"]) == (s1["run_id"], s2["run_id"], 2)
    with transaction(settings.db_url) as conn:
        from projectzero.dealflow.scan import history

        assert len(history.scan_history(conn, schema)["scans"]) == 2


def test_4_added_company_b_surfaces_alone(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()
    clock = Clock()
    feed, page = [item("Aurora Robotics")], ["Bravo Sensors GmbH – spin-off founded 2026"]
    scan(settings, schema, feeds(feed, [], page), clock)
    scan(settings, schema, feeds(feed, [], page), clock)
    feed.append(item("Bravo Photonics", "secures €1M pre-seed for photonic sensors"))
    page.append("Foxtrot Quantum – spin-off founded 2026")
    s3 = scan(settings, schema, feeds(feed, [], page), clock)
    assert s3["new"] == 2 and {n["name"] for n in s3["new_companies"]} == {"Bravo Photonics", "Foxtrot Quantum"}
    assert s3["known_skipped"] == 1 and s3["baseline"] == 0
    assert this_run(settings, schema, s3["run_id"]) == ["Bravo Photonics", "Foxtrot Quantum"]
    s4 = scan(settings, schema, feeds(feed, [], page), clock)
    assert s4["new"] == 0 and this_run(settings, schema, s4["run_id"]) == []
    assert [n for n, *_ in scanned(settings, schema)].count("Bravo Photonics") == 1


def test_5_two_sources_merge_with_both_provenances(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()
    clock = Clock()
    feed, feed2 = (
        [item("Aurora Robotics")],
        [item("Aurora Robotics", "secures €2M seed round", PUB2, "feed2.invented.example")],
    )
    s = scan(settings, schema, feeds(feed, feed2), clock)
    assert (s["new"], s["merged_cross_source"]) == (1, 1)
    ((_, _, a, _),) = scanned(settings, schema)
    assert sorted(a["all_source_ids"]) == ["fx-feed", "fx-feed2"] and len(a["also_seen"]) == 1
    assert {a["source_id"], a["also_seen"][0]["source_id"]} == {"fx-feed", "fx-feed2"}
    assert {a["source"], a["also_seen"][0]["source"]} == {"Fixture Feed (feed)", "Fixture Feed Two (feed)"}
    s2 = scan(settings, schema, feeds(feed, feed2, ["Aurora Robotics – robotics spin-off founded 2026"]), clock)
    assert (s2["new"], s2["merged_cross_source"], s2["merged_into_existing"], s2["known_skipped"], s2["raw_records"],
            s2["provenance_added"]) == (0, 2, 0, 1, 3, 1)  # fmt: skip
    ((_, _, a, _),) = scanned(settings, schema)
    assert sorted(a["all_source_ids"]) == ["fx-feed", "fx-feed2", "fx-page"]
    assert a["also_seen"][-1]["first_seen"] == s2["run_id"] and a["q_found"] == ["fx-feed", "fx-feed2", "fx-page"]
    with transaction(settings.db_url) as conn:  # the candidates_found milestones, derived (sources.counters)
        found = {x["id"]: x["quality"]["candidates_found"] for x in SourcesStore(conn, schema).view()["sources"]}
    assert (found["fx-feed"], found["fx-feed2"], found["fx-page"]) == (1, 1, 1)


def test_6_pipeline_company_never_readded(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()
    clock = Clock()
    s1 = scan(settings, schema, feeds([item("Aurora Robotics")]), clock)
    ((_, _, _, cid),) = scanned(settings, schema)
    with client_of(settings, schema, clock) as client:
        r = client.post("/api/conviction/save", json={"company": "Aurora Robotics", "website": "https://aurora-robotics.example",
                                                      "inbox_id": cid, **scored()})  # fmt: skip
        assert r.status_code == 200, r.text
    assert scanned(settings, schema)[0][1] == "kept"
    s2 = scan(settings, schema, feeds([item("Aurora Robotics")], [item("Aurora Robotics", "secures seed", host="feed2.invented.example")],
                                      ["Aurora Robotics – spin-off founded 2026"]), clock)  # fmt: skip
    assert s2["new"] == 0
    assert (s2["raw_records"], s2["merged_cross_source"], s2["known_pipeline"], s2["known_skipped"]) == (3, 2, 0, 1)
    assert len(scanned(settings, schema)) == 1 and scanned(settings, schema)[0][1] == "kept"  # status never changed
    s3 = scan(settings, schema, feeds([], [item("Aurora Robotics", "secures seed", host="feed2.invented.example")],
                                      ["Aurora Robotics – spin-off founded 2026"]), clock)  # fmt: skip
    assert s3["new"] == 0
    assert (s3["raw_records"], s3["merged_cross_source"], s3["known_pipeline"], s3["known_skipped"]) == (1, 0, 1, 0)
    assert s3["known_pipeline_names"] == ["Aurora Robotics"] and len(scanned(settings, schema)) == 1
    assert s1["run_id"] != s2["run_id"] != s3["run_id"]


def test_9_state_survives_a_restart(settings: Settings, world: Callable[..., str]) -> None:
    """The old test 9 ran a second process: here every state the scan keeps is in the database, so a scan after the
    process's caches are dropped (the GtR cache, the job state) sees the same history, cursors and baselines."""
    schema = world()
    clock = Clock()
    r = feeds([item(f"Alpha {i} Robotics") for i in range(1, 6)], [item(f"Beta {i} Robotics", host="feed2.invented.example")
                                                                   for i in range(1, 6)], ["Hotel Robotics – spin-off founded 2026"])  # fmt: skip
    scan(settings, schema, r, clock)
    before = q(settings, schema, "select uid, lines from {s}.scan_watch_snapshots")
    parsers._GTR_ORG_CACHE.clear()
    run._JOBS.clear()
    s = scan(settings, schema, r, clock)
    assert (s["new"], s["known_skipped"], s["baseline"]) == (0, 10, 0)
    assert q(settings, schema, "select uid, lines from {s}.scan_watch_snapshots") == before
    assert q(settings, schema, "select count(*) from {s}.scan_runs")[0][0] == 2


# ------------------------------------------------------------------ one scan at a time
def test_a_second_scan_gets_the_running_answer(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()
    clock = Clock()
    holder = connect(settings.db_url, autocommit=True)
    try:
        holder.execute("select pg_advisory_lock(hashtext(%s))", (run.LOCK.format(schema=schema),))
        slow = FixtureTransport(feeds([item("Aurora Robotics")]))
        with client_of(settings, schema, clock) as client:
            client.app.state.dealflow_transport = slow  # type: ignore[attr-defined]
            r = client.post("/api/deal-flow/find", json={"days": 7})
            assert r.status_code == 200 and r.json() == {"running": True, "done": 0, "total": 0,
                                                         "note": "scan already running — progress below"}  # fmt: skip
        assert slow.asked == []  # refused before anything was fetched
        with pytest.raises(run.ScanBusy):
            run.scan(settings.db_url, schema, clock=clock, transport=slow, resolver=fixture_resolver)
    finally:
        holder.close()  # the lock goes with the session
    slow = FixtureTransport(feeds([item("Aurora Robotics")]), delay=1.0)
    with client_of(settings, schema, clock) as client:
        client.app.state.dealflow_transport = slow  # type: ignore[attr-defined]
        assert client.post("/api/deal-flow/find", json={"days": 7}).json() == {"started": True}
        busy = client.post("/api/deal-flow/find", json={}).json()
        assert busy["running"] is True and busy["note"] == "scan already running — progress below"
        deadline = time.monotonic() + 90
        while (st := client.get("/api/deal-flow/find_status").json())["running"]:
            assert time.monotonic() < deadline, st
            time.sleep(0.2)
        assert set(st) == {"running", "done", "total", "rows", "result", "error", "started"}
        assert (
            st["error"] == "" and st["result"]["new"] == 1 and st["done"] == st["total"] == 10
        )  # 3 fixtures + 7 defaults (off)
        assert [r.get("source_id") for r in st["rows"]].count("fx-feed") == 1 and re.fullmatch(
            r"\d\d:\d\d:\d\d", st["started"]
        )
        assert client.post("/api/deal-flow/find", json={"days": 7}).json() == {"started": True}  # free again


# ------------------------------------------------------------------ the deadline
def test_the_fetch_budget_cuts_off_a_slow_source_and_a_late_write_saves_nothing(
    settings: Settings, world: Callable[..., str]
) -> None:
    slow_url = "https://slow.invented.example/rss.xml"
    schema = world(*SOURCES, src("fx-slow", "Slow Feed", slow_url, "rss", "rss", "mixed", ["DACH"]))
    clock = Clock()

    class Slow(FixtureTransport):
        def send(self, target: Any, method: str, *a: Any, **k: Any) -> Any:
            if target.host == "slow.invented.example":
                time.sleep(3.0)
            return super().send(target, method, *a, **k)

    r = {**feeds([item("Aurora Robotics")]), slow_url: {"body": rss([item("Late Robotics")])}}
    clock.tick()
    s = run.scan(settings.db_url, schema, clock=clock, transport=Slow(r), resolver=fixture_resolver, max_workers=6,
                 time_budget=1, source_budget=1)  # fmt: skip
    rows = {
        x.get("source_id"): x for x in json.loads(q(settings, schema, "select report::text from {s}.scan_runs")[0][0])
    }
    assert rows["fx-slow"]["status"] == "failed" and rows["fx-slow"]["note"].startswith(
        "timeout — scan budget (1s) hit"
    )
    assert s["new"] == 1 and [n for n, *_ in scanned(settings, schema)] == [
        "Aurora Robotics"
    ]  # the late result discarded
    with transaction(settings.db_url) as conn:
        slow = next(x for x in SourcesStore(conn, schema).stored() if x["id"] == "fx-slow")
    assert slow["failures_in_row"] == 1 and slow["last_scan"] == "2026-11-13 10:00" and slow.get("last_ok") is None
    before = fingerprint(settings, schema)
    with pytest.raises(run.ScanWriteDeadline):
        scan(settings, schema, feeds([item("Bravo Robotics")]), clock, write_budget=1.0)  # < libpq's 2 s minimum
    assert fingerprint(settings, schema) == before  # cut off cleanly: nothing saved
    assert scan(settings, schema, feeds([item("Bravo Robotics")]), clock)["new"] == 1  # and the lock was released


# ------------------------------------------------------------------ phase 3 is atomic
def test_a_failing_write_phase_leaves_nothing_behind(
    settings: Settings, world: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = world()
    clock = Clock()
    r = feeds([item("Aurora Robotics")], [], ["Bravo Sensors GmbH – spin-off founded 2026"])
    before = fingerprint(settings, schema)

    def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("the snapshot write failed")

    monkeypatch.setattr(ingest, "_save_snapshots", boom)
    with pytest.raises(RuntimeError, match="snapshot write failed"):
        scan(settings, schema, r, clock)
    assert fingerprint(settings, schema) == before  # no delivery, no run, no cursor, no candidate
    monkeypatch.undo()
    s = scan(settings, schema, r, clock)  # the lock was released on the failure path; a NEW run id delivers again
    assert (s["new"], s["baseline"]) == (1, 1)


# ------------------------------------------------------------------ the import boundary
def test_nothing_is_fetched_or_written_before_the_import(
    settings: Settings, world: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = world()
    with transaction(settings.db_url) as conn:  # the import marker goes: this scratch schema is "before the import"
        conn.execute(sql.SQL("delete from {}.documents where key = 'ops/legacy_import'").format(sql.Identifier(schema)))
    real = ensure_intake_open

    def guarded(conn: psycopg.Connection[Any], s: str, *, live: str = "pz") -> None:
        real(conn, s, live=s)  # the production guard, pointed at this scratch name

    monkeypatch.setattr(run, "ensure_intake_open", guarded)
    before = fingerprint(settings, schema)
    t = FixtureTransport(feeds([item("Aurora Robotics")]))
    with pytest.raises(IntakeClosedError):
        run.scan(settings.db_url, schema, clock=Clock(), transport=t, resolver=fixture_resolver)
    with client_of(settings, schema, Clock()) as client:
        client.app.state.dealflow_transport = t  # type: ignore[attr-defined]
        r = client.post("/api/deal-flow/find", json={"days": 7})
        assert r.status_code == 409 and r.json()["ok"] is False and "legacy import" in r.json()["error"]
        assert client.get("/api/deal-flow/find_status").json()["running"] is False
    assert t.asked == [] and fingerprint(settings, schema) == before


# ------------------------------------------------------------------ a toggle made mid-scan
def test_a_toggle_made_during_the_fetch_survives(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()

    def toggle(_f: Any) -> None:
        with transaction(settings.db_url) as conn:
            SourcesStore(conn, schema).toggle({"id": "fx-feed2", "enabled": False})

    s = scan(settings, schema, feeds([item("Aurora Robotics")], [item("Echo Photonics", host="feed2.invented.example")]),
             Clock(), after_fetch=toggle)  # fmt: skip
    assert s["new"] == 2
    with transaction(settings.db_url) as conn:
        feed2 = next(x for x in SourcesStore(conn, schema).stored() if x["id"] == "fx-feed2")
    assert feed2["enabled"] is False  # the operator's toggle survived the scan's write
    assert feed2["last_ok"] == "2026-11-13 10:00" and feed2["total_results"] == 1  # and the scan's runtime keys merged
    assert q(settings, schema, "select source_id, action from {s}.source_events") == [("fx-feed2", "toggle")]


# ------------------------------------------------------------------ revision 2: both orders of migration and import
LINE_A = "Golf Sensors GmbH – photonic spin-off founded 2025"
LINE_B = "Hotel Robotics GmbH – robotics spin-off founded 2026"


def import_before_0024(settings: Settings, docs: dict[str, Any]) -> str:
    """The import into a schema migrated up to 0023, then migration 0024 applied (the other order)."""
    name = f"pz_itest_{secrets.token_hex(4)}"
    files = sorted(MIGRATIONS.glob("*.sql"))
    before = "\n".join(p.read_text(encoding="utf-8") for p in files if not p.name.startswith("20261113000024"))
    after = next(p for p in files if p.name.startswith("20261113000024")).read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="pz-world-") as tmp:
        for rel, raw in files_of({**{k: v for k, v in FILLER.items() if k not in docs}, **docs}).items():
            (Path(tmp) / rel).parent.mkdir(parents=True, exist_ok=True)
            (Path(tmp) / rel).write_bytes(raw)
        snapshot = LegacySnapshot.capture(Path(tmp))
    with connect(settings.db_url, autocommit=True) as admin:
        admin.execute(re.sub(r"\bpz\b", name, before).encode())
    try:
        conn = connect(settings.db_url)
        try:
            assert apply_plan(build_plan(snapshot), schema=name, conn=conn).get("applied")
        finally:
            conn.close()
        with connect(settings.db_url, autocommit=True) as admin:
            admin.execute(re.sub(r"\bpz\b", name, after).encode())
    except BaseException:
        drop_schema(settings.db_url, name)
        raise
    return name


@pytest.mark.parametrize("order", ["migrate_then_import", "import_then_migrate"])
def test_an_imported_watch_baseline_is_diffed_in_either_order(settings: Settings, order: str) -> None:
    docs = {"sources.json": {"sources": [SOURCES[2], *DEFAULTS_OFF]}, "inbox.json": {"candidates": [], "reprocess_v": 3},
            f".watch/{uid(PAGE)}.json": [LINE_A]}  # fmt: skip
    schema = (
        import_world(settings.db_url, docs) if order == "migrate_then_import" else import_before_0024(settings, docs)
    )
    try:
        assert q(settings, schema, "select count(*) from {s}.scan_watch_snapshots")[0][0] == 0  # nothing backfilled
        s = scan(settings, schema, {PAGE: {"body": html([LINE_A, LINE_B])}}, Clock())
        assert (s["new"], s["baseline"]) == (1, 0)  # only B surfaces; nothing is re-baselined
        assert [n for n, *_ in scanned(settings, schema)] == ["Hotel Robotics GmbH"]
        assert q(settings, schema, "select lines, seeded_from from {s}.scan_watch_snapshots") == [
            ([LINE_A, LINE_B], f".watch/{uid(PAGE)}.json")
        ]
    finally:
        drop_schema(settings.db_url, schema)


# ------------------------------------------------------------------ revision 3: refusals, replays, the corrected retry
def test_revision_3_partial_replay_wholly_refused_and_corrected_retry(
    settings: Settings, world: Callable[..., str]
) -> None:
    sbir = src("fx-sbir", "Fixture SBIR mirror", SBIR, "api", "sbir", "grant", ["US"], country="USA", location="USA")
    ckan = src("fx-ckan", "Fixture CKAN mirror", CKAN, "dataset", "ckan", "grant", ["CA"], country="Canada",
               location="Canada", resource_id="res-1")  # fmt: skip
    schema = world(SOURCES[2], sbir, ckan, **{f".watch/{uid(PAGE)}.json": [LINE_A]})
    clock = Clock()
    observed: list[dict[str, Any]] = []

    def responses(page: list[str], sbir_rows: list[dict[str, Any]], ckan_names: list[str]) -> dict[str, Any]:
        recs = [
            {"recipient_legal_name": n, "description_en": "Photonic sensor research and development"}
            for n in ckan_names
        ]
        return {PAGE: {"body": html([LINE_A, *page])}, f"{SBIR}?year=2026&rows=1": {"body": "[]"},
                f"{SBIR}?year=2026&rows=50&start=0": {"body": json.dumps(sbir_rows)},
                f"{SBIR}?year=2026&rows=50&start=50": {"body": "[]"},
                f"{CKAN}?resource_id=res-1&limit=25": {"body": json.dumps({"result": {"records": recs}})}}  # fmt: skip

    def award(aid: str, firm: str) -> dict[str, Any]:
        return {"firm": firm, "award_id": aid, "award_title": "Autonomous inspection drones", "agency": "DOD",
                "award_link": f"https://www.sbir.gov/award/{aid}"}  # fmt: skip

    def state(label: str, s: dict[str, Any]) -> dict[str, Any]:
        with transaction(settings.db_url) as conn:
            sb = next(x for x in SourcesStore(conn, schema).stored() if x["id"] == "fx-sbir")
        rows = {r.get("source_id"): r for r in json.loads(
            q(settings, schema, "select report::text from {s}.scan_runs order by id desc limit 1")[0][0])}  # fmt: skip
        o = {"step": label, "new": s["new"], "known_skipped": s["known_skipped"], "refused": s["refused"],
             "rows": {sid: {k: rows[sid].get(k) for k in ("refused", "already_delivered", "note")} for sid in ("fx-page", "fx-sbir", "fx-ckan")},
             "cursor": sorted((sb.get("hwm") or {}).get("seen") or []),
             "snapshot": q(settings, schema, "select lines from {s}.scan_watch_snapshots")[0][0] if
             q(settings, schema, "select count(*) from {s}.scan_watch_snapshots")[0][0] else None,
             "candidates": sorted(n for n, *_ in scanned(settings, schema))}  # fmt: skip
        observed.append(o)
        return o

    def replay(of: str, fetched: ingest.Fetched) -> dict[str, Any]:
        clock.tick()
        with transaction(settings.db_url) as conn:
            return ingest.write(conn, schema, fetched, clock=clock, replay_of=of)

    caught: list[ingest.Fetched] = []
    keep: Callable[[ingest.Fetched], None] = caught.append
    # 1. the partial batch: one valid and one refused entity per source (a name the schema refuses)
    r1 = responses([LINE_B, "----- -----"], [award("A-1", "Lima Robotics Inc"), award("A-2", "***")],
                   ["Romeo Photonics Inc.", "***"])  # fmt: skip
    s1 = scan(settings, schema, r1, clock, after_fetch=keep)
    o1 = state("1 partial batch", s1)
    assert (o1["new"], o1["known_skipped"], o1["refused"]) == (3, 0, 3)
    assert o1["cursor"] == ["sbir:A-1"] and o1["snapshot"] == [LINE_A, LINE_B]  # the refused key / line not advanced
    for sid in ("fx-page", "fx-sbir", "fx-ckan"):
        assert (
            o1["rows"][sid]["refused"] == 1
            and "1 item(s) refused by the intake: $/entities/" in o1["rows"][sid]["note"]
        )
    # 2. its identical replay BEFORE the correction: the original record decides; nothing advances
    o2 = state("2 replay of the partial batch", replay(s1["run_id"], caught[0]))
    assert (o2["new"], o2["known_skipped"], o2["refused"]) == (0, 3, 3)
    assert all(o2["rows"][sid]["already_delivered"] == 1 for sid in ("fx-page", "fx-sbir", "fx-ckan"))
    assert (o2["cursor"], o2["snapshot"], o2["candidates"]) == (o1["cursor"], o1["snapshot"], o1["candidates"])
    # 3. a wholly refused delivery per source, and its identical replay: 0 known, nothing advanced
    r3 = responses([LINE_B, "----- -----", "===== ====="], [award("A-1", "Lima Robotics Inc"), award("A-2", "***")],
                   ["***", "%%%"])  # fmt: skip
    s3 = scan(settings, schema, r3, clock, after_fetch=keep)
    o3 = state("3 wholly refused delivery", s3)
    assert (o3["new"], o3["known_skipped"], o3["refused"]) == (0, 0, 5)
    assert (o3["cursor"], o3["snapshot"], o3["candidates"]) == (o1["cursor"], o1["snapshot"], o1["candidates"])
    outcomes = [
        r[0] for r in q(settings, schema, "select outcome from {s}.intake_submissions order by received_at, id")
    ]
    assert outcomes.count("rejected") == 3 and outcomes.count("partial") == 3
    o4 = state("4 replay of the wholly refused delivery", replay(s3["run_id"], caught[1]))
    assert (o4["new"], o4["known_skipped"], o4["refused"]) == (0, 0, 5)
    assert (o4["cursor"], o4["snapshot"], o4["candidates"]) == (o1["cursor"], o1["snapshot"], o1["candidates"])
    # 5. the corrected retry: a new delivery; the corrected item is new once, the earlier valid one never new twice
    r5 = responses([LINE_B, "Kilo Drives GmbH – robotics spin-off founded 2026"],
                   [award("A-1", "Lima Robotics Inc"), award("A-2", "Mike Sensors LLC")],
                   ["Romeo Photonics Inc.", "Quebec Photonics Inc."])  # fmt: skip
    o5 = state("5 corrected retry", scan(settings, schema, r5, clock))
    assert (o5["new"], o5["known_skipped"], o5["refused"]) == (3, 1, 0)  # Romeo is known (CKAN has no cursor)
    assert o5["cursor"] == ["sbir:A-1", "sbir:A-2"]
    assert o5["snapshot"] == [LINE_A, LINE_B, "Kilo Drives GmbH – robotics spin-off founded 2026"]
    names = [n for n, *_ in scanned(settings, schema)]
    assert sorted(names) == ["Hotel Robotics GmbH", "Kilo Drives GmbH", "Lima Robotics Inc", "Mike Sensors LLC",
                             "Quebec Photonics Inc.", "Romeo Photonics Inc."]  # fmt: skip
    print("\n[034a-rev3] " + json.dumps(observed, ensure_ascii=False))


# ------------------------------------------------------------------ H-343: the imported registry ids
def imported_award(cid: str, name: str, source_id: str, uei: str) -> dict[str, Any]:
    """An old inbox record of an SBIR award (invented), as the old scan stored it."""
    return {"id": cid, "name": name, "source": "Fixture SBIR mirror (api)", "discovery_tier": "grant",
            "source_url": f"https://www.sbir.gov/award/{cid}", "date": "2026-09-01", "date_kind": "award",
            "detected_on": "2026-10-01", "location": "USA", "country": "USA",
            "description": "Autonomous inspection drones — DOD SBIR, 2026", "why": [], "archetype_hits": [],
            "twins": [], "noise": False, "decision": "new", "notes": "", "priority": 4, "source_id": source_id,
            "geo": ["US"], "first_seen": "2026-10-01", "source_date": "2026-09-01", "run_id": "2026-10-01 08:00:00",
            "first_seen_run": "2026-10-01 08:00:00", "last_observed": "2026-10-01 08:00:00", "seen_runs": 1,
            "all_source_ids": [source_id], "entity_ids": {"uei": uei}}  # fmt: skip


def test_an_imported_uei_is_reused_by_its_source_and_isolated_across_sources(
    settings: Settings, world: Callable[..., str]
) -> None:
    """H-343: a NEW award (new award id, a changed company name, no domain) with an imported company's UEI from the
    SAME source joins that company, with no refusal and no second company; the same UEI value imported from ANOTHER
    source does not join on its own (a new company)."""
    sbir = src("fx-sbir", "Fixture SBIR mirror", SBIR, "api", "sbir", "grant", ["US"], country="USA", location="USA")
    inbox = {"candidates": [imported_award("c-same", "Sierra Motion Inc", "fx-sbir", "SAMEUEI00001"),
                            imported_award("c-other", "Oscar Dynamics Inc", "fx-sbir-old", "OTHERUEI0002")],
             "reprocess_v": 3}  # fmt: skip
    schema = world(sbir, **{"inbox.json": inbox})
    company = {cid: q(settings, schema, "select c.company_id from {s}.candidates c join {s}.candidate_aliases a "
                      "on a.candidate_id = c.id where a.namespace = 'candidate' and a.alias_id = %s", (cid,))[0][0]
               for cid in ("c-same", "c-other")}  # fmt: skip
    stored = q(settings, schema, "select namespace from {s}.company_identifiers where kind = 'registry' order by 1")
    assert [r[0] for r in stored] == ["uei:fx-sbir", "uei:fx-sbir-old"]  # the importer's namespaces
    companies_before = q(settings, schema, "select count(*) from {s}.companies")[0][0]

    def award(aid: str, firm: str, uei: str) -> dict[str, Any]:
        return {"firm": firm, "award_id": aid, "award_title": "Autonomous inspection drones", "agency": "DOD",
                "award_link": f"https://www.sbir.gov/award/{aid}", "uei": uei}  # fmt: skip

    rows = [award("NEW-1", "Sierra Motion Holdings LLC", "SAMEUEI00001"),
            award("NEW-2", "Papa Systems LLC", "OTHERUEI0002")]  # fmt: skip
    responses = {f"{SBIR}?year=2026&rows=1": {"body": "[]"},
                 f"{SBIR}?year=2026&rows=50&start=0": {"body": json.dumps(rows)},
                 f"{SBIR}?year=2026&rows=50&start=50": {"body": "[]"}}  # fmt: skip
    s = scan(settings, schema, responses, Clock())
    observed = {k: s[k] for k in ("new", "merged_into_existing", "known_skipped", "refused")}
    joined = q(settings, schema, "select c.company_id, c.name from {s}.candidates c "
               "where 'registry_scan' = any(c.origins) order by c.name")  # fmt: skip
    companies_after = q(settings, schema, "select count(*) from {s}.companies")[0][0]
    print("\n[034a-H343] " + json.dumps({"summary": observed, "companies": [companies_before, companies_after],
          "joined_original": any(r[0] == company["c-same"] for r in joined)}))  # fmt: skip
    assert observed == {"new": 1, "merged_into_existing": 1, "known_skipped": 0, "refused": 0}
    # same source: the original company, no second one for it
    same = q(settings, schema, "select company_id from {s}.candidates where company_id = %s", (company["c-same"],))
    assert len(same) == 1, same  # one candidate on the original company: re-reported, not created
    assert q(settings, schema, "select count(*) from {s}.company_identifiers where kind = 'registry' "
             "and namespace = 'uei:fx-sbir' and value = 'SAMEUEI00001'")[0][0] == 1  # fmt: skip
    # another source: the same value alone joins nothing; a new company under the scanning source's namespace
    papa = [r for r in joined if r[1] == "Papa Systems LLC"]
    assert len(papa) == 1 and papa[0][0] not in (company["c-same"], company["c-other"])
    assert companies_after == companies_before + 1
    owners = q(settings, schema, "select namespace, company_id from {s}.company_identifiers where kind = 'registry' "
               "and value = 'OTHERUEI0002' order by namespace")  # fmt: skip
    assert [(ns, str(cid)) for ns, cid in owners] == [("uei:fx-sbir", str(papa[0][0])),
                                                      ("uei:fx-sbir-old", str(company["c-other"]))]  # fmt: skip


# ------------------------------------------------------------------ the runner's job
def test_the_runners_job_runs_the_scan_once(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()
    now = datetime(2026, 11, 13, 9, 0)
    deps = JobDeps(dealflow_transport=FixtureTransport(feeds([item("Aurora Robotics")])),
                   dealflow_resolver=fixture_resolver)  # fmt: skip
    holder = connect(settings.db_url, autocommit=True)
    try:
        holder.execute("select pg_advisory_lock(hashtext(%s))", (run.LOCK.format(schema=schema),))
        busy = runner.run_due(settings.db_url, schema, source="cli", now=now, only=["deal_flow_scan"], deps=deps)
        assert [(r["job"], r["note"]) for r in busy] == [("deal_flow_scan", "skipped — a scan is already running")]
    finally:
        holder.close()
    later = now + timedelta(days=8)
    rows = runner.run_due(settings.db_url, schema, source="cli", now=later, only=["deal_flow_scan"], deps=deps)
    assert [(r["job"], r["ok"], r["note"]) for r in rows] == [
        (
            "deal_flow_scan",
            True,
            "1 genuinely new · 0 baseline · machine triage FAILED: 0 of 1 — not_configured: deepinfra: API key "
            "not set (environment variable DEEPINFRA_API_KEY)",  # review 035b: no key under tests, so no call
        )
    ]
    assert q(settings, schema, "select count(*), max(trigger) from {s}.scan_runs") == [(1, "cli")]
    assert runner.run_due(settings.db_url, schema, source="cli", now=later, only=["deal_flow_scan"], deps=deps) == []
    plan = {p["id"]: p for p in runner.status(settings.db_url, schema, now=later)["plan"]}
    assert "availability" not in plan["deal_flow_scan"] and plan["deal_flow_scan"]["overdue"] is False
    assert q(settings, schema, "select count(*) from {s}.scan_runs")[0][0] == 1  # ran once
