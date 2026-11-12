"""Review 019 acceptance tests (Codex H-137 / H-139) against the hosted project, in throw-away scratch schemas:

* the first Radar view credits every newly placed entry ONCE: ``radar`` in its record's ``q_milestones`` and one
  ``radar_milestone`` event with ``counted = bool(source_id) and not legacy_credit``; a placed entry with no source
  is marked but not counted; an entry not placed, or already credited in the import, gets nothing;
* a second view, and two concurrent views, add nothing;
* the download credits like the view, is named ``weekly_memo.html`` and carries the old Windows text-mode bytes;
* the memo, the email and the weekly update write nothing.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from projectzero.api.app import create_app
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.ops.db_check import _scratch_sql

pytestmark = pytest.mark.hosted
T0 = datetime(2026, 11, 11, 12, 0, 0)
ALL_V = {"founders": True, "traction": True, "funding": True}
TOP = {"founder": 25, "venture_scale": 19, "why_now": 15, "taste": 15, "insight": 10}  # 84, verified
LOW = {"founder": 10, "venture_scale": 4, "why_now": 2, "taste": 0, "insight": 2}  # 18: never placed


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture
def schema(settings: Settings) -> Iterator[str]:
    name = f"pz_itest_{secrets.token_hex(4)}"
    admin = connect(settings.db_url, autocommit=True)
    try:
        admin.execute(_scratch_sql(name).encode())
        yield name
    finally:
        admin.execute(f"drop schema if exists {name} cascade".encode())
        admin.close()


@pytest.fixture
def client(settings: Settings, schema: str) -> Iterator[TestClient]:
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = lambda: T0
    with TestClient(app, base_url="http://127.0.0.1:8177") as c:
        yield c


def entry(company: str, slug: str, *, scores: dict[str, int] = TOP, archetype: int = 1, **extra: Any) -> dict[str, Any]:
    return {"company": company, "slug": slug, "status": "new", "archetype": archetype, "conflict": "none",
            "scores": scores, "verified": dict(ALL_V), "founders": [{"name": "Ada Example"}],
            "one_liner": f"{company} automates customs paperwork.", **extra}  # fmt: skip


def seed(settings: Settings, schema: str, records: list[dict[str, Any]], inbox: list[dict[str, Any]] = ()) -> None:  # type: ignore[assignment]
    """Imported-style entries (``legacy`` = the record) and, optionally, the imported ``inbox.json``."""
    with transaction(settings.db_url) as conn:
        for r in records:
            co = conn.execute(f"insert into {schema}.companies (name) values (%s) returning id".encode(),
                              (r["company"],)).fetchone()  # fmt: skip
            assert co is not None
            conn.execute(
                f"insert into {schema}.conviction_entries (company_id, slug, status, verified, scores, legacy) "
                "values (%s, %s, 'new', %s, %s, %s)".encode(),
                (co[0], r["slug"], Jsonb(r["verified"]), Jsonb(r["scores"]), Jsonb(r)),
            )
        if inbox:
            raw = json.dumps({"candidates": inbox}).encode("utf-8")
            conn.execute(
                f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) "
                "values ('inbox.json', %s, %s, %s, %s)".encode(),
                (hashlib.sha256(raw).hexdigest(), len(raw), raw, Jsonb({"candidates": inbox})),
            )


def milestones(settings: Settings, schema: str) -> dict[str, list[dict[str, Any]]]:
    with transaction(settings.db_url) as conn:
        rows = conn.execute(f"select slug, detail, actor from {schema}.conviction_events "
                            "where action = 'radar_milestone' order by id".encode()).fetchall()  # fmt: skip
    out: dict[str, list[dict[str, Any]]] = {}
    for slug, detail, actor in rows:
        assert actor == "system"
        out.setdefault(slug, []).append(detail)
    return out


def q_milestones(settings: Settings, schema: str) -> dict[str, Any]:
    with transaction(settings.db_url) as conn:
        rows = conn.execute(f"select slug, coalesce(attrs->'record', legacy)->'q_milestones' "
                            f"from {schema}.conviction_entries".encode()).fetchall()  # fmt: skip
    return dict(rows)


def count_events(settings: Settings, schema: str) -> int:
    with transaction(settings.db_url) as conn:
        row = conn.execute(f"select count(*) from {schema}.conviction_events".encode()).fetchone()
    assert row is not None
    return int(row[0])


def standard(settings: Settings, schema: str) -> None:
    seed(
        settings,
        schema,
        [
            entry("Counted Robotics", "counted-robotics", source_id="src-a", inbox_id="aa0000000001"),
            entry("Prefix Credit Labs", "prefix-credit-labs", archetype=2, source_id="src-b", inbox_id="aa0000000002"),
            entry("No Source Systems", "no-source-systems", archetype=3),  # placed, no source_id (Codex H-137)
            entry("Already Credited", "already-credited", archetype=4, source_id="src-c", q_milestones=["radar"]),
            entry("Not Placed Co", "not-placed-co", scores=LOW, source_id="src-d"),
        ],
        inbox=[{"id": "aa0000000001", "q_milestones": ["kept"]},
               {"id": "aa0000000002", "q_milestones": ["kept", "radar"]}],  # the pre-fix Keep-time credit
    )  # fmt: skip


def test_the_first_view_credits_each_newly_placed_entry_once(
    settings: Settings, schema: str, client: TestClient
) -> None:
    standard(settings, schema)
    view = client.get("/api/conviction/radar").json()
    high = {e["slug"]: e for e in view["high"]}  # equal scores keep the stored order
    assert set(high) == {"counted-robotics", "prefix-credit-labs", "no-source-systems", "already-credited"}
    assert "radar" not in (high["no-source-systems"].get("q_milestones") or [])  # composed before the credit
    ms = milestones(settings, schema)
    assert ms == {
        "counted-robotics": [{"source_id": "src-a", "legacy_credit": False, "counted": True}],
        "prefix-credit-labs": [{"source_id": "src-b", "legacy_credit": True, "counted": False}],
        "no-source-systems": [{"source_id": None, "legacy_credit": False, "counted": False}],
    }
    stored = q_milestones(settings, schema)
    assert stored["counted-robotics"] == stored["prefix-credit-labs"] == stored["no-source-systems"] == ["radar"]
    assert stored["already-credited"] == ["radar"] and stored["not-placed-co"] is None
    # a second view adds nothing, and the pipeline now shows the milestone
    before = count_events(settings, schema)
    client.get("/api/conviction/radar")
    assert count_events(settings, schema) == before
    pipe = {s["slug"]: s for s in client.get("/api/conviction/pipeline").json()["signals"]}
    assert pipe["no-source-systems"]["q_milestones"] == ["radar"]


def test_two_concurrent_views_write_one_event_per_entry(settings: Settings, schema: str, client: TestClient) -> None:
    standard(settings, schema)
    codes: list[int] = []
    threads = [threading.Thread(target=lambda: codes.append(client.get("/api/conviction/radar").status_code))
               for _ in range(2)]  # fmt: skip
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert codes == [200, 200]
    assert {k: len(v) for k, v in milestones(settings, schema).items()} == {
        "counted-robotics": 1, "prefix-credit-labs": 1, "no-source-systems": 1}  # fmt: skip


def test_the_download_credits_like_the_view_with_the_old_name_and_bytes(
    settings: Settings, schema: str, client: TestClient
) -> None:
    standard(settings, schema)
    r = client.get("/api/conviction/radar.html")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["content-disposition"] == 'attachment; filename="weekly_memo.html"'
    assert r.content.startswith(b"<!doctype html>") and b"\r\n" in r.content and b"\n\n" not in r.content
    assert b"Week of 2026-11-11" in r.content and b"Counted Robotics" in r.content
    assert {k: len(v) for k, v in milestones(settings, schema).items()} == {
        "counted-robotics": 1, "prefix-credit-labs": 1, "no-source-systems": 1}  # fmt: skip
    client.get("/api/conviction/radar.html")
    client.get("/api/conviction/radar")
    assert sum(len(v) for v in milestones(settings, schema).values()) == 3


def test_memo_email_and_weekly_write_nothing(settings: Settings, schema: str, client: TestClient) -> None:
    standard(settings, schema)
    stored = q_milestones(settings, schema)
    memo = client.get("/api/conviction/memo", params={"c": "counted-robotics"})
    assert memo.status_code == 200 and memo.json()["text"].startswith("# Scout memo — Counted Robotics\n")
    assert "2026-11-11" in memo.json()["text"]
    email = client.get("/api/conviction/email", params={"c": "counted-robotics"})
    assert email.status_code == 200 and email.json()["text"].startswith("# Outreach — Counted Robotics")
    for kind in ("memo", "email"):
        missing = client.get(f"/api/conviction/{kind}", params={"c": "no-such-company"})
        assert (missing.status_code, missing.json()) == (404, {"error": "not found"})
    weekly = client.post("/api/conviction/weekly", json={"insight": "Buyers want audit trails."})
    assert weekly.status_code == 200
    assert weekly.json()["text"].startswith("Sourcing update — week of 2026-11-11\n")
    assert "Observation: Buyers want audit trails." in weekly.json()["text"]
    assert client.post("/api/conviction/weekly", content=b"[1]").status_code == 400
    assert count_events(settings, schema) == 0 and q_milestones(settings, schema) == stored
