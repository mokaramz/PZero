"""Feedback ledger from decision events (review 008): step-by-step parity with the OLD record_decision, and the
merged-candidate rules (absorbed ids, linked Omar outcomes) asserted by hand."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from projectzero.dealflow.ranking import feedback, ledger
from projectzero.ops import parity_feedback

GOLDEN = json.loads(parity_feedback.GOLDEN.read_text(encoding="utf-8"))


def test_goldens_come_from_the_clean_old_revision_and_the_current_corpus() -> None:
    assert GOLDEN["provenance"]["old_revision"] == "6c739b9cb6ca2517b845e381d39a36c50eccc59e"
    assert GOLDEN["provenance"]["old_dirty"] is False
    assert GOLDEN["corpus"] == json.loads(json.dumps(parity_feedback.corpus()))


def test_every_step_matches_the_old_write_path() -> None:
    assert parity_feedback.compare(GOLDEN["expected"], parity_feedback.run_new(GOLDEN["corpus"])) == []


def test_the_script_reaches_the_sensitive_rules() -> None:
    steps = GOLDEN["expected"]
    assert steps[0]["table"]["src-a"]["active"] is True  # the fifth unique company activates src-a
    assert steps[4]["entry"] is None and "new-7" not in steps[4]["decision_keys"]  # no sources: nothing recorded
    assert "imp-3" in steps[5]["decision_keys"]  # undo without sources keeps the imported vote
    assert "new-5" in steps[6]["decision_keys"]  # ... and an earlier event's vote
    assert "imp-2" not in steps[3]["decision_keys"] and steps[12]["decision_keys"][-1] == "imp-2"  # moved to the end
    capped = steps[11]["probes"]["new-6"]  # src-a +2 and src-b +2 add up to 4, capped to 3
    assert sum(s["adjustment"] for s in capped["sources"]) == 4 and capped["adjustment"] == feedback.CAP
    assert steps[13]["decisions"] == steps[12]["decisions"]  # an identical repeat changes no vote


def test_no_events_reads_the_imported_ledger_unchanged() -> None:
    base = GOLDEN["corpus"]["base"]
    assert ledger.effective(base, []) is base
    assert ledger.effective(None, []) is None  # a missing ledger stays "no ledger"


def test_events_without_a_snapshot_or_with_empty_sources_change_nothing() -> None:
    base = GOLDEN["corpus"]["base"]
    before = feedback.normalize(base)
    events = [{"candidate_id": "imp-1", "detail": {}, "at": None},
              {"candidate_id": "imp-1", "detail": {"notes": "only a note"}, "at": None},
              {"candidate_id": "imp-1", "detail": {"feedback": {"decision": "new", "source_ids": [], "keys": ["imp-1"]}},
               "at": None}]  # fmt: skip
    assert ledger.effective(base, events) == before


def test_parse_base_keeps_the_old_key_order_and_falls_back() -> None:
    raw = '﻿{"decisions": {"zz": {"decision": "kept"}, "aa": {"decision": "watch"}}}'.encode()
    assert list(ledger.parse_base(raw, {"x": 1})["decisions"]) == ["zz", "aa"]
    assert ledger.parse_base(b"not json", {"x": 1}) == {"x": 1}
    assert ledger.parse_base(None, None) is None


# ── merged candidates: a survivor that absorbed an old inbox record ─────────────────────────────────────────────


def merged_base() -> dict[str, Any]:
    return {
        "decisions": {
            "abs-1": {"source_ids": ["src-m"], "decision": "kept", "name": "Merged Co", "ts": "t", "by": "Mohamed"},
            "surv": {"source_ids": ["src-m"], "decision": "watch", "name": "Merged Co", "ts": "t", "by": "Mohamed"},
            "other": {"source_ids": ["src-m"], "decision": "research", "name": "Other", "ts": "t", "by": "Mohamed"},
        },
        "omar": {"merged-co": {"source_ids": ["src-m"], "outcome": "negative", "company": "Merged Co",
                               "candidate_id": "abs-1"}},
    }  # fmt: skip


def event(decision: str, sids: list[str], keys: list[str] | None = None) -> dict[str, Any]:
    rec = {"decision": decision, "source_ids": sids, "name": "Merged Co", "keys": keys or ["surv", "abs-1"]}
    return {"candidate_id": "surv", "detail": {"feedback": rec}, "at": "2026-11-11 12:00:00"}


def rows(d: Any) -> dict[str, dict[str, Any]]:
    return feedback.company_rows("src-m", feedback.normalize(d))


def test_before_any_decision_the_imported_merge_reads_as_imported() -> None:
    assert set(rows(ledger.effective(merged_base(), []))) == {"abs-1", "surv", "other"}  # as the old file counted


def test_a_decision_through_the_survivor_drops_the_absorbed_vote_and_relinks_omar() -> None:
    d = ledger.effective(merged_base(), [event("rejected", ["src-m"])])
    assert list(d["decisions"]) == ["surv", "other"]
    assert d["decisions"]["surv"]["decision"] == "rejected"
    assert d["omar"]["merged-co"]["candidate_id"] == "surv"
    r = rows(d)
    assert set(r) == {"surv", "other"}  # one company, counted once
    assert r["surv"] == {"decision": "rejected", "omar": "negative", "name": "Merged Co"}
    assert feedback.source_stats("src-m", feedback.normalize(d))["reviewed"] == 2


def test_undo_through_the_survivor_removes_every_vote_of_the_company() -> None:
    d = ledger.effective(merged_base(), [event("rejected", ["src-m"]), event("new", ["src-m"])])
    assert list(d["decisions"]) == ["other"]
    r = rows(d)
    assert r["surv"] == {"decision": None, "omar": "negative", "name": "Merged Co"}  # Omar's outcome stays linked
    assert feedback.source_stats("src-m", feedback.normalize(d))["reviewed"] == 2


def test_undo_with_no_sources_keeps_the_merged_votes() -> None:
    d = ledger.effective(merged_base(), [event("new", [])])
    assert d == feedback.normalize(merged_base())


@pytest.mark.parametrize("keys", [["surv"], ["surv", "abs-1"], ["surv", "abs-1", "never-voted"]])
def test_only_the_snapshot_keys_are_touched(keys: list[str]) -> None:
    d = ledger.effective(copy.deepcopy(merged_base()), [event("watch", ["src-m"], keys)])
    assert "other" in d["decisions"]
    assert ("abs-1" in d["decisions"]) is ("abs-1" not in keys)


# ── pre-008 status events (no snapshot): the compatibility fallback (H-058) ─────────────────────────────────────


def imported_row(cid: str, status: str, source_id: str = "src-m") -> dict[str, Any]:
    legacy = {"id": cid, "name": "Merged Co", "decision": "watch", "discovery_tier": "registry", "source_id": source_id}
    return {"id": cid, "status": status, "legacy": legacy, "attrs": {}}


def test_a_historical_undo_without_a_snapshot_removes_the_imported_votes() -> None:
    from projectzero.dealflow.ranking.service import backfill_snapshots

    events = [{"candidate_id": "surv", "to_status": "new", "detail": {}, "at": None}]
    filled = backfill_snapshots(events, {"surv": imported_row("surv", "new")}, {"surv": ["abs-1", "surv"]})
    assert filled[0]["detail"]["feedback"] == {"decision": "new", "source_ids": ["src-m"], "name": "Merged Co",
                                               "keys": ["surv", "abs-1"]}  # fmt: skip
    d = ledger.effective(merged_base(), filled)
    assert list(d["decisions"]) == ["other"]  # both the survivor's and the absorbed imported votes are gone
    assert d["omar"]["merged-co"]["candidate_id"] == "surv"


def test_backfill_maps_the_recorded_status_and_keeps_recorded_snapshots() -> None:
    from projectzero.dealflow.ranking.service import backfill_snapshots

    recorded = {"candidate_id": "surv", "to_status": "watch", "at": None,
                "detail": {"feedback": {"decision": "watch", "source_ids": [], "name": "Merged Co", "keys": ["surv"]}}}  # fmt: skip
    historical = {"candidate_id": "surv", "to_status": "reviewing", "detail": {"notes": "n"}, "at": None}
    unknown = {"candidate_id": "gone", "to_status": "new", "detail": {}, "at": None}
    out = backfill_snapshots([recorded, historical, unknown], {"surv": imported_row("surv", "reviewing")}, {})
    assert out[0] is recorded  # an explicitly empty source list is a recorded value: untouched
    assert out[1]["detail"] == {"notes": "n", "feedback": {"decision": "research", "source_ids": ["src-m"],
                                                           "name": "Merged Co", "keys": ["surv"]}}  # fmt: skip
    assert out[2] is unknown  # no row to rebuild from: left as it is (and ignored by the replay)
    assert ledger.effective(merged_base(), [recorded]) == feedback.normalize(merged_base())
