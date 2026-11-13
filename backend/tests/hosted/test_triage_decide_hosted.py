"""Review 035a acceptance tests for the machine-triage decisions (accept / override, batch reject, the decision log),
against the hosted project in throw-away ``pz_itest_*`` schemas imported by the PRODUCTION importer. Invented names
only. No model, no network.

* the decision and its log line are atomic; KEEP writes only the log; an absorbed old id decides its survivor;
  ``expected_status`` gives the 409;
* revision 2: KEEP racing a status change (both orders), a duplicate alias in a batch, a moved company, a forced
  failure on the third line of a five-candidate batch;
* H-348: two overlapping batches whose candidate-id order crosses the company order (asserted in the fixture) both
  finish, each applying its open candidate and skipping its pre-rejected sibling; two concurrent confirms of the SAME
  open candidate write one line and the second reports it "already decided";
* a candidate decided between the preview and the confirm is skipped;
* H-351: only a literal ``true`` applies a batch; the preview reads one snapshot across a concurrent edit;
* nothing is written before the import; ``model_ledger`` is unchanged by every route;
* the view and Validation read the archived lines, then the rows, and a re-decided candidate counts once.
"""

from __future__ import annotations

import copy
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
from projectzero.dealflow.candidates import DealFlowStore, DecisionError
from projectzero.dealflow.intake.postgres import ensure_intake_open
from projectzero.dealflow.triage import decide as td
from projectzero.dealflow.triage import log as triage_log
from projectzero.network.view import BERLIN
from projectzero.ops import parity_triage_decide as ptd
from projectzero.ops.scratch_import import drop_schema, import_world

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
        name = import_world(settings.db_url, copy.deepcopy(docs or ptd.world_docs()))
        made.append(name)
        return name

    yield build
    for name in made:
        drop_schema(settings.db_url, name)


def docs_of(cands: list[dict[str, Any]], log: str = "") -> dict[str, Any]:
    """A world of the given candidates, each an obvious machine REJECT (both models agree)."""
    return {
        "inbox.json": {"candidates": cands, "last_run": "2026-10-20 08:00:00", "reprocess_v": 3},
        "triage_proposals.json": {"version": 1, "proposals": {c["id"]: ptd._both(c) for c in cands}},
        "triage_decisions.jsonl": log,
    }


def q(settings: Settings, schema: str, query: str, params: Any = ()) -> list[tuple[Any, ...]]:
    with transaction(settings.db_url) as conn:
        return conn.execute(query.replace("{s}", schema).encode(), params).fetchall()


def status(settings: Settings, schema: str, cid: str) -> str:
    return str(q(settings, schema, "select status from {s}.candidates where id = %s", (cid,))[0][0])


def rows(settings: Settings, schema: str) -> list[tuple[str, dict[str, Any]]]:
    return [
        (r[0], r[1]) for r in q(settings, schema, "select candidate_id, entry from {s}.triage_decisions order by seq")
    ]


def events(settings: Settings, schema: str) -> int:
    return int(
        q(settings, schema, "select count(*) from {s}.candidate_events where action in ('status', 'note')")[0][0]
    )


def client_of(settings: Settings, schema: str, **kw: Any) -> TestClient:
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    app.state.clock = lambda: NOW
    return TestClient(app, base_url="http://127.0.0.1:8177", **kw)


def decide(client: TestClient, **body: Any) -> Any:
    return client.post("/api/deal-flow/triage/decide", json=body)


def confirm(settings: Settings, schema: str, ids: list[str]) -> dict[str, Any]:
    with transaction(settings.db_url) as conn:
        return td.batch_reject(conn, schema, {"ids": ids, "confirm": True}, NOW)


def fingerprint(settings: Settings, schema: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for t in ("candidates", "candidate_events", "triage_decisions", "model_ledger", "documents"):
        out[t] = q(settings, schema, f"select count(*) from {{s}}.{t}")[0][0]
    out["statuses"] = q(settings, schema, "select id, status, attrs->>'notes' from {s}.candidates order by id")
    return out


# ------------------------------------------------------------------ one decision
def test_the_decision_and_its_line_are_atomic(
    settings: Settings, world: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = world()
    before = fingerprint(settings, schema)

    def broken(*_a: Any, **_k: Any) -> int:
        raise RuntimeError("forced: the log insert fails")

    monkeypatch.setattr(triage_log, "append", broken)
    with client_of(settings, schema, raise_server_exceptions=False) as client:
        r = decide(client, id="tri-ovr", verdict="REJECT", mode="accept", note="never saved")
    assert r.status_code == 500
    assert fingerprint(settings, schema) == before  # the status, the notes and the event rolled back with the line
    assert status(settings, schema, "tri-ovr") == "new"


def test_keep_writes_only_the_log_and_research_logs_the_old_vocabulary(
    settings: Settings, world: Callable[..., str]
) -> None:
    schema = world()
    ev = events(settings, schema)
    with client_of(settings, schema) as client:
        r = decide(client, id="tri-keep", verdict="KEEP", expected_status="new")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "verdict": "KEEP", "agreed": True, "inbox_decision": None, "open_keep": True}
        assert status(settings, schema, "tri-keep") == "new" and events(settings, schema) == ev
        assert rows(settings, schema)[-1][1]["inbox_decision_applied"] is None
        r = decide(client, id="tri-acc", verdict="RESEARCH", note="Ask about the pilot.")
        assert r.json()["inbox_decision"] == "research" and status(settings, schema, "tri-acc") == "reviewing"
    last = rows(settings, schema)[-1]
    assert last[0] == "tri-acc" and last[1]["inbox_decision_applied"] == "research"
    assert last[1]["ts"] == "2026-11-13T10:00:00" and last[1]["note"] == "Ask about the pilot."
    ev_rows = q(settings, schema, "select reason, to_status, detail->>'notes' from {s}.candidate_events "
                "where candidate_id = 'tri-acc' and action = 'status'")  # fmt: skip
    assert ev_rows == [("machine triage: accept", "reviewing", "Ask about the pilot.")]
    raw = q(settings, schema, "select entry::text from {s}.triage_decisions order by seq desc limit 1")[0][0]
    assert raw == triage_log.line(last[1])  # the old line, byte for byte (sorted keys)


def test_an_absorbed_old_id_decides_its_survivor(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()
    with client_of(settings, schema) as client:
        r = decide(client, id="dup-b", verdict="WATCH", mode="override")
    assert r.status_code == 200 and r.json()["inbox_decision"] == "watch"
    assert status(settings, schema, "dup-a") == "watch"
    assert rows(settings, schema) == [("dup-a", rows(settings, schema)[0][1])]
    assert rows(settings, schema)[0][1]["candidate_id"] == "dup-a"


def test_a_stale_expected_status_is_the_decision_routes_409(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()
    before = fingerprint(settings, schema)
    with client_of(settings, schema) as client:
        r = decide(client, id="tri-both", verdict="REJECT", expected_status="watch")
    assert r.status_code == 409
    assert r.json() == {
        "ok": False,
        "error": "the candidate changed meanwhile; reload and decide again",
        "current": "new",
    }
    assert fingerprint(settings, schema) == before


# ------------------------------------------------------------------ revision 2: KEEP racing a status change
def test_keep_racing_a_status_change_that_commits_first_gets_the_409(
    settings: Settings, world: Callable[..., str]
) -> None:
    schema = world()
    out: dict[str, Any] = {}
    with client_of(settings, schema) as client:

        def keep() -> None:
            out["r"] = decide(client, id="tri-keep", verdict="KEEP", expected_status="new")

        with transaction(settings.db_url) as conn:  # the competing decision holds both locks, then commits
            DealFlowStore(conn, schema).decide("tri-keep", "watch", reason="competing tab")
            t = threading.Thread(target=keep)
            t.start()
            time.sleep(1.5)
            assert t.is_alive()  # the KEEP waits on the company lock
        t.join(30)
    r = out["r"]
    assert r.status_code == 409 and r.json()["current"] == "watch" and "open_keep" not in r.json()
    assert rows(settings, schema) == [] and status(settings, schema, "tri-keep") == "watch"


def test_a_committed_keep_line_makes_a_batch_skip_the_candidate(settings: Settings, world: Callable[..., str]) -> None:
    cands = [ptd._c("kp-1", "Ondrel Glassworks", "Ondrel Glassworks runs a glass shop.")]
    schema = world(docs_of(cands))
    with client_of(settings, schema) as client:
        assert decide(client, id="kp-1", verdict="KEEP", mode="override").json()["open_keep"] is True
    assert confirm(settings, schema, ["kp-1"]) == {"ok": True, "applied": 0, "skipped": {td.ALREADY_DECIDED: 1}}
    assert status(settings, schema, "kp-1") == "new" and len(rows(settings, schema)) == 1


# ------------------------------------------------------------------ the batch
def test_a_duplicate_alias_decides_the_survivor_once(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()
    with client_of(settings, schema) as client:
        preview = client.post("/api/deal-flow/triage/batch_reject", json={"ids": ["dup-b", "dup-a"]}).json()
        assert preview == {"ok": True, "preview": True, "eligible": 1, "skipped": {td.SAME_CANDIDATE: 1}}
        r = client.post("/api/deal-flow/triage/batch_reject", json={"ids": ["dup-b", "dup-a"], "confirm": True})
    assert r.json() == {"ok": True, "applied": 1, "skipped": {td.SAME_CANDIDATE: 1}}
    assert [c for c, _ in rows(settings, schema)] == ["dup-a"] and status(settings, schema, "dup-a") == "rejected"
    ev = q(
        settings, schema, "select reason from {s}.candidate_events where candidate_id = 'dup-a' and action = 'status'"
    )
    assert ev == [("machine triage: batch_accept",)]


def test_a_candidate_decided_after_the_preview_is_skipped(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()
    with client_of(settings, schema) as client:
        preview = client.post("/api/deal-flow/triage/batch_reject", json={"ids": ["tri-both", "tri-both2"]}).json()
        assert preview["eligible"] == 2
        assert client.post("/api/deal-flow/candidates/tri-both/decision", json={"status": "watch"}).status_code == 200
        r = client.post("/api/deal-flow/triage/batch_reject", json={"ids": ["tri-both", "tri-both2"], "confirm": True})
    assert r.json() == {"ok": True, "applied": 1, "skipped": {td.ALREADY_DECIDED: 1}}
    assert status(settings, schema, "tri-both") == "watch" and status(settings, schema, "tri-both2") == "rejected"


def test_a_moved_company_refuses_the_whole_confirm(
    settings: Settings, world: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = world()
    real = DealFlowStore._rows
    moved: list[str] = []

    def peek_then_move(self: DealFlowStore, query: str, params: Any = ()) -> list[dict[str, Any]]:
        out = real(self, query, params)
        if query.startswith("select id, company_id from {s}.candidates") and not moved:
            with connect(settings.db_url, autocommit=True) as other:  # a merge commits between the peek and the lock
                new = other.execute(sql.SQL("insert into {}.companies (name) values ('Invented Moved Co') returning id")
                                    .format(sql.Identifier(schema))).fetchone()  # fmt: skip
                assert new is not None
                other.execute(sql.SQL("update {}.candidates set company_id = %s where id = 'tri-both2'")
                              .format(sql.Identifier(schema)), (new[0],))  # fmt: skip
            moved.append("tri-both2")
        return out

    monkeypatch.setattr(DealFlowStore, "_rows", peek_then_move)
    before = q(settings, schema, "select count(*) from {s}.triage_decisions")
    with client_of(settings, schema) as client:
        r = client.post("/api/deal-flow/triage/batch_reject", json={"ids": ["tri-both", "tri-both2"], "confirm": True})
    assert moved and r.status_code == 409
    assert r.json() == {
        "ok": False,
        "error": "the candidate moved to another company meanwhile; reload and decide again",
    }
    assert q(settings, schema, "select count(*) from {s}.triage_decisions") == before
    assert status(settings, schema, "tri-both") == "new" and status(settings, schema, "tri-both2") == "new"


def test_a_failure_on_the_third_line_rolls_the_whole_batch_back(
    settings: Settings, world: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    names = ["Pellow Bricks", "Quarrington Mills", "Rusholme Dairy", "Sallow Timber", "Tredegar Cement"]
    cands = [ptd._c(f"at-{i}", n, f"{n} is a regional trade business.") for i, n in enumerate(names)]
    schema = world(docs_of(cands))
    before = fingerprint(settings, schema)
    needle = "t.line::json"  # review 035d: the lines are ONE insert; a real database error on its third row
    assert triage_log._INSERT_MANY.count(needle) == 1
    monkeypatch.setattr(triage_log, "_INSERT_MANY", triage_log._INSERT_MANY.replace(
        needle, "(case when t.ord = 3 then (1 / 0)::text else t.line end)::json"))  # fmt: skip
    with client_of(settings, schema, raise_server_exceptions=False) as client:
        r = client.post("/api/deal-flow/triage/batch_reject", json={"ids": [c["id"] for c in cands], "confirm": True})
    assert r.status_code == 500
    assert fingerprint(settings, schema) == before  # all five statuses unchanged, no line


# ------------------------------------------------------------------ H-348: concurrency
def crossing_world() -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Companies A (Mirelle) and B (Norrland), each an open candidate and a rejected sibling (one invented DUNS per
    company). Sorting each batch by candidate id gives OPPOSITE company orders: batch 1 = [a0, b1] is A then B,
    batch 2 = [b0, a1] is B then A."""
    a, b = {"duns": "111111111"}, {"duns": "222222222"}
    desc = "{} is a regional freight business."
    cands = [
        ptd._c("cx-1", "Mirelle Freight", desc.format("Mirelle Freight"), entity_ids=a, decision="rejected"),  # a0
        ptd._c("cx-2", "Norrland Tiles", desc.format("Norrland Tiles"), entity_ids=b),  # b1
        ptd._c("cx-3", "Norrland Tiles", desc.format("Norrland Tiles"), entity_ids=b, decision="rejected"),  # b0
        ptd._c("cx-4", "Mirelle Freight", desc.format("Mirelle Freight"), entity_ids=a),  # a1
    ]
    return docs_of(cands), {"batch1": ["cx-1", "cx-2"], "batch2": ["cx-3", "cx-4"]}


def slow_locks(monkeypatch: pytest.MonkeyPatch, seconds: float = 1.0) -> None:
    """Hold the batch's locks a moment, so a concurrent confirm is really waiting on them."""
    real = DealFlowStore.lock_for_triage_batch

    def held(self: DealFlowStore, ids: list[str]) -> dict[str, dict[str, Any]]:
        out = real(self, ids)
        time.sleep(seconds)
        return out

    monkeypatch.setattr(DealFlowStore, "lock_for_triage_batch", held)


def run_together(*jobs: Callable[[], Any]) -> list[Any]:
    barrier = threading.Barrier(len(jobs))
    out: list[Any] = [None] * len(jobs)

    def run(i: int, job: Callable[[], Any]) -> None:
        barrier.wait()
        try:
            out[i] = job()
        except Exception as exc:  # surfaced by the asserts
            out[i] = exc

    threads = [threading.Thread(target=run, args=(i, j)) for i, j in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    return out


def test_overlapping_batches_through_different_candidates_finish_without_deadlock(
    settings: Settings, world: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    docs, batches = crossing_world()
    schema = world(docs)
    company = {str(i): str(c) for i, c in q(settings, schema, "select id, company_id from {s}.candidates")}
    a, b = company["cx-1"], company["cx-2"]
    assert company["cx-4"] == a and company["cx-3"] == b and a != b  # two candidates per company
    assert [company[i] for i in sorted(batches["batch1"])] == [a, b]  # the fixture's crossing, asserted
    assert [company[i] for i in sorted(batches["batch2"])] == [b, a]
    slow_locks(monkeypatch)
    r1, r2 = run_together(lambda: confirm(settings, schema, batches["batch1"]),
                          lambda: confirm(settings, schema, batches["batch2"]))  # fmt: skip
    assert r1 == {"ok": True, "applied": 1, "skipped": {td.ALREADY_DECIDED: 1}}, r1
    assert r2 == {"ok": True, "applied": 1, "skipped": {td.ALREADY_DECIDED: 1}}, r2
    assert sorted(c for c, _ in rows(settings, schema)) == ["cx-2", "cx-4"]  # each open candidate exactly once
    assert status(settings, schema, "cx-2") == "rejected" and status(settings, schema, "cx-4") == "rejected"
    ev = q(settings, schema, "select candidate_id, count(*) from {s}.candidate_events where action = 'status' "
           "and reason = 'machine triage: batch_accept' group by 1 order by 1")  # fmt: skip
    assert ev == [("cx-2", 1), ("cx-4", 1)]


def test_two_confirms_of_the_same_open_candidate_write_one_line(
    settings: Settings, world: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    docs, _ = crossing_world()
    schema = world(docs)
    slow_locks(monkeypatch)
    out = run_together(lambda: confirm(settings, schema, ["cx-4"]), lambda: confirm(settings, schema, ["cx-4"]))
    assert sorted(out, key=lambda r: -r["applied"]) == [
        {"ok": True, "applied": 1, "skipped": {}},
        {"ok": True, "applied": 0, "skipped": {td.ALREADY_DECIDED: 1}},
    ], out
    assert [c for c, _ in rows(settings, schema)] == ["cx-4"]


# ------------------------------------------------------------------ the boundaries
# ------------------------------------------------------------------ H-351: the batch request at the HTTP boundary
@pytest.mark.parametrize("value", ["false", "true", 1, 0, None, [], {}])
def test_only_a_literal_true_applies_a_batch(settings: Settings, world: Callable[..., str], value: Any) -> None:
    """A malformed ``confirm`` (the string "false" above all) is a 400 and changes nothing: no status, event or line."""
    schema = world()
    before = fingerprint(settings, schema)
    with client_of(settings, schema) as client:
        r = client.post("/api/deal-flow/triage/batch_reject", json={"ids": ["tri-both", "tri-both2"], "confirm": value})
        assert (r.status_code, r.json()) == (400, {"ok": False, "error": "confirm must be true or false"})
        for body in ({"ids": ["tri-both", "tri-both2"], "confirm": False}, {"ids": ["tri-both", "tri-both2"]}):
            p = client.post("/api/deal-flow/triage/batch_reject", json=body)
            assert p.status_code == 200 and p.json()["preview"] is True and p.json()["eligible"] == 2
    assert fingerprint(settings, schema) == before


def test_the_preview_reads_one_snapshot_across_a_concurrent_edit(
    settings: Settings, world: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The preview opens ONE read-only snapshot before its first query: a decision committed by another writer between
    its alias resolution and its view read stays invisible to it (under READ COMMITTED it would count as decided)."""
    schema = world()
    real = DealFlowStore.resolve_many
    edited: list[str] = []

    def resolve_then_edit(self: DealFlowStore, ids: list[str]) -> Any:
        out = real(self, ids)
        if not edited:  # another writer commits right after the preview's first read
            with transaction(settings.db_url) as other:
                DealFlowStore(other, schema).decide("tri-both", "watch", expected_status="new")
            edited.append("tri-both")
        return out

    monkeypatch.setattr(DealFlowStore, "resolve_many", resolve_then_edit)
    with client_of(settings, schema) as client:
        p = client.post("/api/deal-flow/triage/batch_reject", json={"ids": ["tri-both", "tri-both2"]}).json()
    assert edited == ["tri-both"] and status(settings, schema, "tri-both") == "watch"  # the edit committed
    assert p == {"ok": True, "preview": True, "eligible": 2, "skipped": {}}  # the snapshot from before it


def test_nothing_is_written_before_the_import(
    settings: Settings, world: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = world()
    with transaction(settings.db_url) as conn:  # the import marker goes: this scratch schema is "before the import"
        conn.execute(sql.SQL("delete from {}.documents where key = 'ops/legacy_import'").format(sql.Identifier(schema)))

    def guarded(conn: psycopg.Connection[Any], s: str, *, live: str = "pz") -> None:
        ensure_intake_open(conn, s, live=s)  # the production guard, pointed at this scratch name

    monkeypatch.setattr(td, "ensure_intake_open", guarded)
    before = fingerprint(settings, schema)
    with client_of(settings, schema) as client:
        r = decide(client, id="tri-keep", verdict="KEEP")
        assert r.status_code == 409 and "legacy import" in r.json()["error"]
        r = client.post("/api/deal-flow/triage/batch_reject", json={"ids": ["tri-both"], "confirm": True})
        assert r.status_code == 409 and "legacy import" in r.json()["error"]
        preview = client.post("/api/deal-flow/triage/batch_reject", json={"ids": ["tri-both"]})
        assert preview.status_code == 200 and preview.json()["eligible"] == 1  # the preview only reads
    assert fingerprint(settings, schema) == before


def test_no_route_touches_the_model_ledger(settings: Settings, world: Callable[..., str]) -> None:
    schema = world()
    ledger = "select count(*), coalesce(max(id), 0) from {s}.model_ledger"
    before = q(settings, schema, ledger)
    with client_of(settings, schema) as client:
        for body in ({"id": "tri-acc", "verdict": "RESEARCH"}, {"id": "tri-ovr", "verdict": "WATCH", "mode": "override"},
                     {"id": "tri-keep", "verdict": "KEEP"}, {"id": "tri-veto", "verdict": "REJECT", "mode": "override"},
                     {"id": "tri-human", "verdict": "BAD"}):  # fmt: skip
            decide(client, **body)
        client.post("/api/deal-flow/triage/batch_reject", json={"ids": ["tri-both", "tri-s0"]})
        client.post("/api/deal-flow/triage/batch_reject", json={"ids": ["tri-both", "tri-s0"], "confirm": True})
        assert client.get("/api/deal-flow/triage").status_code == 200
    assert q(settings, schema, ledger) == before
    assert len(rows(settings, schema)) == 6


# ------------------------------------------------------------------ the readers
def test_the_view_and_validation_read_the_archive_then_the_rows_per_survivor(
    settings: Settings, world: Callable[..., str]
) -> None:
    schema = world()  # archived: dup-b (absorbed into dup-a) WATCH, tri-gone KEEP, tri-human RESEARCH
    with client_of(settings, schema) as client:
        v0 = client.get("/api/deal-flow/triage").json()
        assert v0["calibration"]["decisions"] == 3  # survivors: dup-a, tri-gone, tri-human
        assert v0["proposals"]["dup-a"]["mohamed"]["verdict"] == "WATCH"  # the absorbed id's archived line
        val0 = client.get("/api/validation").json()["calibration"]
        assert val0["decisions"] == 3
        decide(client, id="dup-a", verdict="REJECT", mode="accept")  # the survivor re-decided: a new line
        v1 = client.get("/api/deal-flow/triage").json()
        val1 = client.get("/api/validation").json()["calibration"]
    assert v1["calibration"]["decisions"] == 3  # counted once, the new line wins
    assert v1["proposals"]["dup-a"]["mohamed"] == {"verdict": "REJECT", "mode": "accept", "at": "2026-11-13T10:00:00",
                                                   "agreed": True}  # fmt: skip
    assert v1["calibration"]["matrix_machine_to_mohamed"]["REJECT"] == {"REJECT": 1}
    assert val1["decisions"] == 3 and val1["matrix"]["REJECT"] == {"REJECT": 1}
    assert rows(settings, schema)[0][1]["candidate_id"] == "dup-a"


def test_a_pure_refusal_never_opens_a_connection(
    settings: Settings, world: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = world()
    import projectzero.api.routers.dealflow_triage as router

    def no_db(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a connection was opened")

    monkeypatch.setattr(router, "transaction", no_db)
    with client_of(settings, schema) as client:
        assert decide(client, id="x", verdict="NOPE").json()["error"].startswith("verdict must be one of")
        assert client.post("/api/deal-flow/triage/batch_reject", json={"ids": "x"}).status_code == 400
        assert client.post("/api/deal-flow/triage/batch_reject", content=b"[1]").status_code == 400
    with pytest.raises(DecisionError), transaction(settings.db_url) as conn:
        DealFlowStore(conn, schema).lock_for_triage("tri-keep", "watch")
