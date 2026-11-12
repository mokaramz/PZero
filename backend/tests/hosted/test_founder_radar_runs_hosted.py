"""Review 026b acceptance tests (plan revision 2, Codex H-217 / H-219) against the hosted project, in throw-away scratch
schemas, with the fixture sites of the parity (invented names) behind a recording transport. NO live network: the
system resolver and ``socket.getaddrinfo`` fail the test if anything calls them.

* a scan end to end through the route: the GitHub rate limit (403 with ``X-RateLimit-Reset``) stops the later GitHub
  sources, which are never contacted; the people, cursor and health are written with their events;
* one run at a time: a second run is a 409; the session lock is released after a failure and after a deadline;
* a write phase blocked on the write lock times out (503), rolls back and releases the session lock;
* a person edited DURING the fetch keeps the edit (the write phase re-reads);
* research and the queue through the routes: the queue resumes across calls;
* the 409 before the import, with nothing fetched.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import socket
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from projectzero.api.app import create_app
from projectzero.core import net
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.dealflow.ranking.names import slug as radar_slug
from projectzero.founder_radar import db, runs
from projectzero.network.people import columns_of, distinct_identifiers
from projectzero.network.store import PeopleStore
from projectzero.ops.db_check import _scratch_sql
from projectzero.ops.parity_founder_calls import utc_instant
from projectzero.ops.parity_founder_radar_fetch import (
    NAMES,
    SIGNALS,
    FixtureTransport,
    fixture_resolver,
    gh_search,
    research_people,
    research_sites,
    scan_403_docs,
    scan_403_sites,
)

pytestmark = pytest.mark.hosted
NOW = utc_instant("2026-11-12T10:00:00")


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture(autouse=True)
def no_live_dns(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    """Only the database's own host may be resolved; any other lookup (a run's request) fails the test."""
    from urllib.parse import urlsplit

    db_host = urlsplit(settings.db_url).hostname
    real = socket.getaddrinfo

    def guarded(host: Any, *a: Any, **kw: Any) -> Any:
        if host == db_host:
            return real(host, *a, **kw)
        raise AssertionError(f"the system resolver must not be used for {host!r} in a test")

    def refuse(host: str) -> list[str]:
        raise AssertionError(f"the system resolver must not be used for {host!r} in a test")

    monkeypatch.setattr(net, "default_resolver", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", guarded)


def _q(settings: Settings, schema: str, query: str, params: Any = ()) -> list[tuple[Any, ...]]:
    with transaction(settings.db_url) as conn:
        return list(conn.execute(query.replace("{s}", schema).encode(), params).fetchall())


def _seed(settings: Settings, schema: str, people: list[dict[str, Any]], documents: dict[str, Any]) -> None:
    raw = json.dumps({"people": people}).encode()
    with transaction(settings.db_url) as conn:
        conn.execute(f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values "
                     "(%s, %s, %s, %s, %s)".encode(),
                     ("people.json", hashlib.sha256(raw).hexdigest(), len(raw), raw, Jsonb(json.loads(raw))))  # fmt: skip
        for p in people:
            cols = columns_of(p["id"], p)
            conn.execute(
                f"insert into {schema}.people (id, name, normalized_name, country, identity_status, founder_status, "
                "radar_state, attrs, legacy) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)".encode(),
                (p["id"], cols["name"], cols["normalized_name"], cols["country"], cols["identity_status"],
                 cols["founder_status"], cols["radar_state"], Jsonb(cols["attrs"]), Jsonb(p)),
            )  # fmt: skip
            for kind, value in distinct_identifiers(p):
                conn.execute(f"insert into {schema}.person_identifiers (person_id, kind, value) values (%s, %s, %s)"
                             .encode(), (p["id"], kind, value))  # fmt: skip
        for key, body in documents.items():
            conn.execute(f"insert into {schema}.documents (key, body) values (%s, %s)".encode(), (key, Jsonb(body)))
        for s in SIGNALS:  # the pipeline companies (research domains, the pz_data collector)
            co = conn.execute(f"insert into {schema}.companies (name) values (%s) returning id".encode(),
                              (s["company"],)).fetchone()  # fmt: skip
            assert co is not None
            conn.execute(f"insert into {schema}.conviction_entries (company_id, slug, status, verified, scores, legacy) "
                         "values (%s, %s, 'new', '{}', '{}', %s)".encode(),
                         (co[0], radar_slug(s["company"]), Jsonb(s)))  # fmt: skip


def _schema(settings: Settings) -> str:
    name = f"pz_itest_{secrets.token_hex(4)}"
    with connect(settings.db_url, autocommit=True) as admin:
        admin.execute(re.sub(r"\bpz\b", name, _scratch_sql("pz")).encode())
    return name


def _drop(settings: Settings, schema: str) -> None:
    with connect(settings.db_url, autocommit=True) as admin:
        admin.execute(f"drop schema if exists {schema} cascade".encode())


def _scan_docs() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    d = scan_403_docs()
    docs = {k: v for k, v in d.items() if k.startswith("radar_")}
    return d["people.json"]["people"], docs


@pytest.fixture
def scan_env(settings: Settings) -> Iterator[tuple[TestClient, str, FixtureTransport]]:
    schema = _schema(settings)
    try:
        people, docs = _scan_docs()
        _seed(settings, schema, people, docs)
        transport = FixtureTransport(scan_403_sites())
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: NOW
        app.state.radar_transport = transport
        app.state.radar_resolver = fixture_resolver({})
        with TestClient(app, base_url="http://127.0.0.1:8177") as c:
            yield c, schema, transport
    finally:
        _drop(settings, schema)


def _session_free(settings: Settings, schema: str) -> bool:
    with connect(settings.db_url, autocommit=True) as probe:
        got = probe.execute("select pg_try_advisory_lock(hashtext(%s))", (f"{schema}.founder_radar.fetch",)).fetchone()
        if got and got[0]:
            probe.execute("select pg_advisory_unlock(hashtext(%s))", (f"{schema}.founder_radar.fetch",))
            return True
        return False


def test_a_scan_end_to_end_stops_github_at_the_rate_limit_and_writes_its_results(
    settings: Settings, scan_env: tuple[TestClient, str, FixtureTransport]
) -> None:
    c, schema, transport = scan_env
    people_before = _q(settings, schema, "select count(*) from {s}.people")[0][0]
    r = c.post("/api/founder-radar/scan", json={})
    assert r.status_code == 200, r.text
    health = r.json()
    assert health["scan_time"] and isinstance(health["totals"], dict)
    urls = [q["url"] for q in transport.requests]
    assert gh_search("Corvath") in urls  # the 403
    assert gh_search("Dunmarrow") not in urls  # the later GitHub source: never contacted
    limited = [s for s in health["sources"] if "rate limited" in json.dumps(s)]
    assert limited, health["sources"]
    assert all("Authorization" not in q["headers"] for q in transport.requests if "api.github.com" not in q["url"])
    assert _q(settings, schema, "select count(*) from {s}.people")[0][0] > people_before  # ingested founders
    docs = _q(settings, schema, "select key from {s}.documents where key in ('radar_cursor.json', 'radar_health.json') "
              "order by key")  # fmt: skip
    assert docs == [("radar_cursor.json",), ("radar_health.json",)]
    actions = {a for (a,) in _q(settings, schema, "select action from {s}.radar_events")}
    assert "scan" in actions
    assert _session_free(settings, schema)  # released


def test_one_run_at_a_time(settings: Settings, scan_env: tuple[TestClient, str, FixtureTransport]) -> None:
    c, schema, transport = scan_env
    holder = connect(settings.db_url, autocommit=True)
    try:
        holder.execute("select pg_advisory_lock(hashtext(%s))", (f"{schema}.founder_radar.fetch",))
        for path, body in (("scan", {}), ("research", {}), ("research_queue", {"batch": 3})):
            r = c.post(f"/api/founder-radar/{path}", json=body)
            assert (r.status_code, r.json()["error"]) == (409, runs.ALREADY_RUNNING), path
        assert transport.requests == []  # nothing was fetched
    finally:
        holder.execute("select pg_advisory_unlock(hashtext(%s))", (f"{schema}.founder_radar.fetch",))
        holder.close()
    assert c.post("/api/founder-radar/scan", json={}).status_code == 200


def test_a_failure_in_the_write_phase_saves_nothing_and_releases_the_lock(
    settings: Settings, scan_env: tuple[TestClient, str, FixtureTransport], monkeypatch: pytest.MonkeyPatch
) -> None:
    c, schema, _ = scan_env
    before = (_q(settings, schema, "select count(*) from {s}.people"), _q(settings, schema, "select key, body from "
              "{s}.documents order by key"), _q(settings, schema, "select count(*) from {s}.radar_events"))  # fmt: skip

    def fail(*_: Any, **__: Any) -> None:
        raise RuntimeError("injected in the write phase")

    monkeypatch.setattr(db, "apply_outcome", fail)
    with pytest.raises(RuntimeError, match="injected"):
        c.post("/api/founder-radar/scan", json={})
    after = (_q(settings, schema, "select count(*) from {s}.people"), _q(settings, schema, "select key, body from "
             "{s}.documents order by key"), _q(settings, schema, "select count(*) from {s}.radar_events"))  # fmt: skip
    assert after == before
    assert _session_free(settings, schema)


def test_a_write_blocked_on_the_write_lock_times_out_rolls_back_and_releases(settings: Settings) -> None:
    schema = _schema(settings)
    try:
        people, docs = _scan_docs()
        _seed(settings, schema, people, docs)
        before = (_q(settings, schema, "select count(*) from {s}.people"),
                  _q(settings, schema, "select count(*) from {s}.radar_events"))  # fmt: skip
        blocker = connect(settings.db_url)
        try:
            with blocker.transaction():
                blocker.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"{schema}.intake",))  # the write lock
                with pytest.raises(runs.RunRefused) as exc:
                    runs.run(settings.db_url, schema, "scan", {}, NOW, transport=FixtureTransport(scan_403_sites()),
                             resolver=fixture_resolver({}), deadline_s=8.0)  # fmt: skip
                assert exc.value.status == 503 and "nothing was saved" in str(exc.value)
        finally:
            blocker.close()
        after = (_q(settings, schema, "select count(*) from {s}.people"),
                 _q(settings, schema, "select count(*) from {s}.radar_events"))  # fmt: skip
        assert after == before  # rolled back
        assert _session_free(settings, schema)  # released
    finally:
        _drop(settings, schema)


def test_a_person_edited_during_the_fetch_keeps_the_edit(settings: Settings) -> None:
    schema = _schema(settings)
    try:
        people, docs = _scan_docs()
        _seed(settings, schema, people, docs)
        edited = {"done": False}
        target = "p-oskar-fenwright"

        class EditingTransport(FixtureTransport):
            def send(self, *a: Any, **kw: Any) -> net.Response:
                if not edited["done"]:  # during the fetch phase: no run transaction is open
                    edited["done"] = True
                    with transaction(settings.db_url) as conn:
                        PeopleStore(conn, schema).save({"id": target, "notes": "edited while the scan fetched"}, NOW)
                return super().send(*a, **kw)

        runs.run(settings.db_url, schema, "scan", {}, NOW, transport=EditingTransport(scan_403_sites()),
                 resolver=fixture_resolver({}))  # fmt: skip
        assert edited["done"]
        rec = _q(settings, schema, "select attrs->'record'->>'notes' from {s}.people where id = %s", (target,))
        assert rec == [("edited while the scan fetched",)]
    finally:
        _drop(settings, schema)


def test_research_and_the_resumable_queue_through_the_routes(settings: Settings) -> None:
    schema = _schema(settings)
    try:
        _seed(settings, schema, research_people(), {})
        transport = FixtureTransport(research_sites())
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: NOW
        app.state.radar_transport = transport
        app.state.radar_resolver = fixture_resolver(NAMES)
        with TestClient(app, base_url="http://127.0.0.1:8177") as c:
            r = c.post("/api/founder-radar/research", json={"key": "dom:larkspur.example"})
            assert r.status_code == 200 and r.json()["ok"], r.text
            assert r.json()["researched"][0]["key"] == "dom:larkspur.example"
            assert not [q for q in transport.requests if "press.elsewhere.example" in q["url"]]  # cross-origin: unsent
            assert all("Authorization" not in q["headers"] for q in transport.requests)
            first = c.post("/api/founder-radar/research_queue", json={"batch": 1}).json()
            assert first["ok"] and len(first["processed"]) == 1
            second = c.post("/api/founder-radar/research_queue", json={"batch": 1}).json()
            assert (second["ok"] and second["remaining"] < first["remaining"]) or second["done"]
            processed = {p["name"] for p in first["processed"]} | {p["name"] for p in second["processed"]}
            assert len(processed) == 2  # resumed: the second call took the next company
        rows = _q(settings, schema, "select key from {s}.radar_research order by pos")
        assert ("dom:larkspur.example",) in rows
        assert ("radar_research_queue.json",) in _q(settings, schema, "select key from {s}.documents")
    finally:
        _drop(settings, schema)


def test_runs_are_closed_before_the_import_in_production_and_fetch_nothing(settings: Settings) -> None:
    transport = FixtureTransport({})
    app = create_app(Settings(db_url=settings.db_url, schema="pz"))
    app.state.clock = lambda: NOW
    app.state.radar_transport = transport
    app.state.radar_resolver = fixture_resolver({})
    with TestClient(app, base_url="http://127.0.0.1:8177") as c:
        r = c.post("/api/founder-radar/scan", json={})
    if r.status_code == 409:
        assert "after the legacy import" in r.json()["error"] and transport.requests == []
    else:  # the live import has happened: the boundary is open
        assert r.status_code == 200


_ = threading  # (kept for parity with the other hosted suites' concurrency helpers)
