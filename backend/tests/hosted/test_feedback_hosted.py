"""Review 008 through the PRODUCTION path: HTTP decisions -> status events -> effective ledger -> feedback in the
decide response, the list and the detail. Scratch schemas only (``scripts/db.ps1 itest``)."""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

import pytest
from tests.hosted.test_ranking_hosted import all_items, client_for, schema, settings, store_as_imported

from projectzero.core.config import Settings
from projectzero.core.db import connect
from projectzero.dealflow.ranking import feedback, ledger

pytestmark = pytest.mark.hosted
__all__ = ["schema", "settings"]  # fixtures re-used from the ranking suite
LAST_RUN = "2026-11-08 19:09:09"


def vote(sids: list[str], decision: str, name: str) -> dict[str, Any]:
    return {"source_ids": sids, "decision": decision, "name": name, "ts": "2026-11-01 10:00:00", "by": "Mohamed"}


def rec(cid: str, name: str, source_id: str, decision: str) -> dict[str, Any]:
    return {"id": cid, "name": name, "decision": decision, "discovery_tier": "registry", "source_id": source_id,
            "source": "Oracle source", "description": "Builds tools."}  # fmt: skip


def archive_ledger(settings: Settings, schema: str, base: dict[str, Any]) -> None:
    raw = json.dumps(base, indent=1).encode()
    with connect(settings.db_url, autocommit=True) as conn:
        conn.execute(
            f"insert into {schema}.legacy_documents (path, sha256, bytes, raw) values (%s, %s, %s, %s)".encode(),
            (ledger.LEDGER_FILE, hashlib.sha256(raw).hexdigest(), len(raw), raw),
        )


def status_events(settings: Settings, schema: str) -> list[tuple[Any, ...]]:
    with connect(settings.db_url, autocommit=True) as conn:
        return conn.execute(
            f"select candidate_id, detail from {schema}.candidate_events where action = 'status' order by id".encode()
        ).fetchall()


def expected_feedback(base: Any, settings: Settings, schema: str, c: dict[str, Any]) -> dict[str, Any]:
    events = [{"candidate_id": cid, "detail": d, "at": None} for cid, d in status_events(settings, schema)]
    return feedback.for_candidate(c, feedback.table(ledger.effective(base, events)))


def seed_imported(settings: Settings, schema: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    records = {r["id"]: r for r in [
        rec("imp-1", "One", "src-a", "rejected"), rec("imp-2", "Two", "src-a", "kept"),
        rec("imp-3", "Three", "src-a", "research"), rec("imp-4", "Four", "src-a", "watch"),
        rec("new-5", "Five", "src-a", "new"), rec("new-6", "Six", "src-a", "new"),
    ]}  # fmt: skip
    base = {"decisions": {cid: vote(["src-a"], r["decision"], r["name"]) for cid, r in records.items()
                          if r["decision"] != "new"}, "omar": {}}  # fmt: skip
    store_as_imported(settings, schema, list(records.values()), LAST_RUN, base)
    archive_ledger(settings, schema, base)
    return base, records


def test_http_decisions_move_the_feedback_like_the_old_ledger(settings: Settings, schema: str) -> None:
    base, records = seed_imported(settings, schema)
    with client_for(settings, schema) as client:
        before = client.get("/api/deal-flow/candidates/new-5").json()["ranking"]["feedback"]
        assert before["active"] is False and before["sources"][0]["reviewed"] == 4

        got = client.post("/api/deal-flow/candidates/new-5/decision", json={"status": "reviewing"}).json()
        assert got["changed"] is True and got["feedback"]["active"] is True  # the fifth company
        assert got["feedback"] == expected_feedback(base, settings, schema, records["new-5"])
        ((_, detail),) = status_events(settings, schema)
        assert detail["feedback"] == {"decision": "research", "source_ids": ["src-a"], "name": "Five",
                                      "keys": ["new-5"]}  # fmt: skip
        items = all_items(client)
        assert items["imp-1"]["ranking"]["feedback"] == got["feedback"]  # every src-a candidate moved

        again = client.post("/api/deal-flow/candidates/new-5/decision", json={"status": "reviewing"}).json()
        assert again["changed"] is False and again["feedback"] == got["feedback"]  # current feedback, no 2nd vote
        noted = client.post("/api/deal-flow/candidates/new-5/decision",
                            json={"status": "reviewing", "notes": "call next week"}).json()  # fmt: skip
        assert noted["feedback"] == got["feedback"] and len(status_events(settings, schema)) == 1

        undo = client.post("/api/deal-flow/candidates/imp-2/decision", json={"status": "new"}).json()
        assert undo["feedback"]["active"] is False and undo["feedback"]["sources"][0]["reviewed"] == 4
        assert undo["feedback"] == expected_feedback(base, settings, schema, records["imp-2"])
        assert client.get("/api/deal-flow/candidates/new-6").json()["ranking"]["feedback"] == undo["feedback"]


def test_a_decision_through_an_absorbed_id_counts_the_company_once(settings: Settings, schema: str) -> None:
    others = [rec(f"m-{i}", f"Other {i}", "src-m", "research") for i in range(4)]
    survivor = rec("surv", "Merged Co", "src-m", "watch")
    base = {"decisions": {"abs-1": vote(["src-m"], "kept", "Merged Co"), "surv": vote(["src-m"], "watch", "Merged Co")}
            | {o["id"]: vote(["src-m"], "research", o["name"]) for o in others},
            "omar": {"merged-co": {"source_ids": ["src-m"], "outcome": "negative", "company": "Merged Co",
                                   "candidate_id": "abs-1"}}}  # fmt: skip
    store_as_imported(settings, schema, [survivor, *others], LAST_RUN, base)
    archive_ledger(settings, schema, base)
    with connect(settings.db_url, autocommit=True) as conn:
        conn.execute(
            f"insert into {schema}.candidate_aliases (namespace, alias_id, candidate_id, reason) "
            "values ('candidate', 'abs-1', 'surv', 'merge')".encode()
        )

    def src_m(fb: dict[str, Any]) -> dict[str, Any]:
        return next(s for s in fb["sources"] if s["source_id"] == "src-m")

    with client_for(settings, schema) as client:
        before = client.get("/api/deal-flow/candidates/surv").json()["ranking"]["feedback"]
        assert src_m(before)["reviewed"] == 6  # imported as it was: the absorbed vote still counts on its own

        got = client.post("/api/deal-flow/candidates/abs-1/decision", json={"status": "rejected"}).json()
        assert got["id"] == "surv" and got["resolved_from"] == {"namespace": "candidate", "id": "abs-1"}
        ((_, detail),) = status_events(settings, schema)
        assert detail["feedback"]["keys"] == ["surv", "abs-1"]
        effective = feedback.normalize(ledger.effective(base, [{"candidate_id": "surv", "detail": detail, "at": None}]))
        rows = feedback.company_rows("src-m", effective)
        assert rows["surv"] == {"decision": "rejected", "omar": "negative", "name": "Merged Co"}
        assert "abs-1" not in rows and src_m(got["feedback"])["reviewed"] == 5  # one company, counted once

        undo = client.post("/api/deal-flow/candidates/surv/decision", json={"status": "new"}).json()
        assert src_m(undo["feedback"])["reviewed"] == 5  # the Omar outcome stays, linked to the survivor
        stats = feedback.source_stats("src-m", feedback.normalize(ledger.effective(
            base, [{"candidate_id": c, "detail": d, "at": None} for c, d in status_events(settings, schema)])))  # fmt: skip
        assert (stats["rejected"], stats["omar_negative"], stats["kept"], stats["watch"]) == (0, 1, 0, 0)


def test_concurrent_decisions_on_two_candidates_both_count(settings: Settings, schema: str) -> None:
    base, records = seed_imported(settings, schema)
    barrier = threading.Barrier(2)
    answers: dict[str, Any] = {}

    def decide(cid: str) -> None:
        with client_for(settings, schema) as client:
            barrier.wait()
            answers[cid] = client.post(f"/api/deal-flow/candidates/{cid}/decision", json={"status": "rejected"}).json()

    threads = [threading.Thread(target=decide, args=(cid,)) for cid in ("new-5", "new-6")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(a["changed"] for a in answers.values())
    assert sorted(cid for cid, _ in status_events(settings, schema)) == ["new-5", "new-6"]
    with client_for(settings, schema) as client:
        fb = client.get("/api/deal-flow/candidates/imp-1").json()["ranking"]["feedback"]
    assert fb["sources"][0]["reviewed"] == 6
    assert fb == expected_feedback(base, settings, schema, records["imp-1"])


def test_a_historical_undo_event_removes_the_imported_vote_in_list_and_detail(settings: Settings, schema: str) -> None:
    seed_imported(settings, schema)
    with client_for(settings, schema) as client:
        new_5 = client.post("/api/deal-flow/candidates/new-5/decision", json={"status": "reviewing"}).json()
    assert new_5["feedback"]["active"] is True  # 5 reviewed companies
    with connect(settings.db_url, autocommit=True) as conn:  # an operator undo recorded before 008: no snapshot
        conn.execute(f"update {schema}.candidates set status = 'new' where id = 'imp-2'".encode())
        conn.execute(
            f"insert into {schema}.candidate_events (candidate_id, actor, action, from_status, to_status, detail) "
            "values ('imp-2', 'operator', 'status', 'kept', 'new', '{}')".encode()
        )
    with client_for(settings, schema) as client:
        detail = client.get("/api/deal-flow/candidates/imp-1").json()["ranking"]["feedback"]
        listed = all_items(client)["imp-1"]["ranking"]["feedback"]
    assert detail == listed
    assert detail["active"] is False and detail["sources"][0]["reviewed"] == 4  # the imported imp-2 vote is gone
