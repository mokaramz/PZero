"""Review 035d acceptance tests: the set-based batch confirm, against the hosted project in throw-away ``pz_itest_*``
schemas imported by the PRODUCTION importer. Invented names only. No model, no network.

* equality (decision d): two scratch copies of one world (obvious REJECTs, a decided, a stale and a flagged one, a
  merged pair, a duplicate id), the request in an order that DIFFERS from candidate-id order; the reference
  per-candidate confirm (035a's code, kept HERE only) on one copy and the new one on the other, in ONE database
  transaction at one request clock, so ``now()`` / ``decided_at`` and the lines' ``ts`` match exactly: the statuses,
  ``decided_at``, every new event, every log row (entry bytes, ``seq`` order) and the answer, with 0 differences;
* an INDEPENDENT expected event detail (a merged alias, distinct sources), written out here, so a regression in the
  shared ``decision_detail`` cannot pass because both paths call it;
* a forced failure in the events insert, and in the log insert: every status unchanged, no row;
* the timing at 50, 200 and 500 synthetic obvious REJECTs, each in its own transaction (``[035d-batch]``).
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from projectzero.api.app import create_app
from projectzero.core.config import Settings
from projectzero.core.db import transaction
from projectzero.dealflow import candidates as cand_mod
from projectzero.dealflow.candidates import DealFlowStore
from projectzero.dealflow.intake.postgres import ensure_intake_open
from projectzero.dealflow.triage import decide as td
from projectzero.dealflow.triage import log as triage_log
from projectzero.network.view import BERLIN
from projectzero.ops import parity_triage_decide as ptd
from projectzero.ops.scratch_import import drop_schema, import_world

pytestmark = pytest.mark.hosted
NOW = datetime(2026, 11, 13, 10, 30, tzinfo=BERLIN)
# request order != candidate-id order; the raw duplicate (tri-both2 twice) and dup-b (absorbed into dup-a) included
REQUEST = ["tri-both2", "tri-s0", "dup-b", "tri-both", "tri-done", "tri-stale", "tri-flag", "dup-a", "tri-both2",
           "tri-ghost"]  # fmt: skip


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture
def world(settings: Settings) -> Iterator[Callable[..., str]]:
    made: list[str] = []

    def build(docs: dict[str, Any]) -> str:
        name = import_world(settings.db_url, copy.deepcopy(docs))
        made.append(name)
        return name

    yield build
    for name in made:
        drop_schema(settings.db_url, name)


def equality_docs() -> dict[str, Any]:
    """The 035a invented world; the merged pair carries distinct sources (several producers, a quality source)."""
    docs = ptd.world_docs()
    cands = docs["inbox.json"]["candidates"]
    for c in cands:
        if c["id"] in ("dup-a", "dup-b"):
            c.update(all_source_ids=["fx-other", "fx-feed"], quality_source_id="fx-quality")
    props = docs["triage_proposals.json"]["proposals"]
    for c in cands:
        if c["id"] in ("dup-a", "dup-b"):
            props[c["id"]] = ptd._both(c)
    return docs


def synthetic_docs(size: int) -> dict[str, Any]:
    cands = [ptd._c(f"sb{n:04d}", f"Invented Batch {n:04d} Haulage", f"Invented Batch {n:04d} Haulage is a family "
                    "haulage business since 1952.") for n in range(size)]  # fmt: skip
    return {
        "inbox.json": {"candidates": cands, "last_run": "2026-10-20 08:00:00", "reprocess_v": 3},
        "triage_proposals.json": {"version": 1, "proposals": {c["id"]: ptd._both(c) for c in cands}},
    }


def q(settings: Settings, schema: str, query: str, params: Any = ()) -> list[tuple[Any, ...]]:
    with transaction(settings.db_url) as conn:
        return conn.execute(query.replace("{s}", schema).encode(), params).fetchall()


# ------------------------------------------------------------------ the reference: 035a's per-candidate confirm
def reference_batch_reject(conn: psycopg.Connection[Any], schema: str, body: Mapping[str, Any], now: datetime) -> Any:
    """035a's ``batch_reject`` confirm, verbatim (commit 400637c / 2e5a598): ``decide`` and ``append`` per candidate."""
    ids, confirm = td.parse_batch(body)
    assert confirm
    ensure_intake_open(conn, schema)
    store = DealFlowStore(conn, schema)
    resolved = store.resolve_many(ids)
    survivors = list(dict.fromkeys(s for s in resolved.values() if s is not None))
    store.lock_for_triage_batch(survivors)
    j = td._judge(conn, schema, survivors)
    eligible, skipped = td.classify_batch(ids, resolved, j.summaries, j.records, j.latest)
    ts = td.now_ts(now)
    for sid in eligible:
        store.decide(
            sid, "rejected", reason="machine triage: batch_accept", expected_status="new", feedback_answer=False
        )
        entry = td.log_entry(j.records[sid], j.inputs.proposals[sid], "REJECT", "batch_accept", "rejected", "", ts)
        triage_log.append(conn, schema, sid, entry, now)
    return {"ok": True, "applied": len(eligible), "skipped": skipped}


def written(conn: psycopg.Connection[Any], schema: str, events_after: int) -> dict[str, Any]:
    def rows(query: str) -> list[tuple[Any, ...]]:
        return [tuple(r) for r in conn.execute(query.replace("{s}", schema).encode()).fetchall()]

    return {
        "statuses": rows("select id, status, decided_at from {s}.candidates order by id"),
        "events": rows(
            f"select candidate_id, actor, action, from_status, to_status, reason, detail, at "
            f"from {{s}}.candidate_events where id > {events_after} order by id"
        ),
        "log": rows("select seq, candidate_id, recorded_at, entry::text from {s}.triage_decisions order by seq"),
    }


def max_event(conn: psycopg.Connection[Any], schema: str) -> int:
    row = conn.execute(f"select coalesce(max(id), 0) from {schema}.candidate_events".encode()).fetchone()
    assert row is not None
    return int(row[0])


# ------------------------------------------------------------------ equality (decision d)
def test_the_set_based_confirm_equals_the_per_candidate_confirm(settings: Settings, world: Callable[..., str]) -> None:
    docs = equality_docs()
    ref_schema, new_schema = world(docs), world(docs)
    body = {"ids": REQUEST, "confirm": True}
    with transaction(settings.db_url) as conn:  # ONE transaction: the same now() for both writers
        ref_after, new_after = max_event(conn, ref_schema), max_event(conn, new_schema)
        ref_answer = reference_batch_reject(conn, ref_schema, body, NOW)
        new_answer = td.batch_reject(conn, new_schema, body, NOW)
        ref, new = written(conn, ref_schema, ref_after), written(conn, new_schema, new_after)
    assert (
        new_answer
        == ref_answer
        == {
            "ok": True,
            "applied": 4,
            "skipped": {td.ALREADY_DECIDED: 1, td.NOT_OBVIOUS: 2, td.SAME_CANDIDATE: 1, td.NO_PROPOSAL: 1},
        }
    )
    eligible = [r[1] for r in new["log"][-4:]]
    assert eligible == ["tri-both2", "tri-s0", "dup-a", "tri-both"]  # the REQUEST order ...
    assert eligible != sorted(eligible)  # ... which is not candidate-id order: an accidental sort fails here
    assert [e[0] for e in new["events"]] == eligible  # the events in the same order
    assert ref == new  # statuses, decided_at, every event (actor, action, from/to, reason, detail, at), every log row
    rejected = [r for r in new["statuses"] if r[0] in eligible]
    assert {r[1] for r in rejected} == {"rejected"} and len({r[2] for r in rejected}) == 1  # one now()


def test_the_event_detail_is_the_expected_snapshot(settings: Settings, world: Callable[..., str]) -> None:
    """Written out independently of ``decision_detail``: the merged survivor's ledger keys (its own id, then the
    absorbed old id) and its sources (every producer, sorted; the quality source)."""
    schema = world(equality_docs())
    with transaction(settings.db_url) as conn:
        out = td.batch_reject(conn, schema, {"ids": ["dup-b", "tri-both"], "confirm": True}, NOW)
    assert out == {"ok": True, "applied": 2, "skipped": {}}
    ev = q(settings, schema, "select actor, action, from_status, to_status, reason, detail from {s}.candidate_events "
           "where candidate_id = 'dup-a' and action = 'status'")  # fmt: skip
    assert ev == [("operator", "status", "new", "rejected", "machine triage: batch_accept", {
        "feedback": {"decision": "rejected", "source_ids": ["fx-feed", "fx-other"], "name": "Kestrel Mapping",
                     "keys": ["dup-a", "dup-b"]},
        "sources": {"source_id": "fx-feed", "quality_source_id": "fx-quality"},
    })]  # fmt: skip
    ev2 = q(settings, schema, "select detail from {s}.candidate_events where candidate_id = 'tri-both' "
            "and action = 'status'")  # fmt: skip
    assert ev2 == [({"feedback": {"decision": "rejected", "source_ids": ["fx-feed"], "name": "Fennimore Cartage",
                                  "keys": ["tri-both"]},
                     "sources": {"source_id": "fx-feed", "quality_source_id": "fx-feed"}},)]  # fmt: skip


def test_decide_keeps_its_branches(settings: Settings, world: Callable[..., str]) -> None:
    """The single decision after the shared builder: a notes-only event holds just the notes; a status change with
    notes holds the notes and the snapshot; the same status again writes no status event."""
    schema = world(equality_docs())
    with transaction(settings.db_url) as conn:
        store = DealFlowStore(conn, schema)
        store.decide("tri-acc", "new", notes="Only a note.")
        store.decide("dup-a", "watch", notes="Watch it.", reason="tab")
        store.decide("dup-a", "watch")
    ev = q(settings, schema, "select candidate_id, action, from_status, to_status, reason, detail from "
           "{s}.candidate_events where action in ('status', 'note') order by id")  # fmt: skip
    assert ev == [
        ("tri-acc", "note", "new", None, None, {"notes": "Only a note."}),
        ("dup-a", "status", "new", "watch", "tab", {
            "notes": "Watch it.",
            "feedback": {"decision": "watch", "source_ids": ["fx-feed", "fx-other"], "name": "Kestrel Mapping",
                         "keys": ["dup-a", "dup-b"]},
            "sources": {"source_id": "fx-feed", "quality_source_id": "fx-quality"},
        }),
    ]  # fmt: skip


# ------------------------------------------------------------------ the rollback (adapted)
def _fails_on(sql_text: str, needle: str, replacement: str) -> str:
    assert sql_text.count(needle) == 1
    return sql_text.replace(needle, replacement)


@pytest.mark.parametrize("where", ["events", "log"])
def test_a_failing_insert_rolls_the_whole_confirm_back(
    settings: Settings, world: Callable[..., str], monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    schema = world(synthetic_docs(5))
    before = q(settings, schema, "select id, status, decided_at from {s}.candidates order by id")
    counts = "select (select count(*) from {s}.candidate_events), (select count(*) from {s}.triage_decisions)"
    n_before = q(settings, schema, counts)
    if where == "events":  # a real database error on the second event row, after the status update ran
        monkeypatch.setattr(cand_mod, "_BATCH_EVENTS", _fails_on(
            cand_mod._BATCH_EVENTS, "e.value->'detail' ", "case when e.ord = 2 then (1 / 0)::text::jsonb "
            "else e.value->'detail' end "))  # fmt: skip
    else:  # on the third line, after the statuses and the events
        monkeypatch.setattr(triage_log, "_INSERT_MANY", _fails_on(
            triage_log._INSERT_MANY, "t.line::json", "(case when t.ord = 3 then (1 / 0)::text else t.line end)::json"))  # fmt: skip
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = lambda: NOW
    with TestClient(app, base_url="http://127.0.0.1:8177", raise_server_exceptions=False) as client:
        r = client.post("/api/deal-flow/triage/batch_reject", json={"ids": [f"sb{n:04d}" for n in range(5)],
                                                                   "confirm": True})  # fmt: skip
    assert r.status_code == 500
    assert q(settings, schema, "select id, status, decided_at from {s}.candidates order by id") == before
    assert q(settings, schema, counts) == n_before  # no event, no line


# ------------------------------------------------------------------ timing (separate transactions)
@pytest.mark.parametrize("size", [50, 200, 500])
def test_the_set_based_confirm_timing(settings: Settings, world: Callable[..., str], size: int) -> None:
    schema = world(synthetic_docs(size))
    ids = [f"sb{n:04d}" for n in reversed(range(size))]  # request order: reversed
    t0 = time.monotonic()
    with transaction(settings.db_url) as conn:
        out = td.batch_reject(conn, schema, {"ids": ids, "confirm": True}, NOW)
    seconds = round(time.monotonic() - t0, 2)
    assert out == {"ok": True, "applied": size, "skipped": {}}
    assert q(settings, schema, "select count(*) from {s}.candidates where status = 'rejected'")[0][0] == size
    logged = [r[0] for r in q(settings, schema, "select candidate_id from {s}.triage_decisions order by seq")]
    assert logged == ids
    print("\n[035d-batch] " + json.dumps({"batch": size, "applied": out["applied"], "seconds": seconds,
                                         "per_candidate_ms": round(1000 * seconds / size, 1)}))  # fmt: skip
