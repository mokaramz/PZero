# ruff: noqa: E501
# (the synthetic corpus: one record per line)
"""Validation parity: the pure port against the OLD code as oracle, with a FIXED clock and no write (review 027a).

    python -m projectzero.ops.parity_validation goldens   # (re)generates golden_v1/oracle_validation.json
    python -m projectzero.ops.parity_validation check     # the stored golden against the new code (no oracle)

The oracle (``scripts/oracle/validation_oracle.py``) runs the old ``services/validation.py`` over a scratch data
folder: ``view(today)`` FIRST (its ``_snapshot`` append redirected to an in-memory log the old view's own subsequent
read sees, ``at`` frozen to the clock; recorded as ``appended``), then ``scout_packet(cycle)`` for ``""``, every cycle
of the view and an unknown one, then ``build(today)``; every other write is blocked and the data folder is checked
unchanged. The new side is the PURE port (``validation.inputs_model.inputs_from_docs`` -> ``validation.view`` /
``scout_packet`` / ``build``) over the same documents. Every answer is compared value by value AND as serialized text
(key order); the snapshot series is compared directly (row by row, key order included), and the inputs are checked
unchanged.

Declared differences, normalised here and nowhere else:

* (a) the old view APPENDED today's snapshot (``appended``); the new one computes the same point in memory and stores
  nothing. The payloads are equal (``snapshots`` included): nothing to normalise in the answer.
* (b) ``news``: the old panel (``news.view``, unavailable in the oracle) answered ``{available: false}``; the new one
  adds its ``reason`` (dropped here after checking it).
* (c) the packet's News and source-network learnings: each deferred section's ``- not available: <reason>`` line is
  mapped to the old fallback line (``- none yet`` / ``- none in probation yet`` / ``- not evaluated yet``) and a card's
  ``not available: <reason>`` to the old ``unavailable`` (text and JSON), then ``sha`` is recomputed.
* (d) ``native_bridge``: the old ``None`` (the pilot, unavailable in the oracle); the new ``{available: false,
  reason}``.

The synthetic data folders hold INVENTED names only:

* ``main``: candidates across tiers (pre-company, grant, announcement, the post-import ``manual`` / ``pre_company``
  intake tiers and an untagged lead), stages, themes, ecosystems and Scout lanes, with first-seen ties and conversion
  ties; triage proposals and more than 20 disagreeing decisions (the last line per candidate wins); Conviction records
  in and out of the Radar (IMQ qualified, sent to Omar, dropped, a legacy score); founder calls; more than 30 live
  outcomes, misses and false-positive audits AFTER filtering, each with a retraction of a row outside the raw tail and a
  superseded row; more than 60 snapshots (an out-of-order row dated today in the middle, the last row yesterday: today
  is appended and the window cuts); News events (MEDIUM / HIGH, LOW, NOISE, curated, a future date, an
  earliest-observation tie decided by the archive key order); verification decisions; an inference ledger across
  months; Scout Intake cycles in a key order JSONB would change (plus a cycle missing from ``cycles``); the routing
  store and the source network; a Scout log.
* ``today``: the final stored snapshot row is dated TODAY (no append, an earlier today row too).
* ``torn``: the snapshot log ends without a newline (the old append joined its last line: both rows are lost).
* ``broken``: tolerance: unreadable News (an issue), network and routing documents, junk log lines, a list of
  ``cycles``, Conviction records as an object.
* ``empty``: no documents at all.

Exit 1 on any difference.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT
from projectzero.dealflow.ranking.names import norm_company
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js
from projectzero.validation import build, inputs_from_docs, scout_packet, view
from projectzero.validation.core import NATIVE_BRIDGE_REASON, NEWS_REASON
from projectzero.validation.packet import DEFERRED

ORACLE = REPO_ROOT / "scripts" / "oracle" / "validation_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_validation.json"
CLOCK = "2026-11-12T10:00:00"
EXTRA_CYCLES = ["no-such-cycle"]


# ------------------------------------------------------------------ the synthetic data folders (invented names only)
def jl(rows: list[Any]) -> str:
    """A JSONL log as the old writers wrote it (``sort_keys``); a ``str`` row is a raw line, kept as is."""
    return "".join(
        (r if isinstance(r, str) else json.dumps(r, ensure_ascii=False, sort_keys=True)) + "\n" for r in rows
    )


def key(name: str) -> str:
    return norm_company(name)


# fmt: off
def sources() -> dict[str, Any]:
    return {"sources": [
        {"id": "s-lab", "name": "Invented Lab Transfer"}, {"id": "s-grant", "name": "Invented Grant Office"},
        {"id": "s-wire", "name": "Invented City Wire"}, {"id": "s-prog", "name": "Invented Venture Programme"},
        {"id": "s-noise", "name": "Invented Noisy Board"}, {"id": "live-manual", "name": "Manual"},
        {"id": "s-dup", "name": "Invented First Name"}, {"id": "s-dup", "name": "Invented Second Name"},
        {"id": "s-noname"}, "not a source",
    ]}


def cand(cid: str, name: str, src: str, tier: str, seen: str, decision: str = "new", country: str = "DE", **kw: Any) -> dict[str, Any]:
    return {"id": cid, "name": name, "source_id": src, "source": src, "discovery_tier": tier, "first_seen": seen,
            "decision": decision, "country": country, **kw}


TIERS = ("pre_company", "grant", "announcement")
SRCS = ("s-lab", "s-grant", "s-wire", "s-prog")
COUNTRIES = ("DE", "AT", "FR", "EE", "")
STAGES_ = ("PRE_COMPANY", "ROUND_FORMING", "FIRST_INSTITUTIONAL", "ALREADY_INSTITUTIONALLY_FUNDED", "GRANT_ONLY", None)
THEMES: tuple[list[str], ...] = (["robotics"], ["energy", "ai"], [], ["ai"])
MACHINE = ("KEEP", "RESEARCH", "WATCH", "REJECT")


def batch(i: int) -> str:
    return f"Invented Batch Co {i}"


def main_inbox() -> list[Any]:
    inbox: list[Any] = [
        cand("a1", "Invented Alpha Robotics GmbH", "s-lab", "pre_company", "2026-11-02", decision="kept",
             also_seen=[{"source_id": "s-wire", "source": "Invented City Wire", "discovery_tier": "announcement",
                         "first_seen": "2026-11-08", "source_date": "2026-11-07", "url": "https://wire.invented.example/alpha"}],
             all_source_ids=["s-lab", "s-wire"], quality_source_id="s-lab"),
        cand("a2", "Invented Alpha Robotics", "s-grant", "grant", "2026-11-02", country="AT"),  # a tie: a1 keeps tier / source / country
        cand("b1", "Invented Beta Funded", "s-wire", "announcement", "2026-10-20", country="FR"),
        cand("f1", "Invented Future Co", "s-lab", "pre_company", "2027-01-05"),
        cand("n1", "Invented Noise Holding", "s-noise", "announcement", "2026-11-03", decision="rejected", noise=True),
        cand("w1", "Invented Watch Optics", "s-prog", "pre_company", "2026-09-15", decision="watch", country="EE"),
        cand("r1", "Invented Rejected Grid", "s-grant", "grant", "2026-08-01", decision="rejected"),
        cand("q1", "Invented Research Lab", "s-lab", "pre_company", "2026-05-01", decision="research"),
        cand("kp1", "Invented Kappa Kept", "s-prog", "grant", "2026-10-11"),
        {"id": "d1", "name": "Invented Detected Only", "source_id": "s-prog", "discovery_tier": "grant",
         "detected_on": "2026-11-11T08:00:00", "decision": "new"},
        # decision (f): the records the database adapter derives for candidates the NEW intake created
        {"id": "live-1", "name": "Invented Manual Lead", "source": "Manual", "source_id": "live-manual", "discovery_tier": "manual",
         "decision": "new", "first_seen": "2026-11-10", "all_source_ids": ["live-manual"], "quality_source_id": "live-manual", "notes": ""},
        {"id": "live-2", "name": "Invented Stealth Lead", "source": "Grok scout", "source_id": "live-grok", "discovery_tier": "pre_company",
         "decision": "research", "first_seen": "2026-11-09", "all_source_ids": ["live-grok"], "quality_source_id": "live-grok"},
        {"id": "live-3", "name": "Invented Partial Lead", "source": "event_debrief", "source_id": "", "decision": "new", "first_seen": "2026-11-11"},
        {"id": "x0", "name": ""}, {"name": "Invented No Id"}, "not a record",
        cand("ag", "AG", "s-lab", "pre_company", "2026-10-01"),
        cand("u1", "Invented Dup Source Co", "s-dup", "grant", "2026-11-04"),
        cand("u2", "Invented Nameless Source Co", "s-noname", "pre_company", "2026-11-05"),
    ]
    for i in range(1, 31):
        inbox.append(cand(f"k{i}", batch(i), SRCS[i % 4], TIERS[i % 3], f"2026-{10 if i % 2 else 11}-{(i % 9) + 1:02d}",
                          country=COUNTRIES[i % 5]))
    for i in range(10):
        inbox.append(cand(f"z{i}", f"Invented Noise Board Find {i}", "s-noise", "announcement", f"2026-11-0{i % 9 + 1}",
                          decision="baseline" if i < 7 else "new"))
    return inbox


def main_props() -> dict[str, Any]:
    props: dict[str, Any] = {f"k{i}": {"status": "proposed" if i % 5 else "needs_human", "proposal": MACHINE[i % 4],
                                       "capital_stage": STAGES_[i % 6], "themes": THEMES[i % 4]} for i in range(1, 31)}
    props.update({
        "a1": {"status": "proposed", "proposal": "KEEP", "capital_stage": "PRE_COMPANY", "themes": ["robotics"]},
        "a2": {"status": "decided", "proposal": "REJECT"},
        "b1": {"status": "proposed", "proposal": "REJECT", "capital_stage": "ALREADY_INSTITUTIONALLY_FUNDED"},
        "r1": {"status": "needs_human", "proposal": "REJECT", "capital_stage": "GRANT_ONLY"},
        "w1": {"status": "proposed", "proposal": "WATCH"},
        "kp1": {"status": "proposed", "proposal": "KEEP", "capital_stage": "ROUND_FORMING", "themes": ["energy"]},
        "live-2": {"status": "proposed", "proposal": "RESEARCH", "capital_stage": "PRE_COMPANY", "themes": ["ai"]},
    })
    return props


def main_decisions() -> str:
    rows: list[Any] = [{"candidate_id": "k3", "name": batch(3), "machine": "WATCH", "verdict": "REJECT", "agreed": False,
                        "ts": "2026-10-30T08:00:00"}]  # superseded by k3's later line
    for i in range(1, 27):
        verdict = "KEEP" if i % 3 == 0 else ("REJECT", "KEEP", "RESEARCH", "WATCH")[i % 4]
        rows.append({"candidate_id": f"k{i}", "name": batch(i), "machine": MACHINE[i % 4], "verdict": verdict,
                     "agreed": verdict == MACHINE[i % 4], "ts": f"2026-11-{1 + i // 4:02d}{'T' if i % 7 else ' '}09:{(i % 4) * 6:02d}:00"})
    rows += [
        {"candidate_id": "a1", "name": "Invented Alpha Robotics GmbH", "machine": "KEEP", "verdict": "KEEP", "agreed": True, "ts": "2026-11-03T10:00:00"},
        {"candidate_id": "w1", "name": "Invented Watch Optics", "machine": "WATCH", "verdict": "WATCH", "agreed": True, "ts": "yesterday"},
        {"candidate_id": "kp1", "name": "Invented Kappa Kept", "machine": "KEEP", "verdict": "KEEP", "agreed": True, "ts": "2026-11-04T10:00:00"},
        {"name": "orphan line without a candidate"}, "not json",
        {"candidate_id": "gone-1", "name": "Invented Unknown Candidate", "machine": "REJECT", "verdict": "KEEP", "agreed": False},
    ]
    return jl(rows)


def signal(company: str, **kw: Any) -> dict[str, Any]:
    return {"company": company, "status": "new", "scores": {"founder": 10, "venture_scale": 9, "why_now": 6, "taste": 6, "insight": 3},
            "verified": {}, "earliness": "unknown", "archetype": 3, **kw}


VERIFIED = {"founders": True, "traction": True, "funding": True}
TOP = {"founder": 22, "venture_scale": 17, "why_now": 12, "taste": 12, "insight": 8}


def main_signals() -> list[Any]:
    return [
        signal("Invented Alpha Robotics", status="contacted", scores=TOP, verified=VERIFIED, sent_to_omar="2026-11-05",
               omar_outcome="positive", imq={"state": "IMQ — QUALIFIED (all gates)"}),
        signal("Invented Gamma Grid", discovered_first_seen="2026-10-01", discovery_tier="pre_company", source_id="s-lab"),
        signal("Invented Delta Drop", status="dropped", omar_outcome="negative", sent_to_omar="2026-10-10"),
        signal("Invented Legacy Scores", scores={"founder": "high", "venture_scale": ""}),
        signal("Invented Kappa Kept", status="contacted", omar_outcome="negative"),
        signal(batch(1), scores=TOP, verified=VERIFIED),  # verified, Radar
        signal(batch(2), scores=TOP, verified={"founders": True}),  # not verified
        {"status": "new"}, "not a record",
    ]


def founder_calls() -> dict[str, Any]:
    return {"calls": {
        "fc-2": {"company_id": "co-b", "date": "2026-11-06", "assessment": {"recommendation": "Follow up"}},
        "fc-1": {"company_id": "co-a", "date": "2026-11-01", "assessment": {"recommendation": "Consider for Omar"}},
        "fc-3": {"company_id": "co-b", "date": "2026-11-08", "assessment": {"recommendation": "Pass"}},  # the last call wins
        "fc-4": {"company_id": "co-x"},
    }, "companies": {"co-a": {"name": "Invented Founder Call Co"}, "co-b": {"name": batch(20)}}}


def scout_item(iid: str, name: str, cycle: str | None, lanes: list[str], **kw: Any) -> dict[str, Any]:
    return {"id": iid, "entity_name": name, "cycle_id": cycle, "source_scouts": lanes, "recommended_action": "PRIORITISE",
            "status": "NEW INTAKE", "date_discovered_effective": "2026-11-01", **kw}


def scout_intake() -> dict[str, Any]:
    return {"cycles": {"cycle-010": {"date": "2026-11-01"}, "c-9": {}, "cycle-002": {}},  # JSONB would order c-9, cycle-002, cycle-010
            "items": [
                scout_item("si-1", "Invented Alpha Robotics", "cycle-010", ["lane-a"], status="ACCEPTED", feedback={"outcome": "KEEP"},
                           date_discovered_effective="2026-10-28", signal_date="2026-10-27",
                           evidence_urls=["https://www.alpha.invented.example/a", "https://alpha.invented.example/b", "not a url",
                                          "https://press.invented.example/x"]),
                scout_item("si-2", batch(3), "c-9", ["lane-a", "lane-b"], recommended_action=None),
                scout_item("si-3", batch(6), "c-9", ["lane-a"], evidence_urls=["https://six.invented.example/"]),
                scout_item("si-4", batch(9), "cycle-010", ["lane-a"]),
                scout_item("si-5", batch(12), "cycle-010", ["lane-a"], status=None),
                scout_item("si-6", batch(15), "cycle-002", ["lane-a"], feedback={"outcome": "DROP"}),
                scout_item("si-7", "Invented Scout Only Find", "cycle-002", ["lane-b"], date_discovered="2026-09-20",
                           date_discovered_effective=None),
                scout_item("si-8", "Invented Kappa Kept", "cycle-777", ["lane-c"]),
                scout_item("si-9", "", "cycle-010", ["lane-a"]),
                scout_item("si-10", "Invented Future Scout", "c-9", [], date_discovered_effective="2027-03-01"),
                scout_item("si-11", batch(24), None, ["lane-b"]),
            ]}


def outcome(oid: str, company: str, kind: str, day: str, url: str = "", **kw: Any) -> dict[str, Any]:
    return {"id": oid, "recorded_at": f"{day}T12:00:00", "recorded_by": "mohamed", "company": company, "entity_key": key(company),
            "candidate_id": "", "kind": kind, "event_date": day, "evidence_url": url, "benchmark_system": "", "note": "",
            "supersedes": None, **kw}


KIND_CYCLE = ("institutional_round", "accelerator", "mainstream_press", "commercial_milestone", "acquisition",
              "omar_interested", "project_a_invested", "shutdown", "weak_outcome", "omar_declined", "external_db_listing")


def main_outcomes() -> str:
    rows: list[Any] = [outcome("oc-001", batch(25), "mainstream_press", "2026-11-01", "https://press.invented.example/25"),
                       outcome("oc-002", batch(26), "acquisition", "2026-11-02", "https://press.invented.example/26")]  # retracted at the end
    for n, i in enumerate((3, 6, 9)):
        rows.append(outcome(f"oc-c{n}", batch(i), "commercial_milestone", f"2026-11-1{n}", f"https://press.invented.example/c{i}"))
    for n, i in enumerate((12, 15, 18)):
        rows.append(outcome(f"oc-w{n}", batch(i), "weak_outcome", f"2026-11-0{n + 4}"))
    for n, i in enumerate((1, 2, 4, 5, 7, 8)):
        rows.append(outcome(f"oc-b{n}", batch(i), "external_db_listing", f"2026-{'09' if n % 2 else '11'}-{10 + n:02d}",
                            f"import://invented db/{n}", benchmark_system="Invented DB"))
    rows.append(outcome("oc-r", "Invented Alpha Robotics GmbH", "institutional_round", "2026-11-10", "https://wire.invented.example/round"))
    rows.append(outcome("oc-acc", batch(10), "accelerator", "2026-11-03"))  # no URL: class 2
    rows.append(outcome("oc-out", "Invented Outside Co", "institutional_round", "2026-10-01", "https://press.invented.example/outside"))
    rows.append(outcome("oc-010", batch(11), "mainstream_press", "2026-10-15", "https://press.invented.example/11"))
    rows.append(outcome("oc-odd", batch(13), "rumour", "2026-11-01"))  # an unknown kind: listed, never counted
    rows.append({"id": "oc-nokind", "company": batch(14)})
    rows += ["not json", "[1, 2]"]
    for i in range(20):
        rows.append(outcome(f"oc-f{i:02d}", f"Invented Filler Co {i}", KIND_CYCLE[i % len(KIND_CYCLE)], f"2026-10-{i + 1:02d}",
                            f"https://press.invented.example/f{i}" if i % 3 else ""))
    rows.append(outcome("oc-050", batch(11), "institutional_round", "2026-10-16", "https://press.invented.example/11b", supersedes="oc-010"))
    rows.append({"id": "rx-1", "retracts": "oc-002", "recorded_at": "2026-11-11T09:00:00", "reason": "entered for the wrong company"})
    return jl(rows)


def miss(aid: str, company: str, **kw: Any) -> dict[str, Any]:
    return {"id": aid, "type": "miss", "recorded_at": "2026-11-01T10:00:00", "company": company, "entity_key": key(company),
            "note": "", "supersedes": None, "miss_type": "never_found", "pz_state_at_audit": None, "earliest_signal": "a lab page",
            "earliest_signal_date": "2026-06-01", "signal_source": "Invented Lab Site", "should_have_found": "s-lab",
            "why_missed": "source_not_covered", "preventable": "yes", "improvement": "watch the lab page", **kw}


def fp(aid: str, company: str, **kw: Any) -> dict[str, Any]:
    return {"id": aid, "type": "false_positive", "recorded_at": "2026-11-02T10:00:00", "company": company, "entity_key": key(company),
            "note": "", "supersedes": None, "causes": ["weak_source"], "lesson": "", **kw}


def main_audits() -> str:
    rows: list[Any] = []
    for i in range(1, 36):
        rows.append(miss(f"au-m{i:02d}", f"Invented Missed Co {i}", preventable=("yes", "no", "unclear")[i % 3],
                         note="from News" if i % 4 == 0 else "", earliest_signal="" if i % 5 == 0 else "a lab page"))
        if i <= 33:
            rows.append(fp(f"au-f{i:02d}", f"Invented FP Co {i}", causes=[("weak_source", "ai_wrapper", "model_error")[i % 3]]))
    rows.append(miss("au-m-strong", batch(3), miss_type="found_too_late"))  # a strong entity: not counted twice
    rows.append(fp("au-f-kappa", "Invented Kappa Kept", causes=["founder_quality_overestimated", "poor_market"]))
    rows.append(fp("au-f99", "Invented FP Co 2", supersedes="au-f02", causes=["insufficient_evidence"]))
    rows += ["{broken", {"id": "rx-a", "retracts": "au-m01", "recorded_at": "2026-11-11T08:00:00", "reason": "this was not a miss"}]
    return jl(rows)


def snap(day: str, n: int) -> dict[str, Any]:
    return {"date": day, "at": f"{day}T07:00:00", "found_this_month": n, "pre_funding_share": None, "pre_funding_this_month": n // 3,
            "median_lead_days": n / 2 if n % 2 else n // 2, "lead_n": n % 7, "found_at_announcement": 1, "strong_cases": n % 4,
            "strong_found_early": 0, "strong_found_late": 0, "exceptional_recall": None, "strong_universe": n % 4,
            "strong_found_and_kept": 0, "false_negatives": 0, "never_seen": 0, "unique_source_this_month": n,
            "conviction": 2, "decisions": n, "agreement": 0.5 if n >= 5 else None}


def main_snapshots() -> str:
    days = [f"2026-09-{d:02d}" for d in range(1, 31)] + [f"2026-10-{d:02d}" for d in range(1, 32)] + [f"2026-11-{d:02d}" for d in range(1, 12)]
    rows: list[Any] = [snap(d, i) for i, d in enumerate(days)]
    rows.insert(40, snap("2026-11-12", 99))  # out of order, today: only the LAST row is compared
    rows.insert(10, "not json")
    return jl(rows)


def news_event(eid: str, ekey: str, mat: str, day: str, **kw: Any) -> dict[str, Any]:
    return {"event_id": eid, "entity_key": ekey, "materiality": mat, "event_date": day, "headline": f"Headline {eid}",
            "sources": [{"publisher": f"Invented Daily {eid}", "url": f"https://news.invented.example/{eid}"}], **kw}


def main_news() -> dict[str, Any]:
    return {"events": {
        "nw-9": news_event("nw-9", key(batch(4)), "MEDIUM", "2026-11-08"),
        "nw-1": news_event("nw-1", key(batch(4)), "HIGH", "2026-11-08"),  # the same date: the first in key order wins
        "nw-5": news_event("nw-5", key(batch(4)), "LOW", "2026-10-01"),
        "nw-3": news_event("nw-3", key(batch(4)), "NOISE", "2026-10-02"),
        "nw-c": news_event("nw-c", key(batch(4)), "HIGH", "2026-09-01", curated=True),
        "nw-a": news_event("nw-a", key("Invented Alpha Robotics"), "HIGH", "2026-11-06"),
        "nw-u": news_event("nw-u", "invented never known", "HIGH", "2026-11-01"),
        "nw-f": news_event("nw-f", key(batch(5)), "MEDIUM", "2027-02-01"),
        "nw-e": news_event("nw-e", "", "HIGH", "2026-11-01"),
        "nw-s": news_event("nw-s", key("Invented Scout Only Find"), "MEDIUM", "2026-10-30"),
        "nw-7": news_event("nw-7", key(batch(7)), "HIGH", "2026-11-09"),
    }, "seeded": ["case-1"]}


def main_docs() -> dict[str, Any]:
    ledger = [{"ts": "2026-10-30T23:59:59", "usd": 0.5}, {"ts": "2026-11-01T00:00:01", "usd": 0.25},
              {"ts": "2026-11-12T09:59:00", "usd": "0.125"}, {"ts": "2025-11-03T10:00:00", "usd": 9},
              {"ts": "2026-11-05T10:00:00", "usd": None}, {"usd": 3}, "not json"]
    routes = {f"k{i}": {"name": batch(i), "state": ("NEEDS_MOHAMED", "CALIBRATION_SAMPLE", "MACHINE_WATCH", "DEFERRED_LOW_PRIORITY",
                                                     "BACKGROUND_RESEARCH")[i % 5], "resurfaced": i == 4} for i in range(1, 11)}
    routes["k3"] = {"name": batch(3), "state": "NEEDS_MOHAMED", "underlying": "DEFERRED_LOW_PRIORITY"}
    routes["a1"] = {"name": "Invented Alpha Robotics GmbH", "state": "CASE_PREPARING"}
    return {
        "sources.json": sources(), "inbox.json": {"candidates": main_inbox()}, "triage_proposals.json": {"proposals": main_props()},
        "triage_decisions.jsonl": main_decisions(), "real_data.json": {"signals": main_signals()},
        "founder_calls.json": founder_calls(), "scout_intake.json": scout_intake(), "news/events.json": main_news(),
        "sources/network.json": {"candidates": {
            "n1": {"registry_source_id": "s-lab", "state": "PROBATION"}, "n2": {"news_feed": "Invented Feed", "state": "TRUSTED"},
            "n3": {"state": "DISCOVERED"}, "n4": {"registry_source_id": "s-wire", "state": "DEGRADED"}}},
        "queue_routing.json": {"routes": routes, "left_queue": {"k11": {"name": batch(11), "state": "MACHINE_WATCH", "resurfaced": True},
                                                               "k12": {"name": batch(12), "underlying": "MACHINE_WATCH"}}, "runs": []},
        "validation/outcomes.jsonl": main_outcomes(), "validation/audits.jsonl": main_audits(),
        "validation/snapshots.jsonl": main_snapshots(),
        "validation/scout_feedback.jsonl": jl([{"at": "2026-11-01T10:00:00", "cycle": "c-9", "companies": 2, "sha": "a" * 16, "handed_over": True},
                                              {"at": "2026-11-08T10:00:00", "cycle": "all", "companies": 9, "sha": "b" * 16, "handed_over": True}]),
        "verification_decisions.jsonl": jl([{"flag": "founders", "decision": "accept"}, {"flag": "funding", "decision": "reject"},
                                            {"flag": "founders", "decision": "accept"}, {"decision": "accept"}, "nope"]),
        "inference_ledger.jsonl": jl(ledger),
    }


def today_docs() -> dict[str, Any]:
    return {
        "sources.json": sources(),
        "inbox.json": {"candidates": [cand("t1", "Invented Today Lab", "s-lab", "pre_company", "2026-11-12"),
                                      cand("t2", "Invented Today Wire", "s-wire", "announcement", "2026-11-12")]},
        "validation/snapshots.jsonl": jl([snap("2026-11-10", 3), snap("2026-11-12", 4), snap("2026-11-11", 5), snap("2026-11-12", 6)]),
        "validation/outcomes.jsonl": jl([outcome("oc-t", "Invented Today Lab", "accelerator", "2026-11-12", "https://press.invented.example/t")]),
        "inference_ledger.jsonl": jl([{"ts": "2026-11-12T00:00:00", "usd": 1.23456}]),
    }


def torn_docs() -> dict[str, Any]:
    return {
        "inbox.json": {"candidates": [cand("o1", "Invented Torn Co", "s-lab", "pre_company", "2026-11-01")]},
        "validation/snapshots.jsonl": jl([snap("2026-11-09", 1), snap("2026-11-10", 2)]) + json.dumps(snap("2026-11-11", 3), sort_keys=True),
    }


def broken_docs() -> dict[str, Any]:
    return {
        "sources.json": {"sources": [{"id": "s-lab"}]},
        "inbox.json": {"candidates": [cand("y1", "Invented Broken Lab", "s-lab", "pre_company", "2026-13-40"),
                                      cand("y2", "Invented Odd Dates", "s-lab", "grant", "2026-11-31x"), 7]},
        "real_data.json": {"signals": {"a": signal("Invented Dict Signal", discovered_first_seen="2026-11-01"), "b": "x"}},
        "scout_intake.json": {"cycles": ["c-list-2", "c-list-1"], "items": [scout_item("sb-1", "Invented Broken Scout", "c-list-1", ["lane-z"]),
                                                                          scout_item("sb-2", "Invented Other Scout", "c-zzz", ["lane-z"])]},
        "news/events.json": [1],
        "sources/network.json": [],
        "queue_routing.json": {"routes": []},
        "founder_calls.json": {"calls": {}, "companies": {}},
        "triage_decisions.jsonl": "garbage\n[1]\n\n" + jl([{"candidate_id": "y1", "machine": "KEEP", "verdict": "REJECT", "agreed": False}]),
        "validation/outcomes.jsonl": "\n\n{\n",
        "validation/audits.jsonl": jl([{"id": "rx-x", "retracts": "nothing"}]),
        "validation/snapshots.jsonl": "garbage\n",
        "validation/scout_feedback.jsonl": "[]\n",
        "verification_decisions.jsonl": "{]\n",
        "inference_ledger.jsonl": "\n",
    }


SETS: dict[str, Any] = {"main": main_docs, "today": today_docs, "torn": torn_docs, "broken": broken_docs, "empty": lambda: {}}
# fmt: on


# ------------------------------------------------------------------ the oracle
def _files(docs: dict[str, Any]) -> dict[str, bytes]:
    out = {}
    for k, v in docs.items():
        out[k] = (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=2)).encode("utf-8")
    return out


def run_oracle(inp: dict[str, Any], files: dict[str, bytes]) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-validation-oracle-") as tmp:
        data = Path(tmp) / "data"
        data.mkdir(parents=True)
        for rel, raw in files.items():
            target = (data / rel).resolve()
            if data.resolve() not in target.parents:
                raise SystemExit(f"refusing a path outside the scratch folder: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        srcf, dst = Path(tmp) / "io" / "in.json", Path(tmp) / "io" / "out.json"
        srcf.parent.mkdir(parents=True, exist_ok=True)
        srcf.write_text(json.dumps(inp, ensure_ascii=False), encoding="utf-8")
        env = {**os.environ, "PZ_DATA": str(data), "PZ_TESTING": "1", "PZ_CASE_PREP": "0",
               "PYTHONPATH": str(OLD_REPO / "backend" / "src")}  # fmt: skip
        for k in [k for k in env if k == "SUPABASE_DB_URL" or k.endswith("_API_KEY") or k.endswith("_TOKEN")]:
            env.pop(k)  # the oracle never needs, and never sees, the database or any key
        run = subprocess.run([str(python), str(ORACLE), str(srcf), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_text(encoding="utf-8"))
        return out


# ------------------------------------------------------------------ the new side and the declared normalisation
def _answer(fn: Any) -> dict[str, Any]:
    try:
        body = fn()
    except Exception as exc:  # the old route would have answered 500
        return {"raises": type(exc).__name__}
    return {"code": 200, "body": js(body)}


_FALLBACK = {  # decision (c): the section header -> the old fallback line
    "== NEWS LEARNING": "- none yet",
    "== SOURCE NETWORK": "- none in probation yet",
    "== NEWS SOURCE LEARNING": "- not evaluated yet",
}


def old_packet(body: dict[str, Any]) -> dict[str, Any]:
    """Decision (c): the new packet as the old code answered with the deferred views unavailable."""
    out, section = [], ""
    for line in body["text"].split("\n"):
        if line.startswith("== "):
            section = next((h for h in _FALLBACK if line.startswith(h)), "")
        if section and line == f"- {DEFERRED}":
            line = _FALLBACK[section]
        out.append(line)
    text = "\n".join(out).replace(f"source learning: {DEFERRED}", "source learning: unavailable")
    text = text.replace(
        json.dumps({"source_learning": DEFERRED}, ensure_ascii=False)[1:-1], '"source_learning": "unavailable"'
    )
    return {**body, "text": text, "sha": hashlib.sha256(text.encode()).hexdigest()[:16]}


def old_view(body: dict[str, Any], problems: list[str], label: str) -> dict[str, Any]:
    """Decisions (b) and (d): the deferred panels as the old code answered with them unavailable."""
    body = dict(body)
    if body.get("news") != {"available": False, "reason": NEWS_REASON}:
        problems.append(f"{label}/news: not the deferred News panel")
    if body.get("native_bridge") != {"available": False, "reason": NATIVE_BRIDGE_REASON}:
        problems.append(f"{label}/native_bridge: not the deferred native-bridge panel")
    keys = list(body)
    body["news"] = {"available": False}
    body["native_bridge"] = None
    return {k: body[k] for k in keys}


def new_side(docs: dict[str, Any], clock: str, cycles: list[str]) -> tuple[dict[str, Any], list[str]]:
    now = datetime.fromisoformat(clock)
    today = now.date()
    docs_before = copy.deepcopy(docs)
    inputs = inputs_from_docs(docs, today)
    inputs_before = copy.deepcopy(inputs)
    problems: list[str] = []
    v = _answer(lambda: view(inputs, today, now))
    if "body" in v:
        v["body"] = old_view(v["body"], problems, "/view")
    packets = {}
    for c in cycles:
        p = _answer(lambda c=c: scout_packet(inputs, c, today, now))
        packets[c] = {**p, "body": old_packet(p["body"])} if "body" in p else p

    def ents() -> dict[str, Any]:
        e, issues = build(inputs, today)
        return {"entities": e, "issues": issues}

    out = {"view": v, "packets": packets, "build": _answer(ents)}
    if inputs != inputs_before:
        problems.append("/inputs: Validation changed its inputs")
    if docs != docs_before:
        problems.append("/docs: inputs_from_docs changed the documents")
    return out, problems


def _text(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def compare_set(name: str, s: dict[str, Any]) -> list[str]:
    expected = s["expected"]
    problems: list[str] = []
    if expected.get("changed"):
        problems.append(f"/{name}/changed: the OLD read changed {expected['changed']}")
    got, invariants = new_side(s["docs"], s["clock"], list(expected["packets"]))
    problems += [f"/{name}{p}" for p in invariants]
    for part in ("view", "packets", "build"):
        problems += [f"/{name}/{part}{p}" for p in diff(js(expected[part]), js(got[part]))]
        if _text(expected[part]) != _text(got[part]):
            problems.append(f"/{name}/{part}: the serialized answer differs (key order)")
    old_series = ((expected["view"].get("body") or {}).get("snapshots")) or []
    new_series = ((got["view"].get("body") or {}).get("snapshots")) or []
    if [_text(r) for r in old_series] != [_text(r) for r in new_series]:
        problems.append(f"/{name}/snapshots: the series differs (row by row, key order included)")
    return problems


def compare_goldens(golden: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for name, s in golden["sets"].items():
        problems += compare_set(name, {**s, "clock": golden["clock"]})
    return problems


def write_goldens() -> int:
    sets: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    for name, fn in SETS.items():
        docs = fn()
        oracle = run_oracle({"clock": CLOCK, "extra_cycles": EXTRA_CYCLES}, _files(docs))
        meta = oracle.pop("meta")
        sets[name] = {"docs": docs, "expected": oracle}
    golden = {"provenance": meta, "clock": CLOCK, "sets": sets}
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    # NOT sort_keys: the documents' insertion order is part of the input (and of what the oracle recorded)
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=None) + "\n", encoding="utf-8", newline="\n")
    problems = compare_goldens(json.loads(GOLDEN.read_text(encoding="utf-8")))
    print(json.dumps({"golden": str(GOLDEN), "bytes": GOLDEN.stat().st_size, "old": meta, "summary": summary(golden)},
                     indent=1, ensure_ascii=False))  # fmt: skip
    for p in problems[:60]:
        print("  DIFF", p)
    print("VALIDATION GOLDENS MATCH" if not problems else f"VALIDATION GOLDENS DIFFER ({len(problems)})")
    return 1 if problems else 0


def summary(golden: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, s in golden["sets"].items():
        e = s["expected"]
        body = e["view"].get("body") or {}
        out[name] = {
            "view": "ok" if body else e["view"],
            "appended": len(e["appended"]),
            "snapshots": len(body.get("snapshots") or []),
            "outcomes": len(body.get("outcomes") or []),
            "misses": len(body.get("misses") or []),
            "false_positive_audits": len(body.get("false_positive_audits") or []),
            "entities": len(((e["build"].get("body") or {}).get("entities")) or {}),
            "issues": ((e["build"].get("body") or {}).get("issues")),
            "cycles": (body.get("scout") or {}).get("cycles"),
            "packets": {c: (p.get("body") or {}).get("counts", p.get("raises")) for c, p in e["packets"].items()},
            "routing": body.get("routing") is not None,
            "changed": e["changed"],
        }
    return out


# ------------------------------------------------------------------ the real snapshot, through the API routes
REAL_CLOCK = "2026-11-12T09:00:00"
_TABLES = "select table_name from information_schema.tables where table_schema = %s and table_type = 'BASE TABLE'"


def _fingerprint(conn: Any, schema: str) -> dict[str, Any]:
    """Every table of the schema as (row count, a digest of its whole rows): a read must leave all of them equal."""
    from psycopg import sql as _sql

    out: dict[str, Any] = {}
    for (table,) in conn.execute(_TABLES, (schema,)).fetchall():
        q = _sql.SQL("select count(*), md5(coalesce(string_agg(t::text, '|' order by t::text), '')) from {}.{} t")
        out[table] = conn.execute(q.format(_sql.Identifier(schema), _sql.Identifier(table))).fetchone()
    return out


def real() -> int:  # pragma: no cover - needs the hosted database and the old repository
    """The real snapshot imported by the production importer into a throw-away schema, through the API routes, against
    the OLD code over a byte-exact copy at the same clock: ``GET /api/validation`` and the Scout 00 packet for ``""``,
    every cycle and an unknown one. Declared (a)-(d) only, normalised as for the goldens; every table of the schema is
    checked unchanged by the reads. Aggregates only are printed."""
    import secrets as _secrets

    from fastapi.testclient import TestClient
    from psycopg import sql as _sql

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot
    from projectzero.ops.parity_founder_calls import utc_instant

    load_dotenv()
    settings = Settings.from_env()
    snapshot_ = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    old = run_oracle({"clock": REAL_CLOCK, "extra_cycles": EXTRA_CYCLES}, {f.path: f.raw for f in snapshot_.files()})
    old.pop("meta", None)
    schema = f"pz_rehearse_{_secrets.token_hex(4)}"
    problems: list[str] = []
    report: dict[str, Any] = {}
    admin = connect(settings.db_url, autocommit=True)
    try:
        admin.execute(_scratch_sql(schema).encode())
        conn = connect(settings.db_url)
        try:
            applied = apply_plan(build_plan(snapshot_), schema=schema, conn=conn)
            assert applied.get("applied"), applied
        finally:
            conn.close()
        with transaction(settings.db_url) as c:
            before = _fingerprint(c, schema)
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: utc_instant(REAL_CLOCK)
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:

            def ans(r: Any) -> dict[str, Any]:
                return (
                    {"code": r.status_code, "body": js(r.json())} if r.status_code == 200 else {"code": r.status_code}
                )

            v = ans(client.get("/api/validation"))
            if "body" in v:
                v["body"] = old_view(v["body"], problems, "/view")
            packets = {}
            for cycle in old["packets"]:
                p = ans(client.get("/api/validation/scout_packet", params={"cycle": cycle}))
                packets[cycle] = {**p, "body": old_packet(p["body"])} if "body" in p else p
        with transaction(settings.db_url) as c:
            after = _fingerprint(c, schema)
        got = {"view": v, "packets": packets}
        for part in got:
            problems += [f"/{part}{p}" for p in diff(js(old[part]), js(got[part]))]
            if _text(old[part]) != _text(got[part]):
                problems.append(f"/{part}: the serialized answer differs (key order)")
        old_series = (old["view"].get("body") or {}).get("snapshots") or []
        new_series = (v.get("body") or {}).get("snapshots") or []
        if [_text(r) for r in old_series] != [_text(r) for r in new_series]:
            problems.append("/snapshots: the series differs (row by row, key order included)")
        changed = sorted(t for t in before if before[t] != after.get(t))
        if changed:
            problems.append(f"/stored: a Validation read changed {changed}")
        body = v.get("body") or {}
        report = {"headline": body.get("headline"), "snapshots": len(body.get("snapshots") or []),
                  "old_appended": len(old.get("appended") or []), "sources": len(body.get("sources") or []),
                  "cycles": (body.get("scout") or {}).get("cycles"),
                  "packets": {c: (p.get("body") or {}).get("counts", p.get("code")) for c, p in packets.items()},
                  "tables_checked": len(before), "old_changed": old.get("changed")}  # fmt: skip
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    report["differences"] = len(problems)
    print(json.dumps(report, indent=2, default=str, ensure_ascii=False))
    for line in problems[:60]:
        print("  DIFF", line)
    print("VALIDATION PARITY PASSED" if not problems else "VALIDATION PARITY FAILED")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["real"]:
        return real()
    if argv[1:] == ["goldens"]:
        return write_goldens()
    if argv[1:] == ["check"]:  # the stored golden against the new code, without the oracle
        problems = compare_goldens(json.loads(GOLDEN.read_text(encoding="utf-8")))
        for p in problems[:60]:
            print("  DIFF", p)
        print("VALIDATION GOLDENS MATCH" if not problems else f"VALIDATION GOLDENS DIFFER ({len(problems)})")
        return 1 if problems else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
