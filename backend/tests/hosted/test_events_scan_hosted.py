"""Review 017 acceptance tests (Codex H-113) against the hosted project, in throw-away scratch schemas. The network is
always a recorded fetcher:

* one scan at a time: a second scan is refused at once (409) while the scan lock is held;
* a scan whose write phase fails leaves nothing behind AND releases the lock: the next scan runs at once;
* a watcher's baseline is seeded from the archived ``.watch/`` file once, then lives in its table;
* a manual decision committed while the sources are being fetched survives the scan's merge;
* leads are never trimmed: more than 250 stay.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import socketserver
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb
from tests.hosted.test_events_hosted import GOOD, client_at, fingerprint, schema, seed, settings

from projectzero.core import net
from projectzero.core.config import Settings
from projectzero.core.db import transaction
from projectzero.events import scan
from projectzero.events.collectors import uid
from projectzero.events.writes import EventsWriter
from projectzero.ops.parity_events_scan import RecordedFetcher

pytestmark = pytest.mark.hosted
_ = (schema, settings)
NOW = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
WATCH = {"id": "s-w", "name": "Watcher", "kind": "watcher", "url": "https://w.example.com/", "city": "Paris"}
LD = {"id": "s-ld", "name": "Example LD", "kind": "jsonld", "url": "https://ld.example.com/", "city": "Karlsruhe"}


def q(settings: Settings, schema: str, query: str, params: Any = ()) -> list[tuple[Any, ...]]:
    with transaction(settings.db_url) as conn:
        return conn.execute(query.replace("{s}", schema).encode(), params).fetchall()


def registry_doc(settings: Settings, schema: str, *sources: dict[str, Any]) -> None:
    from projectzero.events.registry import NEW_DEFAULTS

    doc = {"sources": list(sources), "offered_defaults": NEW_DEFAULTS}
    with transaction(settings.db_url) as conn:
        conn.execute(
            f"insert into {schema}.documents (key, body) values ('event_sources.json', %s)".encode(), (Jsonb(doc),)
        )


def archive(settings: Settings, schema: str, path: str, doc: Any) -> None:
    raw = json.dumps(doc).encode()
    with transaction(settings.db_url) as conn:
        conn.execute(
            f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values (%s, %s, %s, %s, %s)".encode(),
            (path, hashlib.sha256(raw).hexdigest(), len(raw), raw, Jsonb(doc)),
        )


def ld_page(name: str, day: str) -> str:
    ev = {"@type": "Event", "name": name, "startDate": day, "location": {"@type": "Place", "name": "Hall A",
          "address": {"addressLocality": "Karlsruhe"}}}  # fmt: skip
    return f'<script type="application/ld+json">{json.dumps(ev)}</script>'


def state(client: Any) -> Any:
    """The app state behind a TestClient (``client.app`` is typed as a bare ASGI callable)."""
    return client.app.state


def find(settings: Settings, schema: str, fetcher: Any) -> Any:
    with client_at(settings, schema, NOW) as client:
        state(client).events_fetcher = fetcher
        return client.post("/api/events/find", json={})


def test_a_second_scan_is_refused_while_one_runs(settings: Settings, schema: str) -> None:
    seed(settings, schema, [], [])
    registry_doc(settings, schema, LD)
    fetcher = RecordedFetcher({LD["url"]: {"text": ld_page("Robotics Founders Night", "2026-12-04")}})
    holder = psycopg.connect(settings.db_url, autocommit=True)
    try:
        holder.execute("select pg_advisory_lock(hashtext(%s))", (f"{schema}.events.scan",))
        r = find(settings, schema, fetcher)
        assert r.status_code == 409 and r.json()["error"] == scan.ALREADY_RUNNING
        assert fetcher.asked == []  # refused before anything was fetched
    finally:
        holder.execute("select pg_advisory_unlock(hashtext(%s))", (f"{schema}.events.scan",))
        holder.close()
    r = find(settings, schema, fetcher)
    assert r.status_code == 200 and r.json()["accepted"] == 1


def test_a_failing_write_phase_leaves_nothing_and_the_next_scan_runs_at_once(
    settings: Settings, schema: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(settings, schema, [], [])
    registry_doc(settings, schema, LD, WATCH)
    pages = {LD["url"]: {"text": ld_page("Robotics Founders Night", "2026-12-04")},
             WATCH["url"]: {"text": "<p>Founder Pitch Night on 12.12.2026</p>"}}  # fmt: skip
    before = fingerprint(settings, schema)
    real_insert: Callable[..., Any] = scan._insert_lead

    def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("write phase failed")

    monkeypatch.setattr(scan, "_insert_lead", boom)
    with pytest.raises(RuntimeError, match="write phase failed"):
        find(settings, schema, RecordedFetcher(pages))
    assert fingerprint(settings, schema) == before
    assert q(settings, schema, "select count(*) from {s}.event_watch_snapshots") == [(0,)]
    assert q(settings, schema, "select count(*) from {s}.event_history") == [(0,)]
    monkeypatch.setattr(scan, "_insert_lead", real_insert)
    r = find(settings, schema, RecordedFetcher(pages))  # the lock was released on the failure path
    assert r.status_code == 200 and (r.json()["accepted"], r.json()["added"]) == (1, 1)


def test_a_watch_baseline_is_seeded_from_the_archive_once(settings: Settings, schema: str) -> None:
    seed(settings, schema, [], [])
    registry_doc(settings, schema, WATCH)
    path = f".watch/ev-{uid(WATCH['url'])}.json"
    archive(settings, schema, path, ["Founders breakfast every Friday"])
    page = "<p>Founders breakfast every Friday</p><p>Startup Meetup on 20.12.2026</p>"
    first = find(settings, schema, RecordedFetcher({WATCH["url"]: {"text": page}})).json()
    assert first["added"] == 1  # only the line the archived baseline did not have
    assert q(settings, schema, "select seeded_from, lines from {s}.event_watch_snapshots") == [
        (path, ["Founders breakfast every Friday", "Startup Meetup on 20.12.2026"])
    ]
    again = find(settings, schema, RecordedFetcher({WATCH["url"]: {"text": page}})).json()
    assert again["added"] == 0  # the baseline now lives in the table
    titles = [r[0] for r in q(settings, schema, "select title from {s}.event_leads")]
    assert titles == ["Startup Meetup on 20.12.2026"]


def test_a_manual_decision_made_during_the_fetch_survives(settings: Settings, schema: str) -> None:
    seed(settings, schema, [{"id": "ev-robotics-founders-night-2026-12-04", "name": "Robotics Founders Night",
                             "start": "2026-12-04", **GOOD, "status": "new"}],
         [{"id": "evlead-1", "title": "Some Meetup", "decision": "new"}])  # fmt: skip
    registry_doc(settings, schema, LD)

    class DecidingFetcher(RecordedFetcher):
        def get_text(self, url: str) -> str:
            with transaction(settings.db_url) as conn:  # the operator decides WHILE the scan is fetching
                w = EventsWriter(conn, schema, NOW)
                w.save({"id": "ev-robotics-founders-night-2026-12-04", "status": "planned"})
                w.lead({"id": "evlead-1", "decision": "dismissed"})
            return super().get_text(url)

    r = find(
        settings, schema, DecidingFetcher({LD["url"]: {"text": ld_page("Robotics Founders Night 2026", "2026-12-04")}})
    )
    assert r.status_code == 200 and r.json()["health"]["totals"]["dups"] == 1  # merged into the existing event
    ((rec,),) = q(settings, schema, "select attrs->'record' from {s}.events")
    assert rec["status"] == "planned"  # the decision survived the scan's merge
    assert any(s.get("source_id") == "s-ld" for s in rec["sources"])  # and the scan's source was added
    assert q(settings, schema, "select decision from {s}.event_leads") == [("dismissed",)]


def test_leads_beyond_250_are_kept(settings: Settings, schema: str) -> None:
    leads = [{"id": f"evlead-{i:03d}", "title": f"Distinct lead {i} xq{i}", "decision": "new"} for i in range(260)]
    seed(settings, schema, [], leads)
    registry_doc(settings, schema, WATCH)
    r = find(settings, schema, RecordedFetcher({WATCH["url"]: {"text": "<p>Founder Pitch Night on 12.12.2026</p>"}}))
    assert r.json()["added"] == 1
    assert q(settings, schema, "select count(*) from {s}.event_leads") == [(261,)]
    with client_at(settings, schema, NOW) as client:
        listed = client.get("/api/events").json()["leads"]
    assert listed[0]["title"].startswith("Founder Pitch Night") and len(listed) == 261  # the newest lead first


# ── the deadline bounds every wait (Codex H-115) ────────────────────────────────────────────────────────────────
class _Trickle(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "1000")
        self.end_headers()
        for _ in range(1000):  # a byte every 0.1 s: never idle, never done
            try:
                self.wfile.write(b"x")
                self.wfile.flush()
            except OSError:
                return
            time.sleep(0.1)

    def log_message(self, *_: Any) -> None:
        return


class LocalTransport(net.PinnedTransport):
    """The REAL transport, its pinned connection pointed at a local test server instead of the validated address."""

    def __init__(self, port: int) -> None:
        super().__init__()
        self.port = port
        self.hosts: list[str] = []

    def send(self, target: net.Target, *args: Any, **kwargs: Any) -> net.Response:
        self.hosts.append(target.host)
        return super().send(replace(target, ip="127.0.0.1", port=self.port), *args, **kwargs)


def test_a_source_the_deadline_cuts_off_mid_read_fails_and_the_scan_lock_is_released(
    settings: Settings, schema: str
) -> None:
    seed(settings, schema, [], [])
    slow = {"id": "s-slow", "name": "Slow", "kind": "jsonld", "url": "http://slow.example.com/"}
    later = {"id": "s-later", "name": "Later", "kind": "jsonld", "url": "http://later.example.com/"}
    registry_doc(settings, schema, slow, later)
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Trickle)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        transport = LocalTransport(int(srv.server_address[1]))
        with client_at(settings, schema, NOW) as client:
            # fetching stops after 12 s (a quarter kept for writing): the write needs at least the 2 s minimum connect
            # (Codex H-284) plus the hosted pooler's round trips, which an 8 s budget's 2 s window could not hold
            state(client).events_scan_deadline_s = 16.0
            state(client).events_transport = transport
            state(client).events_resolver = lambda _host: ["93.184.215.14"]
            t0 = time.monotonic()
            r = client.post("/api/events/find", json={})
            elapsed = time.monotonic() - t0
            rows = {x["source"]: x for x in r.json()["report"]}
            assert r.status_code == 200 and elapsed < 18.0  # the trickle alone would have taken 100 s
            assert rows["Slow"]["status"] == "failed" and "deadline reached" in rows["Slow"]["note"]
            assert rows["Later"] == {
                "source": "Later",
                "status": "failed",
                "kind": "jsonld",
                "note": scan.DEADLINE_NOTE,
            }
            assert transport.hosts == ["slow.example.com"]  # the later source was never fetched
            state(client).events_scan_deadline_s = scan.SCAN_DEADLINE_S
            state(client).events_fetcher = RecordedFetcher({})  # the next scan takes the lock at once
            assert client.post("/api/events/find", json={}).status_code == 200
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_write_phase_the_deadline_cuts_off_saves_nothing_and_releases_the_lock(
    settings: Settings, schema: str
) -> None:
    seed(settings, schema, [], [])
    registry_doc(settings, schema, LD)
    fetcher = RecordedFetcher({LD["url"]: {"text": ld_page("Robotics Founders Night", "2026-12-04")}})
    before = fingerprint(settings, schema)
    blocker = psycopg.connect(settings.db_url, autocommit=False)  # holds the events lock in an open transaction
    try:
        blocker.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"{schema}.events",))
        with client_at(settings, schema, NOW) as client:
            state(client).events_scan_deadline_s = 4.0
            state(client).events_fetcher = fetcher
            t0 = time.monotonic()
            r = client.post("/api/events/find", json={})
            assert r.status_code == 503 and r.json()["error"] == scan.WRITE_DEADLINE
            assert time.monotonic() - t0 < 6.0  # the lock wait ended with the deadline
            assert fingerprint(settings, schema) == before
            blocker.rollback()  # the events are free again
            assert client.post("/api/events/find", json={}).status_code == 200  # and the scan lock was released
    finally:
        blocker.close()


def _probe_run(sleep_sql: int = 0, sleep_python: float = 0.0) -> Callable[..., Any]:
    """A write phase that writes a probe row, then takes too long (several timely statements, or a slow finish)."""

    def run(conn: psycopg.Connection[Any], schema: str, *_: Any, **__: Any) -> Any:
        conn.execute(f"insert into {schema}.documents (key, body) values ('probe', '{{}}')".encode())
        for _i in range(sleep_sql):
            conn.execute(b"select pg_sleep(1.2)")  # each one well under its statement_timeout
        time.sleep(sleep_python)
        return {"scan_time": "", "totals": {}, "sources": []}

    return run


@pytest.mark.parametrize(
    ("sleep_sql", "sleep_python"), [(5, 0.0), (0, 5.0)], ids=["cumulative-statements", "late-commit"]
)
def test_database_work_past_the_deadline_rolls_back_and_releases_the_lock(
    settings: Settings, schema: str, monkeypatch: pytest.MonkeyPatch, sleep_sql: int, sleep_python: float
) -> None:
    seed(settings, schema, [], [])
    registry_doc(settings, schema, LD)
    fetcher = RecordedFetcher({LD["url"]: {"text": ld_page("Robotics Founders Night", "2026-12-04")}})
    monkeypatch.setattr(scan, "run", _probe_run(sleep_sql, sleep_python))
    with client_at(settings, schema, NOW) as client:
        state(client).events_scan_deadline_s = 4.0
        state(client).events_fetcher = fetcher
        t0 = time.monotonic()
        r = client.post("/api/events/find", json={})
        assert r.status_code == 503 and r.json()["error"] == scan.WRITE_DEADLINE
        # statements are cancelled at the deadline; Python work past it is not interruptible, but it never commits
        assert time.monotonic() - t0 < (7.0 if sleep_sql else 4.0 + sleep_python + 3.0)
        assert q(settings, schema, "select count(*) from {s}.documents where key = 'probe'") == [(0,)]  # rolled back
        monkeypatch.undo()
        state(client).events_scan_deadline_s = scan.SCAN_DEADLINE_S
        assert client.post("/api/events/find", json={}).status_code == 200  # the scan lock was released


def test_a_scan_with_no_time_left_fetches_nothing(settings: Settings, schema: str) -> None:
    seed(settings, schema, [], [])
    registry_doc(settings, schema, LD)
    fetcher = RecordedFetcher({LD["url"]: {"text": ld_page("Robotics Founders Night", "2026-12-04")}})
    with client_at(settings, schema, NOW) as client:
        state(client).events_scan_deadline_s = 0.000001
        state(client).events_fetcher = fetcher
        r = client.post("/api/events/find", json={})
    assert r.status_code == 503 and fetcher.asked == []


def test_a_budget_that_expires_between_queries_never_waits_on_the_next_lock(
    settings: Settings, schema: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex H-119: the deadline passes during Python work; the NEXT write faces a held row lock. It must be refused at
    once (no wait on the lock), roll back, and leave the scan lock free while the blocker still holds the row."""
    seed(settings, schema, [], [])
    registry_doc(settings, schema, LD)
    fetcher = RecordedFetcher({LD["url"]: {"text": ld_page("Robotics Founders Night", "2026-12-04")}})

    def run(conn: psycopg.Connection[Any], schema_: str, *_: Any, **__: Any) -> Any:
        conn.execute(f"insert into {schema_}.documents (key, body) values ('probe', '{{}}')".encode())
        time.sleep(3.5)  # the budget expires here, while no query is running
        conn.execute(f"update {schema_}.documents set body = body where key = 'event_sources.json'".encode())
        return {"scan_time": "", "totals": {}, "sources": []}

    monkeypatch.setattr(scan, "run", run)
    blocker = psycopg.connect(settings.db_url, autocommit=False)
    try:  # holds the row the late write will try to update
        blocker.execute(f"select 1 from {schema}.documents where key = 'event_sources.json' for update".encode())
        with client_at(settings, schema, NOW) as client:
            state(client).events_scan_deadline_s = 4.0
            state(client).events_fetcher = fetcher
            t0 = time.monotonic()
            r = client.post("/api/events/find", json={})
            elapsed = time.monotonic() - t0
            assert r.status_code == 503 and r.json()["error"] == scan.WRITE_DEADLINE
            assert elapsed < 7.0  # refused before the update: no wait on the held row
            assert q(settings, schema, "select count(*) from {s}.documents where key = 'probe'") == [(0,)]
            probe = psycopg.connect(settings.db_url, autocommit=True)
            try:  # the scan lock is free while the blocker still holds the row
                key = f"{schema}.events.scan"
                assert probe.execute("select pg_try_advisory_lock(hashtext(%s))", (key,)).fetchone() == (True,)
                probe.execute("select pg_advisory_unlock(hashtext(%s))", (key,))
            finally:
                probe.close()
            monkeypatch.undo()
            state(client).events_scan_deadline_s = scan.SCAN_DEADLINE_S
            assert client.post("/api/events/find", json={}).status_code == 200  # an immediate rescan, row still held
    finally:
        blocker.rollback()
        blocker.close()


def test_a_statement_that_passes_the_check_and_reaches_the_server_late_is_cancelled(
    settings: Settings, schema: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex H-121: the thread pauses AFTER the cursor's deadline check, the deadline passes (the one-shot cancel of
    revision 4 would fire on an idle connection), then the statement reaches the server and waits on a held row. The
    canceller keeps cancelling until the transaction exits, so the wait ends within its interval, not at the timeout
    set at entry."""
    seed(settings, schema, [], [])
    registry_doc(settings, schema, LD)
    fetcher = RecordedFetcher({LD["url"]: {"text": ld_page("Robotics Founders Night", "2026-12-04")}})

    def run(conn: psycopg.Connection[Any], schema_: str, *_: Any, **__: Any) -> Any:
        conn.execute(f"insert into {schema_}.documents (key, body) values ('probe', '{{}}')".encode())
        conn.execute(f"update {schema_}.documents set body = body where key = 'event_sources.json'".encode())
        return {"scan_time": "", "totals": {}, "sources": []}

    def pause_after_check(query: Any, done_by: float) -> None:
        if b"set body = body" in (query if isinstance(query, bytes) else str(query).encode()):
            time.sleep(max(0.0, done_by - time.monotonic()) + 0.6)  # resume only after the deadline has passed

    monkeypatch.setattr(scan, "run", run)
    monkeypatch.setattr(scan, "_after_check", pause_after_check)
    blocker = psycopg.connect(settings.db_url, autocommit=False)
    try:
        blocker.execute(f"select 1 from {schema}.documents where key = 'event_sources.json' for update".encode())
        with client_at(settings, schema, NOW) as client:
            state(client).events_scan_deadline_s = 4.0
            state(client).events_fetcher = fetcher
            t0 = time.monotonic()
            r = client.post("/api/events/find", json={})
            elapsed = time.monotonic() - t0
            assert r.status_code == 503 and r.json()["error"] == scan.WRITE_DEADLINE
            assert elapsed < 6.0  # deadline (4 s) + the pause past it (0.6 s) + one cancel interval, not + lock_timeout
            assert q(settings, schema, "select count(*) from {s}.documents where key = 'probe'") == [(0,)]
            probe = psycopg.connect(settings.db_url, autocommit=True)
            try:
                key = f"{schema}.events.scan"
                assert probe.execute("select pg_try_advisory_lock(hashtext(%s))", (key,)).fetchone() == (True,)
                probe.execute("select pg_advisory_unlock(hashtext(%s))", (key,))
            finally:
                probe.close()
            monkeypatch.undo()
            state(client).events_scan_deadline_s = scan.SCAN_DEADLINE_S
            assert client.post("/api/events/find", json={}).status_code == 200
    finally:
        blocker.rollback()
        blocker.close()
