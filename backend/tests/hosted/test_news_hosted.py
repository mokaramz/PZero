"""Review 028a acceptance tests (Codex H-243) against the hosted project, in throw-away scratch schemas, with invented
names only.

* every News read (and the Validation GET, which now carries the News block) leaves EVERY table unchanged (whole rows
  digested); the curated case is seeded IN MEMORY: the answer shows it, nothing is stored, a second read is the same;
* the archived key order decides a tie: two stories on the same day with the same materiality come back in the
  archive's key order (the long key first, which JSONB would put last);
* missing archives read as their old defaults (no events, no runs; the refresh job is idle).
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from projectzero.api.app import create_app
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.ops.db_check import _scratch_sql
from projectzero.ops.parity_founder_calls import utc_instant
from projectzero.ops.parity_news import day, ev
from projectzero.ops.parity_validation import _fingerprint

pytestmark = pytest.mark.hosted
NOW = utc_instant("2026-11-12T10:00:00")
READS = ("/api/news", "/api/news/weekly", "/api/news/sources", "/api/news/refresh_status", "/api/validation")


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def _archive(conn: Any, schema: str, path: str, text: str) -> None:
    raw = text.encode("utf-8")
    parsed = text if path.endswith(".json") else None
    conn.execute(f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values "
                 "(%s, %s, %s, %s, %s::jsonb)".encode(),
                 (path, hashlib.sha256(raw).hexdigest(), len(raw), raw, parsed))  # fmt: skip


@pytest.fixture
def make(settings: Settings) -> Iterator[Any]:
    made: list[str] = []

    def build(archives: dict[str, str]) -> tuple[TestClient, str]:
        name = f"pz_itest_{secrets.token_hex(4)}"
        with connect(settings.db_url, autocommit=True) as admin:
            admin.execute(re.sub(r"\bpz\b", name, _scratch_sql("pz")).encode())
        made.append(name)
        with transaction(settings.db_url) as conn:
            for path, text in archives.items():
                _archive(conn, name, path, text)
            conn.execute(
                f"select {name}.backfill_news(), {name}.backfill_news_files()".encode()
            )  # the importer's call after the archives (028b)
        app = create_app(Settings(db_url=settings.db_url, schema=name))
        app.state.clock = lambda: NOW
        return TestClient(app, base_url="http://127.0.0.1:8177"), name

    yield build
    for name in made:
        with connect(settings.db_url, autocommit=True) as admin:
            admin.execute(f"drop schema if exists {name} cascade".encode())


def _tables(settings: Settings, schema: str) -> dict[str, Any]:
    with transaction(settings.db_url) as conn:
        return _fingerprint(conn, schema)


# the LONG key first: JSONB would order the short key first
EVENTS = {"events": {
    "nw-zzzzzzzz-long": ev("nw-zzzzzzzz-long", "Invented Alder Robotics", "Invented Alder Robotics raises €3M seed",
                           "funding", day(3), "MEDIUM", rnd="seed", amount=3.0),
    "nw-a": ev("nw-a", "Invented Birch Automation", "Invented Birch Automation raises €3M seed", "funding", day(3),
               "MEDIUM", rnd="seed", amount=3.0),
}, "seeded": []}  # fmt: skip
RUNS = "".join(json.dumps(r, sort_keys=True) + "\n" for r in (
    {"run_id": "news-1", "at": f"{day(2)}T07:00:00", "status": "ok"},
    {"run_id": "news-2", "at": f"{day(1)}T07:00:00", "status": "failed"},
))  # fmt: skip


def test_every_read_leaves_every_table_unchanged_and_seeds_only_in_memory(settings: Settings, make: Any) -> None:
    c, schema = make({"news/events.json": json.dumps(EVENTS, indent=1), "news/runs.jsonl": RUNS})
    before = _tables(settings, schema)
    first = c.get("/api/news").json()
    for path in READS:
        assert c.get(path).status_code == 200, path
    assert _tables(settings, schema) == before  # whole rows of every table: nothing stored
    assert first["counts"]["events"] == 3  # the two archived stories plus the curated case, applied in memory
    assert c.get("/api/news").json() == first  # still computed, never stored
    status = c.get("/api/news/refresh_status").json()
    assert status["job"]["running"] is False and status["events_total"] == 2  # the stored archive
    assert (status["last"]["run_id"], status["last_ok"]["run_id"]) == ("news-2", "news-1")


def test_the_archived_key_order_decides_a_tie(make: Any) -> None:
    c, _ = make({"news/events.json": json.dumps(EVENTS, indent=1)})
    ids = [s["event_id"] for s in c.get("/api/news").json()["stories"] if s["event_id"] in EVENTS["events"]]
    assert ids == ["nw-zzzzzzzz-long", "nw-a"]


def test_missing_archives_read_as_their_old_defaults(make: Any) -> None:
    c, _ = make({})
    body = c.get("/api/news").json()
    assert body["counts"]["events"] == 1  # only the shipped curated case, seeded in memory
    status = c.get("/api/news/refresh_status").json()
    assert (status["last"], status["last_ok"], status["events_total"]) == (None, None, 0)
    assert c.get("/api/news/sources", params={"window": "nonsense"}).json()["window"] == "90"
