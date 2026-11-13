"""Review 037a acceptance tests for the WATCH store (the targets, the trigger log, the view, page saves and
acknowledgements), against the hosted project in throw-away ``pz_itest_*`` schemas imported by the PRODUCTION
importer. Invented names only. No model, no network.

* two concurrent page saves of one company lose no update; both writes share ONE lock derived from the schema name;
* an acknowledgement of an unknown id: "no such trigger", no row; a re-acknowledgement appends again;
* nothing is written before the import; only ``watch_targets`` and ``watch_events`` ever change;
* the archive-then-rows log is read identically by Conviction, Today, Health, Home and the Map (a BOM-prefixed
  archive's first line included);
* a trigger's ``dedupe_key`` is unique against a second insert;
* revision 2: a manual company with no candidate saved, deactivated and reactivated, and a Scout-only WATCH candidate,
  each compared on the Watchlist and in Health (the same company keys, the same counts); an imported target saved
  twice keeps its ``added_at`` and ``checks`` (and matches the old ``set_target`` of the oracle golden).
"""

from __future__ import annotations

import copy
import json
import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from projectzero.api.app import create_app
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.dealflow.intake.postgres import ensure_intake_open
from projectzero.health import inputs as health_inputs
from projectzero.network.view import BERLIN
from projectzero.ops import parity_watch_store as pws
from projectzero.ops.parity_validation import _fingerprint
from projectzero.ops.scratch_import import drop_schema, import_world
from projectzero.watch import log as watch_log
from projectzero.watch import targets as watch_targets
from projectzero.watch import writes

pytestmark = pytest.mark.hosted
NOW = datetime(2026, 11, 13, 10, 0, tzinfo=BERLIN)


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


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


def client_of(settings: Settings, schema: str, now: datetime = NOW) -> TestClient:
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = lambda: now
    return TestClient(app, base_url="http://127.0.0.1:8177")


def q(settings: Settings, schema: str, query: str, params: Any = ()) -> list[tuple[Any, ...]]:
    with transaction(settings.db_url) as conn:
        return conn.execute(query.replace("{s}", schema).encode(), params).fetchall()


def run(settings: Settings, schema: str, query: str, params: Any = ()) -> None:
    with transaction(settings.db_url) as conn:
        conn.execute(query.replace("{s}", schema).encode(), params)


def fingerprint(settings: Settings, schema: str) -> dict[str, Any]:
    with transaction(settings.db_url) as conn:
        return _fingerprint(conn, schema)


def changed(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    return {k for k in set(before) | set(after) if before.get(k) != after.get(k)}


def both_views(settings: Settings, schema: str, client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    """The Watchlist and Health: their company keys and counts (Health's keys from its own loaded inputs)."""
    view = client.get("/api/watch").json()
    health = client.get("/api/system_health").json()["watch"]
    with transaction(settings.db_url) as conn:
        hi = health_inputs.load(conn, schema, NOW.replace(tzinfo=None))
    keys = list(watch_targets.watched(hi.watch_candidates, watch_targets.targets_of(hi.watch_targets)))
    mine = {"keys": [c["key"] for c in view["companies"]], "companies": len(view["companies"]),
            "open": sum(c["open"] for c in view["companies"])}  # fmt: skip
    theirs = {"keys": keys, "companies": health["companies"], "open": health["open_triggers"]}
    return mine, theirs


def same_set(mine: dict[str, Any], theirs: dict[str, Any]) -> None:
    assert sorted(mine["keys"]) == sorted(theirs["keys"])
    assert (mine["companies"], mine["open"]) == (theirs["companies"], theirs["open"])


# ------------------------------------------------------------------ revision 2: one watched set, two views
def test_a_manual_company_and_a_scout_lead_are_the_same_on_the_watchlist_and_in_health(
    settings: Settings, world: Callable[..., str]
) -> None:
    schema = world()
    lead = pws.extra_watch()[1]  # Kelpie Motors: a Scout planner lead with no target
    with client_of(settings, schema) as client:
        mine, theirs = both_views(settings, schema, client)
        same_set(mine, theirs)
        assert "kelpie motors" in mine["keys"]  # the Scout-only WATCH candidate is listed and counted
        row = next(c for c in client.get("/api/watch").json()["companies"] if c["key"] == "kelpie motors")
        assert row["candidate_id"] == lead["id"] and row["urls"] == []
        assert "fennimore cartage" not in mine["keys"]
        steps = [({"name": "Fennimore Cartage GmbH", "urls": []}, True),
                 ({"name": "Fennimore Cartage", "urls": [], "active": False}, False),
                 ({"name": "Fennimore Cartage", "urls": ["https://fennimore.invented.example/"]}, True)]  # fmt: skip
        for body, listed in steps:
            r = client.post("/api/watch_target", json=body)
            assert r.status_code == 200 and r.json()["target"]["active"] is listed
            mine, theirs = both_views(settings, schema, client)
            same_set(mine, theirs)
            assert ("fennimore cartage" in mine["keys"]) is listed
    assert q(settings, schema, "select count(*) from {s}.candidates where name ilike %s", ("Fennimore%",))[0][0] == 0


def test_an_imported_target_saved_twice_keeps_its_creation_time_and_checks(
    settings: Settings, world: Callable[..., str]
) -> None:
    schema = world()
    golden = json.loads(pws.GOLDEN.read_text(encoding="utf-8"))
    imported = pws.world_targets()["targets"]["arvelle robotics"]
    for i in (1, 2):  # the golden's steps 1 and 2: two URLs, then a different list of three
        step, old = golden["input"]["steps"][i], golden["expected"]["steps"][i]
        when = datetime.fromisoformat(step["clock"]).replace(tzinfo=BERLIN)
        with client_of(settings, schema, when) as client:
            r = client.post("/api/watch_target", json=step["body"])
        assert r.status_code == 200
        got = r.json()["target"]
        assert got == old["answer"]["target"] and list(got) == list(old["answer"]["target"])  # the old set_target
        assert got["added_at"] == imported["added_at"] and got["checks"] == imported["checks"]
        assert got["urls"] == [u.strip() for u in step["body"]["urls"] if u.strip()][:6]
        assert got["updated_at"] == when.strftime("%Y-%m-%dT%H:%M:%S") and got["candidate_id"] == "wat-arv"
        [(record,)] = q(settings, schema, "select record from {s}.watch_targets where key = 'arvelle robotics'")
        assert record == got
    assert q(settings, schema, "select count(*) from {s}.watch_targets")[0][0] == 1


# ------------------------------------------------------------------ the writes
def test_two_concurrent_saves_of_one_company_lose_no_update(
    settings: Settings, world: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = world()
    real_save = watch_targets.save_record
    first = threading.Event()

    def slow_save(conn: psycopg.Connection[Any], s: str, key: str, record: dict[str, Any]) -> None:
        if not first.is_set():
            first.set()
            time.sleep(1.5)  # the first save holds the lock while the second one arrives
        real_save(conn, s, key, record)

    monkeypatch.setattr(watch_targets, "save_record", slow_save)
    answers: dict[str, dict[str, Any]] = {}

    def save(tag: str, body: dict[str, Any], at: datetime) -> None:
        with transaction(settings.db_url) as conn:
            answers[tag] = writes.set_target(conn, schema, body, at)

    a = threading.Thread(target=save, args=("a", {"name": "Gorsedd Holdings", "urls": ["https://g.invented.example/a"],
                                                  "candidate_id": "wat-none"}, NOW))  # fmt: skip
    b = threading.Thread(target=save, args=("b", {"name": "Gorsedd Holdings", "urls": ["https://g.invented.example/b"]},
                                            NOW.replace(minute=5)))  # fmt: skip
    a.start()
    assert first.wait(10)
    b.start()
    a.join(20)
    b.join(20)
    final = answers["b"]["target"]
    assert final["candidate_id"] == "wat-none"  # merged from the first save's committed record, not lost
    assert final["added_at"] == "2026-11-13T10:00:00" and final["urls"] == ["https://g.invented.example/b"]
    assert final["updated_at"] == "2026-11-13T10:05:00"
    [(record,)] = q(settings, schema, "select record from {s}.watch_targets where key = 'gorsedd holdings'")
    assert record == final


def test_both_writes_share_one_lock_derived_from_the_schema(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()
    done: list[str] = []

    def run(tag: str, fn: Callable[..., Any], body: dict[str, Any]) -> None:
        with transaction(settings.db_url) as conn:
            fn(conn, schema, body, NOW)
        done.append(tag)

    with connect(settings.db_url) as other, other.transaction():
        writes.lock(other, "pz_itest_ffffffff")  # another schema's lock blocks nothing here
        run("free", writes.set_target, {"name": "Invented Free Co", "urls": []})
        assert done == ["free"]
    holder = connect(settings.db_url)
    try:
        with holder.transaction():
            writes.lock(holder, schema)
            threads = [threading.Thread(target=run, args=("target", writes.set_target, {"name": "Invented Held Co"})),
                       threading.Thread(target=run, args=("ack", writes.acknowledge,
                                                          {"id": "wt-arv000000002", "status": "reviewed"}))]  # fmt: skip
            for t in threads:
                t.start()
            time.sleep(1.5)
            assert done == ["free"] and all(t.is_alive() for t in threads)  # both wait on <schema>.watch
        for t in threads:
            t.join(20)
    finally:
        holder.close()
    assert sorted(done) == ["ack", "free", "target"]


def test_an_unknown_acknowledgement_writes_nothing_and_a_repeat_appends(
    settings: Settings, world: Callable[..., str]
) -> None:
    schema = world()
    before = fingerprint(settings, schema)
    with client_of(settings, schema) as client:
        r = client.post("/api/watch_ack", json={"id": "wt-nosuchthing1", "status": "reviewed"})
        assert (r.status_code, r.json()) == (400, {"ok": False, "error": "no such trigger"})
        r = client.post("/api/watch_ack", json={"id": "wt-arv000000002", "status": "closed"})
        assert (r.status_code, r.json()) == (400, {"ok": False, "error": "status must be reviewed or dismissed"})
        r = client.post("/api/watch_target", json={"name": "Invented Robotics", "urls": "https://a.invented.example/"})
        assert (r.status_code, r.json()) == (400, {"ok": False, "error": "urls must be a list of strings"})
        r = client.post("/api/watch_target", content=b"[1]", headers={"content-type": "application/json"})
        assert r.status_code == 400 and r.json()["ok"] is False
        assert fingerprint(settings, schema) == before
        for status in ("reviewed", "reviewed", "dismissed"):
            r = client.post("/api/watch_ack", json={"id": "wt-arv000000002", "status": status})
            assert r.status_code == 200 and r.json()["kind"] == "status"
        rows = q(settings, schema, "select kind, trigger_id, dedupe_key, line from {s}.watch_events order by seq")
        assert [(k, t, d, ln["status"]) for k, t, d, ln in rows] == [
            ("status", "wt-arv000000002", None, "reviewed"), ("status", "wt-arv000000002", None, "reviewed"),
            ("status", "wt-arv000000002", None, "dismissed")]  # fmt: skip
        arv = next(c for c in client.get("/api/watch").json()["companies"] if c["key"] == "arvelle robotics")
        assert {t["id"]: t["status"] for t in arv["triggers"]}["wt-arv000000002"] == "dismissed"  # the last wins
    assert changed(before, fingerprint(settings, schema)) == {"watch_events"}


@pytest.mark.parametrize("bad", [False, 0, "", {}, None])
def test_a_malformed_urls_value_is_a_400_and_keeps_the_saved_pages(
    settings: Settings, world: Callable[..., str], bad: Any
) -> None:
    """H-379: a supplied ``urls`` that is not a list of strings never clears the saved pages; an explicit [] does."""
    schema = world()
    pages = ["https://news.invented.example/a", "https://news.invented.example/b"]
    with client_of(settings, schema) as client:
        r = client.post("/api/watch_target", json={"name": "Invented Robotics", "urls": pages})
        assert r.status_code == 200 and r.json()["target"]["urls"] == pages
        before = fingerprint(settings, schema)
        r = client.post("/api/watch_target", json={"name": "Invented Robotics", "urls": bad})
        assert (r.status_code, r.json()) == (400, {"ok": False, "error": "urls must be a list of strings"}), bad
        assert fingerprint(settings, schema) == before  # nothing written
        saved = next(c for c in client.get("/api/watch").json()["companies"] if c["key"] == "invented robotics")
        assert saved["urls"] == pages  # the pages survive
        r = client.post("/api/watch_target", json={"name": "Invented Robotics", "urls": []})  # the valid way to clear
        assert r.status_code == 200 and r.json()["target"]["urls"] == []


def test_nothing_is_written_before_the_import(
    settings: Settings, world: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = world()
    with transaction(settings.db_url) as conn:  # the import marker goes: this scratch schema is "before the import"
        conn.execute(sql.SQL("delete from {}.documents where key = 'ops/legacy_import'").format(sql.Identifier(schema)))

    def guarded(conn: psycopg.Connection[Any], s: str, *, live: str = "pz") -> None:
        ensure_intake_open(conn, s, live=s)  # the production guard, pointed at this scratch name

    monkeypatch.setattr(writes, "ensure_intake_open", guarded)
    before = fingerprint(settings, schema)
    with client_of(settings, schema) as client:
        r = client.post("/api/watch_target", json={"name": "Invented Robotics", "urls": []})
        assert r.status_code == 409 and "legacy import" in r.json()["error"]
        r = client.post("/api/watch_ack", json={"id": "wt-arv000000002", "status": "reviewed"})
        assert r.status_code == 409 and "legacy import" in r.json()["error"]
        r = client.post("/api/watch_target", json={"name": ""})
        assert (r.status_code, r.json()["error"]) == (400, "company name required")  # the pure checks come first
        assert client.get("/api/watch").status_code == 200  # the view only reads
    assert fingerprint(settings, schema) == before


def test_only_the_watch_tables_change_and_the_view_reads_nothing_else(
    settings: Settings, world: Callable[..., str]
) -> None:
    schema = world()
    before = fingerprint(settings, schema)
    with client_of(settings, schema) as client:
        assert client.get("/api/watch").status_code == 200
        assert fingerprint(settings, schema) == before
        assert client.post("/api/watch_target", json={"name": "Brontide Labs", "urls": []}).status_code == 200
        assert (
            client.post("/api/watch_target", json={"name": "Lumen Quarry", "urls": [], "active": False}).status_code
            == 200
        )
        assert client.post("/api/watch_ack", json={"id": "wt-bro000000001", "status": "dismissed"}).status_code == 200
    assert changed(before, fingerprint(settings, schema)) == {"watch_targets", "watch_events"}
    assert q(settings, schema, "select status from {s}.candidates where id = 'wat-bro'")[0][0] == "watch"  # untouched


# ------------------------------------------------------------------ the one reader
def test_every_reader_reads_the_archive_then_the_rows(settings: Settings, world: Callable[..., str]) -> None:
    docs = pws.world_docs()
    docs["watch/triggers.jsonl"] = "﻿" + docs["watch/triggers.jsonl"]  # a BOM: the first record still counts
    schema = world(docs)
    with client_of(settings, schema) as client:
        for body in ({"id": "wt-arv000000001", "status": "dismissed"}, {"id": "wt-dor000000003", "status": "reviewed"}):
            assert client.post("/api/watch_ack", json=body).status_code == 200
    with transaction(settings.db_url) as conn:
        events = watch_log.load_events(conn, schema)
        got = pws.readers(conn, schema, NOW)
    assert events[0]["id"] == "wt-arv000000001"
    assert [e.get("trigger_id") for e in events[-2:]] == ["wt-arv000000001", "wt-dor000000003"]  # the rows last
    expected = watch_log.parse_text(docs["watch/triggers.jsonl"].lstrip("﻿")) + events[-2:]
    assert events == expected
    assert pws.reader_problems(got, events, "") == []
    status = {t["id"]: t["status"] for t in watch_log.triggers(events)}
    assert status["wt-arv000000001"] == "dismissed" and status["wt-dor000000003"] == "reviewed"
    assert "wt-arv000000001" not in {t["id"] for t in got["map_open"]}


def test_a_trigger_dedupe_key_is_unique(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()
    insert = "insert into {s}.watch_events (kind, trigger_id, dedupe_key, line) values (%s, %s, %s, %s::json)"
    line = watch_log.line({"id": "wt-new000000001", "kind": "trigger", "dedupe_key": "k" * 20})
    run(settings, schema, insert, ("trigger", "wt-new000000001", "k" * 20, line))
    with pytest.raises(psycopg.errors.UniqueViolation):
        run(settings, schema, insert, ("trigger", "wt-new000000002", "k" * 20, line))
    with pytest.raises(psycopg.errors.CheckViolation):
        run(settings, schema, insert, ("trigger", "wt-new000000003", None, line))
    run(settings, schema, insert, ("status", "wt-new000000001", None, line))  # status rows carry no key
    run(settings, schema, insert, ("status", "wt-new000000001", None, line))
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        run(settings, schema, "delete from {s}.watch_events")
    assert q(settings, schema, "select count(*) from {s}.watch_events")[0][0] == 3
