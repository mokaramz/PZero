"""Review 027a acceptance tests (plan revision 2, Codex H-226 / H-228) against the hosted project, in throw-away scratch
schemas, with invented names only.

* both GET routes (``/api/validation`` and ``/api/validation/scout_packet``) leave EVERY table unchanged (whole rows
  compared); today's daily snapshot is answered, never stored (decision a);
* the archived log ORDER decides the windows: more than 30 live outcomes whose ``recorded_at`` does not sort like the
  lines answer the last 30 LINES; a retraction outside the raw tail still retracts its target;
* a candidate the new intake created (no legacy inbox record) is counted with its derived fields (decision f): the
  Berlin date of ``first_seen_at`` (a UTC instant on the previous UTC day) and the intake's own discovery tier;
* missing logs read as empty: no outcome, no audit, and the series is today's in-memory point only.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from projectzero.api.app import create_app
from projectzero.core.config import Settings
from projectzero.core.db import connect, read_only_transaction, transaction
from projectzero.dealflow.ranking.tagging import TAGGING_VERSION
from projectzero.ops.db_check import _scratch_sql
from projectzero.ops.parity_founder_calls import utc_instant
from projectzero.ops.parity_validation import _fingerprint
from projectzero.validation import build
from projectzero.validation.inputs import load

pytestmark = pytest.mark.hosted
CLOCK = "2026-11-12T10:00:00"
NOW = utc_instant(CLOCK)
TODAY = NOW.date()


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)


def _archive(conn: Any, schema: str, path: str, raw: bytes) -> None:
    parsed = None
    if path.endswith(".json"):
        parsed = raw.decode("utf-8")
    conn.execute(f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values "
                 "(%s, %s, %s, %s, %s::jsonb)".encode(),
                 (path, hashlib.sha256(raw).hexdigest(), len(raw), raw, parsed))  # fmt: skip


def _outcome(i: int, company: str, recorded_at: str, **kw: Any) -> dict[str, Any]:
    return {"id": f"oc-{i:010d}", "recorded_at": recorded_at, "recorded_by": "mohamed", "company": company,
            "entity_key": company.lower(), "candidate_id": "", "kind": "institutional_round",
            "event_date": "2026-10-01", "evidence_url": "https://invented.example/round", "benchmark_system": "",
            "note": "", "supersedes": None, **kw}  # fmt: skip


def _outcomes() -> str:
    # 36 outcomes; ``recorded_at`` DESCENDS while the lines ascend, so any sort by time would pick other rows; the
    # first line is retracted by the LAST line (outside every raw tail of 30), and line 3 is superseded by line 4
    rows = [
        _outcome(i, f"Invented Kestrel {i:02d}", f"2026-11-{30 - (i // 2):02d}T09:00:{i % 60:02d}") for i in range(36)
    ]
    rows[4]["supersedes"] = rows[3]["id"]
    rows.append({"id": "rx-0000000001", "retracts": rows[0]["id"], "recorded_at": "2026-11-01T08:00:00",
                 "reason": "invented: recorded against the wrong company"})  # fmt: skip
    return _jsonl(rows)


SNAPSHOTS = _jsonl([{"date": f"2026-11-{d:02d}", "at": f"2026-11-{d:02d}T07:00:00", "found_this_month": d,
                     "decisions": 0, "agreement": None} for d in (1, 5, 11)])  # fmt: skip
LOGS = {"validation/outcomes.jsonl": _outcomes(), "validation/snapshots.jsonl": SNAPSHOTS}


def _candidates(conn: Any, schema: str) -> None:
    legacy = {"id": "c-legacy-0001", "name": "Invented Heron Labs", "decision": "new", "discovery_tier": "grant",
              "source_id": "s-invented-grant", "first_seen": "2026-10-03", "description": "Invented grant winner."}  # fmt: skip
    record = {"id": "c-intake-0001", "name": "Invented Plover Systems", "decision": "new",
              "discovery_tier": "pre_company", "source_id": "s-invented-lab", "description": "Invented spin-out."}  # fmt: skip
    tagging = {"version": TAGGING_VERSION, "inputs": {}, "sightings": [], "record": record}
    conn.execute(f"insert into {schema}.candidates (id, name, status, origins, first_seen_at, legacy) values "
                 "('c-legacy-0001', 'Invented Heron Labs', 'new', '{legacy_inbox}', %s, %s)".encode(),
                 (datetime(2026, 10, 3, 8, tzinfo=UTC), Jsonb(legacy)))  # fmt: skip
    # 23:30 UTC on 11 November is 00:30 on 12 November in Berlin: the Berlin date decides
    conn.execute(f"insert into {schema}.candidates (id, name, status, origins, first_seen_at, attrs) values "
                 "('c-intake-0001', 'Invented Plover Systems', 'new', '{manual}', %s, %s)".encode(),
                 (datetime(2026, 11, 11, 23, 30, tzinfo=UTC), Jsonb({"tagging": tagging})))  # fmt: skip


def _schema(settings: Settings, archives: dict[str, str], *, candidates: bool) -> str:
    name = f"pz_itest_{secrets.token_hex(4)}"
    with connect(settings.db_url, autocommit=True) as admin:
        admin.execute(re.sub(r"\bpz\b", name, _scratch_sql("pz")).encode())
    with transaction(settings.db_url) as conn:
        for path, text in archives.items():
            _archive(conn, name, path, text.encode("utf-8"))
        conn.execute(f"select {name}.backfill_validation()".encode())  # the importer's call after the archives (027b)
        if candidates:
            _candidates(conn, name)
    return name


@pytest.fixture
def make(settings: Settings) -> Iterator[Any]:
    made: list[str] = []

    def build_(archives: dict[str, str], *, candidates: bool = False) -> tuple[TestClient, str]:
        schema = _schema(settings, archives, candidates=candidates)
        made.append(schema)
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: NOW
        return TestClient(app, base_url="http://127.0.0.1:8177"), schema

    yield build_
    for schema in made:
        with connect(settings.db_url, autocommit=True) as admin:
            admin.execute(f"drop schema if exists {schema} cascade".encode())


def _tables(settings: Settings, schema: str) -> dict[str, Any]:
    with transaction(settings.db_url) as conn:
        return _fingerprint(conn, schema)


def test_both_reads_leave_every_table_unchanged_and_answer_today_in_memory(settings: Settings, make: Any) -> None:
    client, schema = make(LOGS, candidates=True)
    before = _tables(settings, schema)
    view = client.get("/api/validation")
    packet = client.get("/api/validation/scout_packet", params={"cycle": ""})
    again = client.get("/api/validation")
    assert view.status_code == packet.status_code == again.status_code == 200
    assert _tables(settings, schema) == before  # whole rows of every table: nothing stored
    series = view.json()["snapshots"]
    assert [r["date"] for r in series] == ["2026-11-01", "2026-11-05", "2026-11-11", "2026-11-12"]
    assert series[-1]["at"] == "2026-11-12T10:00:00" and list(series[-1]) == sorted(series[-1])
    assert again.json()["snapshots"] == series  # still computed, never appended
    assert set(packet.json()) == {"cycle", "companies", "text", "sha", "counts"}


def test_the_archived_line_order_decides_the_last_30_and_a_far_retraction_applies(make: Any) -> None:
    client, _ = make(LOGS)
    outcomes = client.get("/api/validation").json()["outcomes"]
    live = [f"oc-{i:010d}" for i in range(36) if i not in (0, 3)]  # retracted, superseded
    assert [o["id"] for o in outcomes] == live[-30:]  # the last 30 LINES (recorded_at descends)


def test_a_candidate_created_by_the_new_intake_is_counted_with_its_derived_fields(
    settings: Settings, make: Any
) -> None:
    _, schema = make({}, candidates=True)
    with read_only_transaction(settings.db_url) as conn:
        inputs = load(conn, schema, NOW)
    ents, _issues = build(inputs, TODAY)
    new = next(e for e in ents.values() if e["name"] == "Invented Plover Systems")
    old = next(e for e in ents.values() if e["name"] == "Invented Heron Labs")
    assert (new["first_seen"], new["first_tier"]) == ("2026-11-12", "pre_company")  # the Berlin date; the intake tier
    assert (old["first_seen"], old["first_tier"]) == ("2026-10-03", "grant")  # the legacy rules


def test_missing_logs_read_as_empty(make: Any) -> None:
    client, _ = make({})
    body = client.get("/api/validation").json()
    assert body["outcomes"] == [] and body["misses"] == [] and body["false_positive_audits"] == []
    assert [r["date"] for r in body["snapshots"]] == ["2026-11-12"]
    assert body["news"]["available"] is False and body["native_bridge"]["available"] is False


def _inbox_record(cid: str, name: str, tier: str, seen: str) -> dict[str, Any]:
    return {"id": cid, "name": name, "decision": "new", "discovery_tier": tier, "source_id": "s-invented-wire",
            "first_seen": seen, "description": f"{name}, invented."}  # fmt: skip


def test_an_absorbed_inbox_record_is_read_at_its_own_archived_position(settings: Settings, make: Any) -> None:
    """The importer merged an old inbox record into a survivor whose own record is a Scout Intake item: the old inbox
    held the inbox record, so Validation reads it (its tier, its first-seen date) at its archived position."""
    first, absorbed, third = (_inbox_record("c-first-0001", "Invented Avocet AG", "grant", "2026-10-01"),
                              _inbox_record("c-absorbed-01", "Invented Dunlin Robotics", "announcement", "2026-10-20"),
                              _inbox_record("c-third-0001", "Invented Godwit Bio", "pre_company", "2026-10-05"))  # fmt: skip
    inbox = json.dumps({"candidates": [first, absorbed, third]}, indent=1)
    _, schema = make({"inbox.json": inbox})
    scout = {"id": "si-005-invented-dunlin", "entity_name": "Invented Dunlin Robotics", "cycle_id": "005"}
    with transaction(settings.db_url) as conn:
        for rec, origins, legacy in ((third, "{legacy_dealflow}", third), (first, "{legacy_dealflow}", first),
                                     (absorbed, "{legacy_dealflow,legacy_scout00}", scout)):  # fmt: skip
            cid = "s-survivor-01" if legacy is scout else rec["id"]
            conn.execute(f"insert into {schema}.candidates (id, name, status, origins, first_seen_at, legacy) "
                         "values (%s, %s, 'watch', %s, %s, %s)".encode(),
                         (cid, rec["name"], origins, datetime(2026, 10, 19, 16, tzinfo=UTC), Jsonb(legacy)))  # fmt: skip
        conn.execute(f"insert into {schema}.observations (candidate_id, origin, payload) values (%s, %s, %s)".encode(),
                     ("s-survivor-01", "legacy_dealflow", Jsonb({"merged_record": absorbed})))  # fmt: skip
    with read_only_transaction(settings.db_url) as conn:
        inputs = load(conn, schema, NOW)
    assert [c["id"] for c in inputs.inbox] == ["c-first-0001", "c-absorbed-01", "c-third-0001"]  # the archived order
    got = inputs.inbox[1]
    assert (got["discovery_tier"], got["first_seen"], got["decision"]) == ("announcement", "2026-10-20", "watch")
    ents, _issues = build(inputs, TODAY)
    dunlin = next(e for e in ents.values() if e["name"] == "Invented Dunlin Robotics")
    assert (dunlin["first_seen"], dunlin["first_tier"]) == ("2026-10-20", "announcement")  # not the survivor's date


def test_a_nul_line_keeps_its_valid_neighbours(settings: Settings, make: Any) -> None:
    """Codex H-241: one archived line text cannot hold (a NUL byte) is skipped as the old reader skipped it; the valid
    outcomes before and after it stay, at their positions."""
    client, schema = make({})
    before, after = (
        _outcome(1, "Invented Kestrel 01", "2026-11-01T09:00:00"),
        _outcome(2, "Invented Kestrel 02", "2026-11-02T09:00:00"),
    )
    raw = (
        (json.dumps(before, sort_keys=True) + "\n").encode()
        + b'{"id": "oc-\x00"}\n'
        + (json.dumps(after, sort_keys=True) + "\n").encode()
    )
    with transaction(settings.db_url) as conn:
        _archive(conn, schema, "validation/outcomes.jsonl", raw)
        conn.execute(f"select {schema}.backfill_validation()".encode())
        conn.execute(f"select {schema}.backfill_validation()".encode())  # a rerun adds nothing
        n = conn.execute(f"select count(*) from {schema}.validation_log".encode()).fetchone()
    assert n is not None and n[0] == 3
    assert [o["id"] for o in client.get("/api/validation").json()["outcomes"]] == [before["id"], after["id"]]
