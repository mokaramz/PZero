"""Review 023 acceptance tests (Codex H-175 / H-177) against the hosted project, in throw-away scratch schemas.

The archive fixture's INSERTION order differs from JSONB's (JSONB sorts keys by length, then bytes: long ids first
here, a short one last), and two calls are TIED on everything Conviction sorts by (date, updated):

* the upgrade: every migration before 0014, the byte-exact archive, then 0014: the three ordered id lists equal the
  raw insertion order (compared as LISTS), the rebuilt document's key order is the archive's, and Conviction's tie
  result follows that order; an edit and a new call survive a second backfill with their content and positions;
* the same through the import path (an archive written after 0014, then the backfill the importer calls);
* every write is one event, an unchanged save writes none; two concurrent saves of one call leave one consistent
  record; writes are closed before the import in production.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from projectzero.api.app import create_app
from projectzero.conviction.inputs import load_inputs
from projectzero.conviction.operator import calls_for
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.founder_calls.store import FounderCallsStore
from projectzero.ops.db_check import MIGRATIONS, _scratch_sql
from projectzero.ops.parity_founder_calls import utc_instant

pytestmark = pytest.mark.hosted
FILES = sorted(MIGRATIONS.glob("*.sql"))
M14 = next(p for p in FILES if "founder_calls" in p.name)
NOW = utc_instant("2026-11-12T10:00:00")


def _call(cid: str, fid: str, coid: str) -> dict[str, Any]:
    return {"id": cid, "created": "2026-11-01 09:00:00", "updated": "2026-11-01 09:00:00", "founder_id": fid,
            "company_id": coid, "call_type": "first", "date": "2026-11-01", "time": "10:00", "channel": "video",
            "participants": [], "discovery_origin": "", "intro_path": "", "objective": "", "observations": "",
            "label": "x", "answers": {}, "claims": [], "risks": [], "open_questions": [],
            "next_action": {"text": "", "owner": "", "due": "", "done": False},
            "assessment": {}}  # fmt: skip


# long ids first, a short id last: JSONB would put the short one first
ARCHIVE: dict[str, Any] = {
    "version": 1,
    "label": "Founder calls (invented)",
    "companies": {
        "fc-co-zzzzzzzz-long": {"id": "fc-co-zzzzzzzz-long", "name": "Tiedwell Robotics", "linked_pipeline_slug": "tiedwell",
                                "external": False, "aliases": [], "created": "2026-10-01", "updated": "2026-10-01"},
        "fc-co-a": {"id": "fc-co-a", "name": "Shortid Labs", "linked_pipeline_slug": "", "external": True, "aliases": [],
                    "created": "2026-10-02", "updated": "2026-10-02"},
    },
    "founders": {
        "fc-f-yyyyyyyy-long": {"id": "fc-f-yyyyyyyy-long", "name": "Ada Tied", "company_id": "fc-co-zzzzzzzz-long",
                               "external": False, "aliases": [], "created": "2026-10-01", "updated": "2026-10-01"},
        "fc-f-b": {"id": "fc-f-b", "name": "Bo Short", "company_id": "fc-co-a", "external": True, "aliases": [],
                   "created": "2026-10-02", "updated": "2026-10-02"},
    },
    "calls": {  # the two tied calls: the LONG id first in the file
        "fc-call-xxxxxxxx-long": _call("fc-call-xxxxxxxx-long", "fc-f-yyyyyyyy-long", "fc-co-zzzzzzzz-long"),
        "fc-call-1": _call("fc-call-1", "fc-f-yyyyyyyy-long", "fc-co-zzzzzzzz-long"),
    },
}  # fmt: skip
RAW = json.dumps(ARCHIVE, indent=1).encode("utf-8")


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def _make(settings: Settings, sql: str) -> str:
    name = f"pz_itest_{secrets.token_hex(4)}"
    with connect(settings.db_url, autocommit=True) as admin:
        admin.execute(re.sub(r"\bpz\b", name, sql).encode())
    return name


def _drop(settings: Settings, name: str) -> None:
    with connect(settings.db_url, autocommit=True) as admin:
        admin.execute(f"drop schema if exists {name} cascade".encode())


def _archive(settings: Settings, schema: str) -> None:
    with transaction(settings.db_url) as conn:
        conn.execute(f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values "
                     "('founder_calls.json', %s, %s, %s, %s::jsonb)".encode(),
                     (hashlib.sha256(RAW).hexdigest(), len(RAW), RAW, RAW.decode("utf-8")))  # fmt: skip


def _backfill(settings: Settings, schema: str) -> int:
    with transaction(settings.db_url) as conn:
        row = conn.execute(f"select {schema}.backfill_founder_calls()".encode()).fetchone()
    assert row is not None
    return int(row[0])


def _check_order(settings: Settings, schema: str) -> dict[str, Any]:
    with transaction(settings.db_url) as conn:
        doc = FounderCallsStore(conn, schema).load()
        inp = load_inputs(conn, schema)
    assert doc is not None
    assert list(doc) == list(ARCHIVE)  # the top level in the archive's order
    for coll in ("companies", "founders", "calls"):
        assert list(doc[coll]) == list(ARCHIVE[coll]), coll  # compared as LISTS (dict equality ignores order)
    tied = [c["id"] for c in calls_for({"slug": "tiedwell", "company": "Tiedwell Robotics"}, inp.operator)]
    assert tied == ["fc-call-xxxxxxxx-long", "fc-call-1"]  # Conviction's tie: the original order
    return doc


@pytest.mark.parametrize("path", ["upgrade", "import"])
def test_the_original_order_survives_both_import_paths_and_a_retry(settings: Settings, path: str) -> None:
    if path == "upgrade":  # every migration before 0014, the archive, then 0014 (which runs the backfill)
        schema = _make(settings, "\n".join(p.read_text(encoding="utf-8") for p in FILES if p < M14))
        _archive(settings, schema)
        with connect(settings.db_url, autocommit=True) as admin:
            admin.execute(re.sub(r"\bpz\b", schema, M14.read_text(encoding="utf-8")).encode())
    else:  # a schema with 0014, then the archive and the backfill the importer calls
        schema = _make(settings, _scratch_sql("pz"))
        _archive(settings, schema)
        assert _backfill(settings, schema) == 6
    try:
        _check_order(settings, schema)
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: NOW
        with TestClient(app, base_url="http://127.0.0.1:8177") as c:
            r = c.post("/api/founder-calls/save", json={"id": "fc-call-1", "observations": "Edited after the import."})
            assert r.status_code == 200, r.text
            r = c.post(
                "/api/founder-calls/save", json={"name": "Cy New", "company": "Shortid Labs", "date": "2026-11-12"}
            )
            assert r.status_code == 200, r.text
        assert _backfill(settings, schema) == 0
        with transaction(settings.db_url) as conn:
            doc = FounderCallsStore(conn, schema).load()
        assert doc is not None
        assert doc["calls"]["fc-call-1"]["observations"] == "Edited after the import."
        calls = list(doc["calls"])
        assert calls[:2] == ["fc-call-xxxxxxxx-long", "fc-call-1"] and len(calls) == 3  # the new call is last
        assert list(doc["companies"]) == list(ARCHIVE["companies"])  # it reused the existing company
    finally:
        _drop(settings, schema)


@pytest.fixture
def client(settings: Settings) -> Iterator[tuple[TestClient, str]]:
    schema = _make(settings, _scratch_sql("pz"))
    _archive(settings, schema)
    _backfill(settings, schema)
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = lambda: NOW
    try:
        with TestClient(app, base_url="http://127.0.0.1:8177") as c:
            yield c, schema
    finally:
        _drop(settings, schema)


def _events(settings: Settings, schema: str) -> list[str]:
    with transaction(settings.db_url) as conn:
        return [r[0] for r in conn.execute(f"select action from {schema}.fc_events order by id".encode()).fetchall()]


def test_every_write_is_one_event_and_an_unchanged_save_none(
    settings: Settings, client: tuple[TestClient, str]
) -> None:
    c, schema = client
    assert c.post("/api/founder-calls/save", json={"id": "fc-call-1", "objective": "Learn the wedge."}).json()[
        "changed"
    ]
    body = c.post("/api/founder-calls/save", json={"id": "fc-call-1", "objective": "Learn the wedge."}).json()
    assert body["changed"] is False
    c.post("/api/founder-calls/followup", json={"id": "fc-call-1", "done": True})
    assert _events(settings, schema) == ["save", "followup"]
    r = c.post("/api/founder-calls/followup", json={"id": "fc-call-nope"})
    assert (r.status_code, r.json()) == (404, {"error": "unknown call"})
    assert _events(settings, schema) == ["save", "followup"]


def test_two_concurrent_saves_of_one_call_stay_consistent(settings: Settings, client: tuple[TestClient, str]) -> None:
    c, schema = client
    codes: list[int] = []
    threads = [threading.Thread(target=lambda t=t: codes.append(
        c.post("/api/founder-calls/save", json={"id": "fc-call-1", "observations": f"Writer {t}"}).status_code))
        for t in ("a", "b")]  # fmt: skip
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert codes == [200, 200]
    with transaction(settings.db_url) as conn:
        doc = FounderCallsStore(conn, schema).load()
    assert doc is not None and doc["calls"]["fc-call-1"]["observations"] in ("Writer a", "Writer b")
    assert _events(settings, schema) == ["save", "save"]  # serialized: each saw the other's write


def test_the_first_save_without_an_archive_writes_the_old_complete_document(settings: Settings) -> None:
    """Codex H-179: no archived founder_calls.json; the first save must read back as the old file would have been
    written: version and label first, then the three objects (the old empty document's order)."""
    from projectzero.founder_calls import core

    schema = _make(settings, _scratch_sql("pz"))
    try:
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: NOW
        with TestClient(app, base_url="http://127.0.0.1:8177") as c:
            r = c.post(
                "/api/founder-calls/save", json={"name": "First Founder", "company": "First Co", "date": "2026-11-12"}
            )
            assert r.status_code == 200, r.text
        with transaction(settings.db_url) as conn:
            doc = FounderCallsStore(conn, schema).load()
        empty = core.empty()
        assert doc is not None and list(doc) == list(empty)  # the complete top level, in the old order
        assert (doc["version"], doc["label"]) == (empty["version"], empty["label"])
        assert [len(doc[k]) for k in ("companies", "founders", "calls")] == [1, 1, 1]
    finally:
        _drop(settings, schema)


def test_writes_are_closed_before_the_import_in_production(settings: Settings) -> None:
    app = create_app(Settings(db_url=settings.db_url, schema="pz"))
    app.state.clock = lambda: NOW
    with TestClient(app, base_url="http://127.0.0.1:8177") as c:
        r = c.post("/api/founder-calls/followup", json={"id": "fc-call-anything", "done": True})
    if r.status_code == 409:
        assert "after the legacy import" in r.json()["error"]
    else:  # the live import has happened: the boundary is open (an unknown call is the old 404)
        assert r.status_code == 404
