"""Offline rules of the Conviction port: the save / status rules, the read model built from in-memory inputs (reads
never write), the loader's failure semantics, the record overlay and order, and the server side of the three client
preview differences (decision c)."""

from __future__ import annotations

import copy
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from projectzero.conviction import entries, imq, operator, pipeline, taste
from projectzero.conviction.inputs import UNREADABLE, inputs_from
from projectzero.conviction.store import ordered, record_of

NOW = datetime(2026, 11, 11, 12, 0, 0)
TODAY = NOW.date()


# ── validate_entry ──────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("body", "problem"),
    [
        ({"company": " "}, "company name is empty"),
        ({"scores": {"founder": 26}}, "score 'founder' = 26 is outside 0–25"),
        ({"scores": {"venture_scale": 21}}, "score 'venture_scale' = 21 is outside 0–20"),
        ({"scores": {"why_now": 16}}, "score 'why_now' = 16 is outside 0–15"),
        ({"scores": {"taste": 16}}, "score 'taste' = 16 is outside 0–15"),
        ({"scores": {"insight": 11}}, "score 'insight' = 11 is outside 0–10"),
        ({"scores": {"custom": -1}}, "score 'custom' = -1 is outside 0–…"),
        ({"scores": {"founder": "x"}}, "score 'founder' is not a number"),
        ({"scores": [1]}, "scores must be a set of numbers"),
        ({"verified": {"founders": "yes"}}, "verified flags must be yes / no"),
        ({"verified": [True]}, "verified flags must be yes / no"),
        ({"discovery_date": "2026-11-12"}, "signal date 2026-11-12 is in the future"),
        ({"discovery_date": "11/01/2026"}, "signal date '11/01/2026' is not a date (YYYY-MM-DD)"),
        ({"status": "won"}, "status 'won' is not one of new, contacted, replied, forwarded, dropped"),
        ({"conflict": "maybe"}, "conflict 'maybe' is not a known value"),
        ({"archetype": 16}, "archetype 16 does not exist"),
        ({"archetype": -1}, "archetype -1 does not exist"),
        ({"archetype": "x"}, "archetype must be a number"),
        ({"founders": 5}, "founders must be a list of names"),
    ],
)
def test_each_refusal(body: dict[str, Any], problem: str) -> None:
    assert entries.validate_entry(body, TODAY) == [problem]


def test_the_limits_themselves_and_today_are_accepted() -> None:
    ok = {"company": "Fine", "scores": {"founder": 25, "venture_scale": 20, "why_now": 15, "taste": 15, "insight": 10},
          "verified": {"founders": True, "traction": False}, "discovery_date": TODAY.isoformat(), "archetype": 15,
          "conflict": "", "status": "forwarded", "founders": "Jane"}  # fmt: skip
    assert entries.validate_entry(ok, TODAY) == []
    assert entries.validate_entry({"archetype": 0, "scores": {"founder": 0}}, TODAY) == []
    assert entries.refusal(["a", "b"]) == "Not saved — a; b. Nothing was changed."


# ── save / status ───────────────────────────────────────────────────────────────────────────────────────────────
def test_a_partial_save_merges_and_never_clears_absent_fields() -> None:
    """The checklist sends {slug, company, verified}: every other field stays as it was (old save_entry)."""
    rec = {"company": "Acme", "status": "contacted", "scores": {"founder": 20}, "bull": "strong", "outreach": [1]}
    after = copy.deepcopy(rec)
    entries.apply_save(after, {"slug": "acme", "company": "Acme", "verified": {"founders": True}})
    assert after == rec | {"verified": {"founders": True}}
    assert "slug" not in after  # only the SAVE_FIELDS are stored


def test_save_cleans_founders_and_ignores_unknown_keys() -> None:
    rec: dict[str, Any] = {"status": "new"}
    entries.apply_save(rec, {"company": "A", "founders": ["Jane", "", None, {"name": " "}, {"name": "Max"}],
                             "sc": {"provisional": 99}, "imq": {"state": "x"}, "inbox_id": "c1"})  # fmt: skip
    assert rec == {"status": "new", "company": "A", "founders": [{"name": "Jane"}, {"name": "Max"}]}


def test_provenance_of_a_kept_candidate() -> None:
    rec: dict[str, Any] = {}
    cx = {"id": "old", "source_id": "src-a", "quality_source_id": "src-q", "all_source_ids": ["src-b", "src-a"],
          "run_id": "2026-11-08 19:09:09", "first_seen": "2026-11-08", "source_url": "https://x"}  # fmt: skip
    entries.provenance(rec, cx, "cand-1")
    assert rec == {"source_id": "src-q", "inbox_id": "cand-1", "source_ids": ["src-a", "src-b"],
                   "discovered_run": "2026-11-08 19:09:09", "discovered_first_seen": "2026-11-08",
                   "discovered_source_url": "https://x"}  # fmt: skip


def test_status_dates_the_first_contact_once() -> None:
    rec: dict[str, Any] = {"status": "new"}
    entries.apply_status(rec, "contacted", NOW)
    assert rec["outreach"] == [{"kind": "outreach_sent", "date": "2026-11-11", "channel": "other",
                                "note": "status set to contacted in Conviction", "by": entries.OUTREACH_BY,
                                "recorded": "2026-11-11T12:00:00"}]  # fmt: skip
    entries.apply_status(rec, "new", NOW)
    entries.apply_status(rec, "contacted", NOW)  # back again: the first contact is already dated
    assert len(rec["outreach"]) == 1
    entries.apply_status(rec, "replied", NOW)
    assert [x["kind"] for x in rec["outreach"]] == ["outreach_sent", "reply_received"]
    entries.apply_status(rec, "dropped", NOW)
    assert rec["status"] == "dropped" and len(rec["outreach"]) == 2


def test_changes_lists_only_changed_fields() -> None:
    assert entries.changes({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4}) == ({"b": 2, "c": None}, {"b": 3, "c": 4})
    assert entries.changes({"a": 1}, {"a": 1}) == ({}, {})


# ── the read model ──────────────────────────────────────────────────────────────────────────────────────────────
PEOPLE = [{"id": "p-ada", "name": "Ada Lovelace", "identity_status": "resolved"}]


def qualified(trigger_days_ago: int, **extra: Any) -> dict[str, Any]:
    trig = {"kind": "fundraising", "date": (TODAY - timedelta(days=trigger_days_ago)).isoformat(),
            "url": "https://news.example.com/a", "fact": "raising", "by": "operator"}  # fmt: skip
    return {"company": "Qual GmbH", "status": "new", "archetype": 3, "earliness": "pre_company", "conflict": "none",
            "scores": {"founder": 25, "venture_scale": 19, "why_now": 15, "taste": 15, "insight": 10},
            "verified": {"founders": True, "traction": True, "funding": True},
            "founders": [{"name": "Ada Lovelace"}], "imq_trigger": trig} | extra  # fmt: skip


def build(stored: list[Any], now: datetime = NOW, **docs: Any) -> dict[str, Any]:
    return pipeline.build({"week": "45/2026"}, stored, inputs_from(docs, PEOPLE), now)


def test_reads_never_write_and_time_alone_moves_only_the_display() -> None:
    snap = {"state": imq.QUALIFIED, "qualified_at": "2026-11-01 09:00", "history": [{"on": "2026-11-01 09:00",
            "to": imq.QUALIFIED}]}  # fmt: skip
    stored = [qualified(80, imq=snap)]
    frozen = copy.deepcopy(stored)
    first = build(stored)["signals"][0]
    assert first["imq_eval"]["state"] == imq.QUALIFIED
    later = NOW + timedelta(days=15)  # the trigger is now 95 days old
    for _ in range(2):
        e = build(stored, later)["signals"][0]
        assert e["imq_eval"]["state"] == "IMQ — STALE"
        assert e["imq_eval"]["persisted"] == snap  # the stored snapshot, untouched
    assert stored == frozen  # nothing the read computed reached the stored record
    # the next write stamps the transition ONCE, at the write's clock
    rec = copy.deepcopy(stored[0])
    ev = pipeline.enrich(copy.deepcopy(rec), inputs_from({}, PEOPLE).imq, later)
    assert imq.persist(rec, ev, now=later) is True
    assert rec["imq"]["stale_since"] == later.strftime("%Y-%m-%d %H:%M") and len(rec["imq"]["history"]) == 2
    ev2 = pipeline.enrich(copy.deepcopy(rec), inputs_from({}, PEOPLE).imq, later + timedelta(hours=1))
    assert imq.persist(rec, ev2, now=later + timedelta(hours=1)) is False
    assert len(rec["imq"]["history"]) == 2


def test_view_fields_and_top_level() -> None:
    out = build([{"company": "Acme GmbH", "discovery_date": "2026-11-01", "archetype": 7, "discovered_run": "r1"},
                 {"not": "a record"}, "junk", {"company": "Plain", "archetype": "7"}])  # fmt: skip
    assert out["week"] == "45/2026" and [s["slug"] for s in out["signals"]] == ["acme", "plain"]
    a, b = out["signals"]
    assert a["status"] == "new" and a["days_old"] == 10 and a["archetype_name"].startswith("#7 Industrial autonomy")
    assert a["discovery_status"] == "Discovered by scan r1 (first seen —)"
    assert b["archetype_name"] == "—" and b["discovery_status"] == "Existing pipeline — not discovered in this scan"
    assert set(a["sc"]) >= {"provisional", "verified", "missing", "fully_verified", "verdict", "timing_label"}
    assert a["op"]["source"] == "score band" and isinstance(a["imq_eval"]["blockers"], list)


def test_an_unreadable_value_is_read_neutral_and_flagged() -> None:
    e = build([{"company": "Bad", "scores": {"founder": "", "insight": "7"}, "penalties": ["known", 3]}])["signals"][0]
    assert e["data_warning"].startswith("a stored value could not be read")
    assert e["scores"] == {"founder": 0, "insight": 7} and e["penalties"] == ["known"]
    assert e["sc"]["breakdown"]["founder"] == 0 and e["imq_eval"]["state"] == "NOT YET IMQ"


def test_founder_radar_facts_and_contradictions_reach_imq() -> None:
    radar = {"companies": {"x": {"name": "Qual", "facts": [
        {"field": "recent_activity", "confirmed": True, "activity_date": "2026-11-01", "source_url": "https://q.example",
         "claim": "pilot"}]}}}  # fmt: skip
    evals = {"sessions": {"s1": {"subject": {"slug": "qual"}, "ledger": [
        {"state": "CONTRADICTION", "text": "two different founding dates"}]}}}  # fmt: skip
    e = build([qualified(400, company="Qual")], **{"radar_companies.json": radar, "evaluations.json": evals})
    ev = e["signals"][0]["imq_eval"]
    assert ev["timing"]["established"] and ev["timing"]["kind"] == "recent_activity"
    assert ev["blockers"] == ["C · unresolved contradiction: two different founding dates"]


def test_unreadable_radar_or_evaluations_read_as_empty() -> None:
    inp = inputs_from({"radar_companies.json": UNREADABLE, "evaluations.json": {"sessions": {}}}, [])
    assert inp.imq.radar_companies == {} and inp.imq.evaluations == {"sessions": {}}
    inp = inputs_from({"radar_companies.json": {"companies": {"a": {}}}, "evaluations.json": UNREADABLE}, [])
    assert inp.imq.radar_companies == {} and inp.operator.evaluations == {}
    inp = inputs_from({"case_prep/cases.json": UNREADABLE, "founder_calls.json": [1]}, [])
    assert inp.operator.cases == {} and inp.operator.founder_calls == [1]


def test_operator_status_priority() -> None:
    now = NOW
    case = {"card": {"next_action": {"code": "CONTACT_FOUNDER", "label": "Contact the founders (you send)",
            "why": "w"}, "conflict": {"gated": False}, "decisions": []}, "prepared_at": "2026-11-10T09:00:00"}  # fmt: skip
    e = {"company": "Acme", "slug": "acme", "sc": {"verdict": "Watch"}}
    inp = operator.OperatorInputs(
        cases={"acme": case | {"fingerprint": operator.fingerprint(e, operator.OperatorInputs())}}
    )
    got = operator.operator_status(e, inp.cases["acme"], inp, now)
    assert (got["status"], got["source"], got["tone"]) == ("READY FOR MOHAMED", "prepared case", "amber")
    changed = e | {"one_liner": "edited"}
    assert operator.operator_status(changed, inp.cases["acme"], inp, now)["status"] == "REFRESHING CASE"
    assert operator.operator_status(e, inp.cases["acme"], inp, now + timedelta(days=15))["status"] == "REFRESHING CASE"
    gated = e | {"conflict": "unclear"}
    assert operator.operator_status(gated, None, inp, now)["status"] == "CONFLICT GATED"
    held = e | {"omar_outcome": "negative", "omar_outcome_at": "2026-11-01T10:00:00"}
    assert operator.operator_status(held, None, inp, now)["source"] == "human outcome"
    contacted = e | {"status": "contacted"}
    assert (
        operator.operator_status(contacted, None, operator.OperatorInputs(), now)["status"]
        == "AWAITING FOUNDER RESPONSE"
    )
    assert operator.operator_status(e, None, operator.OperatorInputs(), now)["status"] == "WATCH"
    assert operator.operator_status({"company": "X"}, None, operator.OperatorInputs(), now)["status"] == "NOT ASSESSED"


def test_case_view_is_the_imported_case_read_only() -> None:
    inp = operator.OperatorInputs(cases={"a": {"prepared_at": "2026-11-10T09:00:00", "error": "boom"}},
                                  case_actions=[{"slug": "a", "n": i} for i in range(45)] + [{"slug": "b"}])  # fmt: skip
    v = operator.case_view("a", None, inp, NOW)
    assert v["state"] == "BLOCKED" and v["states"] == operator.STATES and len(v["audit"]) == 40
    assert v["audit"][0]["n"] == 5 and v["steps"] == [] and v["usd"] == 0.0
    assert operator.case_view("zzz", None, inp, NOW)["state"] == "NOT STARTED"


# ── record overlay and order ────────────────────────────────────────────────────────────────────────────────────
def test_record_of_prefers_the_saved_record() -> None:
    assert record_of({"legacy": {"company": "Old"}, "attrs": {"record": {"company": "New"}}}) == {"company": "New"}
    assert record_of({"legacy": {"company": "Old"}, "attrs": {"bull": "x"}}) == {"company": "Old"}
    assert record_of({"legacy": None, "attrs": {}}) == {}


def test_order_is_the_archived_order_then_creation() -> None:
    t0 = datetime(2026, 1, 1)
    rows = [
        {"id": "n2", "legacy": None, "created_at": t0 + timedelta(days=2)},
        {"id": "b", "legacy": {"company": "Beta GmbH"}, "created_at": t0},
        {"id": "n1", "legacy": None, "created_at": t0 + timedelta(days=1)},
        {"id": "a", "legacy": {"company": "Alpha"}, "created_at": t0},
    ]
    assert [r["id"] for r in ordered(rows, ["Alpha", None, "Beta"])] == ["a", "b", "n1", "n2"]


# ── decision c: the server side of the three client preview differences, at their boundaries ────────────────────
def test_server_side_of_the_client_quirks() -> None:
    s = {"founder": 14, "venture_scale": 14, "why_now": 11, "taste": 10, "insight": 5}  # 54 + earliness
    # (1) the server zeroes the resemblance for archetype 15 (the client preview does not)
    assert taste.score({"scores": s, "conflict": "complementary", "archetype": 15})["breakdown"]["resemblance"] == 0
    assert taste.score({"scores": s, "conflict": "complementary", "archetype": 14})["breakdown"]["resemblance"] == 5
    # (2) the server bands are 65 / 80 on the provisional basis (the client "Investigate" uses >= 63)
    for total, verdict in ((63, "Watch"), (64, "Watch"), (65, "Research this week"), (79, "Research this week"),
                           (80, "Investigate immediately")):  # fmt: skip
        e = {"scores": s | {"taste": total - 44}}
        assert taste.score(e)["provisional"] == total and taste.score(e)["verdict"] == verdict
    # (3) the server's IMQ gates 'unclear' as well as 'potential_conflict' (the client isGated only the latter)
    for conflict in ("potential_conflict", "unclear"):
        assert (
            imq.evaluate(qualified(10, conflict=conflict), PEOPLE, None, None, today=TODAY)["state"] == "CONFLICT GATED"
        )
    assert (
        taste.score({"scores": s, "conflict": "unclear"})["verdict"]
        != taste.score({"scores": s, "conflict": "potential_conflict"})["verdict"]
    )


def test_days_since_takes_the_clock() -> None:
    assert taste.days_since("2026-11-01", date(2026, 11, 11)) == 10
    assert taste.days_since("2026-12-01", date(2026, 11, 11)) == 0
