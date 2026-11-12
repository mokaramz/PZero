# ruff: noqa: E501
# (the synthetic corpus: one record per line)
"""Validation parity: the pure port against the OLD code as oracle, with a FIXED clock and no write (review 027a).

    python -m projectzero.ops.parity_validation goldens   # (re)generates golden_v1/oracle_validation.json
    python -m projectzero.ops.parity_validation check     # the stored golden against the new code (no oracle)
    python -m projectzero.ops.parity_validation writes-goldens  # (re)generates golden_v1/oracle_validation_writes.json
    python -m projectzero.ops.parity_validation writes-check    # the stored writes golden against the new code

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
* (b) closed by review 028a: the News panel (``news``) and the packet's NEWS LEARNING / NEWS SOURCE LEARNING are the
  News port's; the oracle runs the old ``news.view`` / ``news.learnings`` / ``news_sources.scout_lines`` with the
  GET-time seeding of the curated cases in memory (``news_oracle.install_news``; recorded as ``news_saved`` and
  compared with the new ``news.seed_cases``): nothing to normalise.
* (c) the packet's source-network learnings (the source network is not ported): the SOURCE NETWORK section's
  ``- not available: <reason>`` line is mapped to the old fallback line (``- none in probation yet``) and a card's
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
  earliest-observation tie decided by the archive key order) with their actions, runs, metric cache, scan history and
  an invented curated case the GET seeds (review 028a); verification decisions; an inference ledger across
  months; Scout Intake cycles in a key order JSONB would change (plus a cycle missing from ``cycles``); the routing
  store and the source network; a Scout log.
* ``today``: the final stored snapshot row is dated TODAY (no append, an earlier today row too).
* ``torn``: the snapshot log ends without a newline (the old append joined its last line: both rows are lost).
* ``broken``: tolerance: unreadable News (an issue), network and routing documents, junk log lines, a list of
  ``cycles``, Conviction records as an object.
* ``empty``: no documents at all (and an empty curated case folder: every set names its own, ``CASES_KEY``).

The writes (review 027b, ``writes-goldens`` / ``writes-check``, ``golden_v1/oracle_validation_writes.json``): the
oracle (``scripts/oracle/validation_writes_oracle.py``) runs the old ``record_outcome`` / ``record_audit`` /
``retract`` / ``import_benchmark`` / ``scout_packet(mark=True)`` step by step over the ``main`` and ``empty``
folders, the clock frozen and the old ``_id``'s ``datetime.now().timestamp()`` answering the step's ``seam``
values; every append goes to in-memory logs the later old reads see (the folder is checked unchanged); then the old
``view``. The new side is ``validation.writes`` with ``new_hex`` = the same seam, each step's lines appended to the
inputs' log texts (``writes.appended``), then the 027a ``view``. The answers are compared value by value and as
text, the appended lines BYTE for BYTE, then the next view. Declared, and nothing else:

* (e) the CSV whose first data row has more fields than the header, and the one raising ``csv.Error``: the old
  500, now a 400 ``the CSV could not be read: ...``; neither side appends anything;
* (f) the packet mark: the new body is the ``{cycle, generated, sha}`` of the packet the GET shows; the answer is
  compared through the 027a normalisation (c); the old line logged the sha of its regenerated text, checked equal
  to the text at the frozen clock and replaced by the shown packet's sha (in the line and the next view's
  ``scout.last_packet``); a stale sha (409) and a missing ``generated`` (400) are checked refused, nothing appended.

Exit 1 on any difference.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT
from projectzero.dealflow.ranking.names import norm_company
from projectzero.news import seed_cases
from projectzero.news.core import load as news_load
from projectzero.news.inputs_model import CASES_KEY
from projectzero.ops.parity_news import scratch_oracle, split_cases
from projectzero.ops.parity_ranking import GOLDEN_DIR, diff, js
from projectzero.validation import build, inputs_from_docs, scout_packet, view, writes
from projectzero.validation.catalog import MISS_REASONS
from projectzero.validation.core import NATIVE_BRIDGE_REASON, ValidationError
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
    """A stored News event; the fields the News view reads (review 028a) default to a German robotics funding round."""
    return {"event_id": eid, "company": f"Company {eid}", "entity_key": ekey, "materiality": mat, "event_date": day, "headline": f"Headline {eid}",
            "summary": "", "event_type": "funding", "round": "", "amount_m": None, "geo": ["DE"], "themes": ["robotics"], "noise": mat == "NOISE",
            "sources": [{"publisher": f"Invented Daily {eid}", "url": f"https://news.invented.example/{eid}", "published": day,
                         "headline": f"Headline {eid}", "independence": "independent"}],
            "backcast": [], "card": None, "materiality_why": ["rule"], **kw}


NEWS_CASE = {  # review 028a: an invented curated case the GET seeds (the old ``seed_cases``), in its file's key order
    "event_id": "nw-case-1", "curated": True, "company": "Invented Case Robotics", "company_from": "curated case",
    "headline": "Invented Case Robotics passes a $1 billion valuation", "summary": "A secondary sale set the price.",
    "event_type": "valuation", "round": "", "amount_m": 1000, "event_date": "2026-10-05", "geo": ["DE"], "themes": ["robotics"],
    "noise": False, "sources": [{"publisher": "Invented Wire", "url": "https://wire.invented.example/case", "published": "2026-10-05",
                                 "headline": "Invented Case Robotics valued at $1bn", "text_sha": "case", "independence": "independent"}],
    "backcast": [{"date": "2021", "precision": "year", "text": "an invented lab spinout", "family": "university_lab",
                  "url": "https://lab.invented.example/", "kind": "known_early_signal"}],
    "learning": "",
}


def news_cases() -> dict[str, str]:
    return {"case-1.json": json.dumps(NEWS_CASE, ensure_ascii=False, indent=2) + "\n"}


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
        "nw-7": news_event("nw-7", key(batch(7)), "HIGH", "2026-11-09", event_type="acquisition"),
        "nw-m": news_event("nw-m", "invented backcast miss", "HIGH", "2026-11-03", backcast=[
            {"date": "2026-10-01", "precision": "day", "text": "an invented grant list", "family": "grant",
             "url": "https://grant.invented.example/", "kind": "known_early_signal"}]),
    }, "seeded": []}


def main_news_docs() -> dict[str, Any]:
    """Review 028a: the rest of the News store the News panel and the packet read."""
    pubs = {"Invented Daily nw-1": [{"role": "EARLY SIGNAL", "basis": "observed", "evidence": "mentioned 3 companies early"}],
            "Invented Daily nw-a": [{"role": "SECONDARY COVERAGE", "basis": "observed", "evidence": "syndicated 9/16"}],
            "Invented Daily nw-9": [{"role": "CORE EUROPEAN INTELLIGENCE", "basis": "observed", "evidence": "covered 9/15"}]}
    window = {"benchmark_events": 7, "sources": {p: {"name": p, "kind": "feed", "roles": r} for p, r in pubs.items()}}
    return {
        "news/actions.jsonl": jl([{"kind": "outcome_decision", "event_id": "nw-7", "decision": "reject", "at": "2026-11-10T09:00:00"},
                                  {"kind": "miss_audit", "event_id": "nw-m", "audit_id": "au-m04", "at": "2026-11-10T09:00:00"}]),
        "news/runs.jsonl": jl([{"run_id": "news-1", "at": "2026-11-11T07:00:00", "status": "partial"}]),
        "news/source_metrics.json": {"at": "2026-11-11T16:05:00", "windows": {"90": window}},
        "scan_history.json": {"scans": [{"run_id": "2026-09-27T08-00-00"}]},
        CASES_KEY: news_cases(),
    }


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
        **main_news_docs(),
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


def _with_cases(fn: Any) -> Any:
    """Every set names its own curated case folder (review 028a): an empty one unless it has cases."""
    return lambda: {CASES_KEY: {}, **fn()}


SETS: dict[str, Any] = {"main": main_docs, "today": _with_cases(today_docs), "torn": _with_cases(torn_docs),
                        "broken": _with_cases(broken_docs), "empty": _with_cases(dict)}
# fmt: on


# ------------------------------------------------------------------ the oracle
def run_oracle(inp: dict[str, Any], files: dict[str, bytes], cases: Any = ...) -> dict[str, Any]:
    """The 027a oracle over a scratch folder; ``cases``: the curated case folder (``...``: the old one, for the real
    snapshot)."""
    return scratch_oracle(ORACLE, inp, files, cases, prefix="pz-validation-oracle-")


# ------------------------------------------------------------------ the new side and the declared normalisation
def _answer(fn: Any) -> dict[str, Any]:
    try:
        body = fn()
    except Exception as exc:  # the old route would have answered 500
        return {"raises": type(exc).__name__}
    return {"code": 200, "body": js(body)}


_FALLBACK = {  # decision (c): the section header -> the old fallback line
    "== SOURCE NETWORK": "- none in probation yet",
}


def old_packet(body: dict[str, Any]) -> dict[str, Any]:
    """Decision (c): the new packet as the old code answered with the source network unavailable."""
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
    """Decision (d): the deferred native-bridge panel as the old code answered with it unavailable."""
    body = dict(body)
    if body.get("native_bridge") != {"available": False, "reason": NATIVE_BRIDGE_REASON}:
        problems.append(f"{label}/native_bridge: not the deferred native-bridge panel")
    keys = list(body)
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

    out = {"view": v, "packets": packets, "build": _answer(ents), "news_saved": news_saved(inputs, now)}
    if inputs != inputs_before:
        problems.append("/inputs: Validation changed its inputs")
    if docs != docs_before:
        problems.append("/docs: inputs_from_docs changed the documents")
    return out, problems


def news_saved(inputs: Any, now: datetime) -> Any:
    """Review 028a: what the old News GET's seeding saved (the old guard, then ``seed_cases``), or ``None``."""
    news = inputs.news_inputs
    try:
        if news.cases is not None and len(news_load(news.events)["seeded"]) < len(news.cases):
            doc, added = seed_cases(news.events, news.cases, now)
            return js(doc) if added else None
    except Exception:
        return None
    return None


def _text(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def compare_set(name: str, s: dict[str, Any]) -> list[str]:
    expected = s["expected"]
    problems: list[str] = []
    if expected.get("changed"):
        problems.append(f"/{name}/changed: the OLD read changed {expected['changed']}")
    got, invariants = new_side(s["docs"], s["clock"], list(expected["packets"]))
    problems += [f"/{name}{p}" for p in invariants]
    for part in ("view", "packets", "build", "news_saved"):
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
        files, cases = split_cases(docs)
        oracle = run_oracle({"clock": CLOCK, "extra_cycles": EXTRA_CYCLES}, files, cases)
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
    from projectzero.validation import store

    load_dotenv()
    settings = Settings.from_env()
    snapshot_ = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    files = {f.path: f.raw for f in snapshot_.files()}
    old = run_oracle({"clock": REAL_CLOCK, "extra_cycles": EXTRA_CYCLES}, files)
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
            stored_logs = store.texts(c, schema)
        # review 027b: the importer's backfill holds every archived log line, in order, byte for byte
        for path in store.PATHS.values():
            raw = files.get(path)
            if raw is None:
                if stored_logs[path]:
                    problems.append(f"/{path}: rows without an archive")
                continue
            lines = re.split(r"\r\n|\r|\n", raw.decode("utf-8-sig"))
            if lines and lines[-1] == "":
                lines.pop()
            if stored_logs[path] != "".join(f"{line}\n" for line in lines):
                problems.append(f"/{path}: the backfilled lines differ from the archive")
        report_logs = {p: stored_logs[p].count("\n") for p in store.PATHS.values()}
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
                  "tables_checked": len(before), "old_changed": old.get("changed"), "log_lines": report_logs}  # fmt: skip
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    report["differences"] = len(problems)
    print(json.dumps(report, indent=2, default=str, ensure_ascii=False))
    for line in problems[:60]:
        print("  DIFF", line)
    print("VALIDATION PARITY PASSED" if not problems else "VALIDATION PARITY FAILED")
    return 1 if problems else 0


# ------------------------------------------------------------------ review 027b: the writes
WRITES_ORACLE = REPO_ROOT / "scripts" / "oracle" / "validation_writes_oracle.py"
WRITES_GOLDEN = GOLDEN_DIR / "oracle_validation_writes.json"
WRITE_WORLDS = ("main", "empty")
SEAM_SIZE = 12  # id-seam values per step (the most ids one step makes: a confirmed import's usable rows)


def seam(i: int) -> list[str]:
    """The id seam of step ``i``: the old ``str(datetime.now().timestamp())`` answers, the new ``new_hex()``."""
    return [f"{i:04x}{k:08x}" for k in range(SEAM_SIZE)]


BENCH = "Name,First Seen\nInvented Alpha Robotics,2026-10-01\nInvented Unknown Benchmark Co,2026-09-01\n,2026-09-02\nInvented Bad Date Co,not a date\nInvented Future Bench Co,2027-01-01\nInvented Unknown Benchmark Co,2026-09-01\n"
BENCH_OVERRIDE = "Org Label,When Listed,Company,Date\nInvented Kappa Kept,2026-10-02,Invented Ignored Name,2026-01-01\nInvented Override Only Co,2026-10-03,x,2026-01-01\n"
BENCH_STRIP = "  Company Name  ,Launch Date,Last Funding Date\nInvented Batch Co 5,2026-09-09,2026-10-10\nInvented Strip Co,2026-09-10,\nInvented Late Extra Co,2026-09-11,2026-10-11,surplus\n"
EXTRA = "name,date\nInvented Extra Co,2026-10-01,surplus\n"  # decision (e): the old None-key 500
UNQUOTED_CR = (
    "name,date\nInvented Good Co,2026-10-01\nInvented\rBroken,2026-10-01\n"  # decision (e): the old csv.Error 500
)


# fmt: off
def _outcome_steps() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for n, kind in enumerate(KIND_CYCLE):  # every outcome kind, with and without an evidence URL
        for with_url in (True, False):
            company = "Invented Kappa Kept" if kind == "institutional_round" and with_url else f"Invented Write Co {n}{'u' if with_url else ''}"
            steps.append({"op": "outcome", "body": {"kind": kind, "company": f"  {company} ", "event_date": f"2026-11-0{n % 9 + 1}",
                                                     "evidence_url": f" https://press.invented.example/w{n} " if with_url else "",
                                                     "note": f"note {n}", "candidate_id": f"k{n}" if n % 2 else "",
                                                     "benchmark_system": "Invented DB"}})
    steps += [
        {"op": "outcome", "body": {"kind": "rumour", "company": "Invented Write Co", "event_date": "2026-11-01"}},
        {"op": "outcome", "body": {"company": "Invented Write Co", "event_date": "2026-11-01"}},
        {"op": "outcome", "body": {"kind": "accelerator", "company": "   ", "event_date": "2026-11-01"}},
        {"op": "outcome", "body": {"kind": "accelerator", "company": "Invented Write Co"}},
        {"op": "outcome", "body": {"kind": "accelerator", "company": "Invented Write Co", "event_date": "2026-13-01"}},
        {"op": "outcome", "body": {"kind": "accelerator", "company": "Invented Write Co", "event_date": "2026-11-13"}},  # the future
        {"op": "outcome", "body": {"kind": "accelerator", "company": "Invented Today Co", "event_date": "2026-11-12"}},
        {"op": "outcome", "body": {"kind": "accelerator", "company": "Invented Time Co", "event_date": " 2026-11-01T09:00:00 "}},
        {"op": "outcome", "body": {"kind": "acquisition", "company": "Invented Write Co", "event_date": "2026-11-01", "evidence_url": "ftp://invented.example/x"}},
        {"op": "outcome", "body": {"kind": "institutional_round", "company": batch(11), "event_date": "2026-10-17",
                                   "evidence_url": "http://press.invented.example/11c", "supersedes": "oc-050"}},  # a supersede
        {"op": "outcome", "body": {"kind": "external_db_listing", "company": "Invented Long " + "N" * 200, "event_date": "2026-10-01",
                                   "evidence_url": "https://db.invented.example/" + "u" * 600, "note": "n" * 600, "candidate_id": "c" * 100,
                                   "benchmark_system": "S" * 80}},
        {"op": "outcome", "body": {"kind": "shutdown", "company": "Invented Café Œuvre GmbH", "event_date": "2026-10-02",
                                   "note": "fermé — “quoted” and ünïcode", "supersedes": ""}},
        {"op": "outcome", "body": {"kind": "weak_outcome", "company": "Invented Separator Co", "event_date": "2026-10-03",
                                   "note": "a line" + chr(0x2028) + "separator"}},  # the old reader split the line: unreadable, on both sides
        {"op": "outcome", "body": {"kind": "omar_declined", "company": 12345, "event_date": "2026-10-04", "note": 7, "candidate_id": 9}},
    ]
    return steps


MISS_COMPANIES = ("Invented Missed New Co 1", "Invented Watch Optics", "Invented Rejected Grid", "Invented Beta Funded",
                  "Invented Research Lab", "Invented Alpha Robotics", batch(5), "Invented Kappa Kept", "Invented Gamma Grid")


def _audit_steps() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for n, (reason, company) in enumerate(zip(MISS_REASONS, MISS_COMPANIES, strict=True)):  # every why_missed
        steps.append({"op": "audit", "body": {"type": "miss", "company": company, "why_missed": reason,
                                               "outcome_date": "2026-10-15" if n == 5 else "", "earliest_signal": f"signal {n}",
                                               "earliest_signal_date": ("2026-06-01", "bad", "")[n % 3], "signal_source": "Invented Lab Site",
                                               "should_have_found": "s-lab", "preventable": ("yes", "no", "unclear", "maybe", None)[n % 5],
                                               "improvement": "watch it", "note": f"miss {n}"}})
    steps += [
        {"op": "audit", "body": {"type": "miss", "company": "Invented Watch Optics", "why_missed": "forgot"}},  # context, then refused
        {"op": "audit", "body": {"type": "miss", "company": "Invented Missed New Co 2"}},
        {"op": "audit", "body": {"type": "other", "company": "Invented FP Co"}},
        {"op": "audit", "body": {"company": "Invented FP Co"}},
        {"op": "audit", "body": {"type": "false_positive", "company": "  "}},
        {"op": "audit", "body": {"type": "false_positive", "company": "Invented FP New Co", "causes": ["ai_wrapper", "nonsense", "model_error"],
                                 "lesson": "l" * 600, "note": "x" * 900}},
        {"op": "audit", "body": {"type": "false_positive", "company": "Invented FP New Co", "causes": []}},  # no cause
        {"op": "audit", "body": {"type": "false_positive", "company": "Invented FP New Co", "causes": ["nonsense"]}},
        {"op": "audit", "body": {"type": "false_positive", "company": "Invented FP New Co"}},
        {"op": "audit", "body": {"type": "false_positive", "company": "Invented FP Co 3", "causes": ["poor_market"], "supersedes": "au-f03"}},
        {"op": "audit", "body": {"type": "miss", "company": "Invented Missed Over Co", "why_missed": "other", "supersedes": "au-m02",
                                 "earliest_signal": "s" * 400, "signal_source": "t" * 400, "should_have_found": "u" * 200, "improvement": "v" * 600}},
    ]
    return steps


def _retract_steps(outcome_at: int, audit_at: int) -> list[dict[str, Any]]:
    return [
        {"op": "retract", "body": {"id": "oc-001", "reason": "duplicate entry, wrong company"}},
        {"op": "retract", "body": {"id": "au-f05", "reason": "not a false positive after all"}},
        {"op": "retract", "body": {"reason": "entered by mistake today"}, "id_from": outcome_at},
        {"op": "retract", "body": {"reason": "entered by mistake today"}, "id_from": audit_at},
        {"op": "retract", "body": {"id": "no-such-id", "reason": "nothing to retract here"}},
        {"op": "retract", "body": {"id": "oc-001", "reason": "too sho"}},  # a short reason
        {"op": "retract", "body": {"id": "oc-001", "reason": "   1234567   "}},
        {"op": "retract", "body": {"id": "oc-c0", "reason": "12345678"}},
        {"op": "retract", "body": {"id": "rx-1", "reason": "retract the retraction"}},
        {"op": "retract", "body": {"reason": "no id given at all"}},
        {"op": "retract", "body": {"id": "au-m03", "reason": "r" * 400}},
    ]


def _benchmark_steps() -> list[dict[str, Any]]:
    return [
        {"op": "benchmark", "body": {"system": "Invented DB", "csv": BENCH}},  # the preview
        {"op": "benchmark", "body": {"system": " Invented DB ", "csv": BENCH, "confirm": True}},
        {"op": "benchmark", "body": {"system": "Invented Other DB", "csv": BENCH_OVERRIDE, "name_column": "ORG LABEL", "date_column": "when listed", "confirm": 1}},
        {"op": "benchmark", "body": {"system": "Invented Other DB", "csv": BENCH_OVERRIDE, "name_column": "no such", "date_column": ""}},
        {"op": "benchmark", "body": {"system": "Invented Strip DB", "csv": BENCH_STRIP, "confirm": "yes"}},
        {"op": "benchmark", "body": {"system": "Invented DB", "csv": "name,date\r\nInvented Crlf Co,2026-10-05\r\n", "confirm": True}},
        {"op": "benchmark", "body": {"system": "Invented DB", "csv": "a,b\n1,2\n"}},  # too short
        {"op": "benchmark", "body": {"csv": BENCH}},
        {"op": "benchmark", "body": {"system": "Invented DB", "csv": "name,date\n"}},  # no rows
        {"op": "benchmark", "body": {"system": "Invented DB", "csv": "foo,bar\n1,2\n3,4\n"}},  # unknown columns
        {"op": "benchmark", "body": {"system": "Invented DB", "csv": "﻿name,date\nInvented Bom Co,2026-10-01\n"}},
        {"op": "benchmark", "body": {"system": "Invented DB", "csv": EXTRA}, "declared": "e"},
        {"op": "benchmark", "body": {"system": "Invented DB", "csv": EXTRA, "confirm": True}, "declared": "e"},
        {"op": "benchmark", "body": {"system": "Invented DB", "csv": UNQUOTED_CR, "confirm": True}, "declared": "e"},
    ]


def _with_seams(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**s, "seam": seam(i)} for i, s in enumerate(steps)]


def main_steps() -> list[dict[str, Any]]:
    outcomes = _outcome_steps()
    steps = outcomes + _audit_steps()
    steps += _retract_steps(0, len(outcomes) + 1) + _benchmark_steps()
    steps += [{"op": "mark", "body": {"cycle": ""}}, {"op": "mark", "body": {"cycle": "c-9"}},
              {"op": "mark", "body": {"cycle": "no-such-cycle"}},
              {"op": "audit", "body": {"type": "miss", "company": "Invented Late Miss Co", "why_missed": "other", "earliest_signal": "a late signal"}},
              {"op": "mark", "body": {"cycle": "c-9"}}]  # the packet after a new audit
    return _with_seams(steps)


def empty_steps() -> list[dict[str, Any]]:
    return _with_seams([
        {"op": "outcome", "body": {"kind": "accelerator", "company": "Invented Empty Co", "event_date": "2026-11-01"}},
        {"op": "audit", "body": {"type": "miss", "company": "Invented Empty Co", "why_missed": "source_not_covered"}},
        {"op": "audit", "body": {"type": "false_positive", "company": "Invented Empty FP", "causes": ["other"]}},
        {"op": "retract", "body": {"reason": "entered by mistake today"}, "id_from": 0},
        {"op": "retract", "body": {"reason": "entered by mistake today"}, "id_from": 1},
        {"op": "retract", "body": {"id": "oc-none", "reason": "nothing to retract here"}},
        {"op": "benchmark", "body": {"system": "Invented DB", "csv": BENCH}},
        {"op": "benchmark", "body": {"system": "Invented DB", "csv": BENCH, "confirm": True}},
        {"op": "benchmark", "body": {"system": "Invented DB", "csv": EXTRA, "confirm": True}, "declared": "e"},
        {"op": "mark", "body": {}},
    ])


WRITE_STEPS: dict[str, Any] = {"main": main_steps, "empty": empty_steps}
# fmt: on


def run_writes_oracle(inp: dict[str, Any], files: dict[str, bytes], cases: Any = ...) -> dict[str, Any]:
    return scratch_oracle(WRITES_ORACLE, inp, files, cases, prefix="pz-validation-writes-oracle-")


def write_answer(fn: Any) -> tuple[dict[str, Any], list[list[str]], writes.Written | None]:
    """The new route's answer for one pure write, the ``[log, text]`` it appends (``line + "\\n"``, what the old
    ``storage.append_line`` wrote) and the ``Written``."""
    try:
        w = fn()
    except writes.StalePacket as exc:
        return {"code": 409, "error": str(exc)}, [], None
    except ValidationError as exc:
        return {"code": 400, "error": str(exc)}, [], None
    except Exception as exc:  # the route would answer 500
        return {"raises": type(exc).__name__}, [], None
    return {"code": 200, "body": js(w.answer)}, [[log, line + "\n"] for log, line in w.appends], w


def new_writes(docs: dict[str, Any], clock: str, steps: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """The pure writes over the inputs, each step's lines appended to the inputs' log texts (``writes.appended``),
    then the 027a ``view``. Decision (f): a mark sends the ``{cycle, generated, sha}`` of the packet the GET shows at
    that moment; a stale sha (409) and a missing ``generated`` (400) are checked refused with nothing appended."""
    now = datetime.fromisoformat(clock)
    today = now.date()
    inputs = inputs_from_docs(docs, today)
    problems: list[str] = []
    fns = {
        "outcome": writes.outcome,
        "audit": writes.audit,
        "retract": writes.retract,
        "benchmark": writes.benchmark_import,
    }
    results: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        body = dict(step["body"])
        if step.get("id_from") is not None:
            body["id"] = results[step["id_from"]]["answer"]["body"]["entry"]["id"]
        hexes = list(step["seam"])
        before = copy.deepcopy(inputs)
        sent: dict[str, Any] = {}
        if step["op"] == "mark":
            shown = scout_packet(inputs, str(body.get("cycle") or ""), today, now)
            sent = {"cycle": body.get("cycle"), "generated": writes.generated_at(shown["text"]), "sha": shown["sha"]}
            for bad, code in (({**sent, "sha": "0" * 16}, 409), ({**sent, "generated": ""}, 400)):
                refused, lines, _ = write_answer(
                    lambda bad=bad, ins=inputs: writes.packet_mark(ins, bad, today=today, now=now)
                )
                if refused.get("code") != code or lines:
                    problems.append(f"/steps[{i}]/mark: {bad} answered {refused} (expected {code}, nothing appended)")
            answer, lines, w = write_answer(lambda ins=inputs, b=sent: writes.packet_mark(ins, b, today=today, now=now))
        else:
            fn = fns[step["op"]]
            answer, lines, w = write_answer(
                lambda: fn(inputs, body, today=today, now=now, new_hex=lambda: hexes.pop(0))  # noqa: B023 - called now
            )
        if inputs != before:
            problems.append(f"/steps[{i}]: the write changed its inputs")
        if w is not None:
            inputs = writes.appended(inputs, w.appends)
        results.append({"answer": answer, "appended": lines, "sent": sent})
    v = _answer(lambda: view(inputs, today, now))
    if "body" in v:
        v["body"] = old_view(v["body"], problems, "/view")
    return {"steps": results, "view": v}, problems


def _mark_problems(at: str, old: dict[str, Any], new: dict[str, Any], shas: dict[str, str]) -> list[str]:
    """Decision (f): the answer is the packet (027a's normalisation (c)); the logged line is the old one with the
    shown packet's sha in place of the regenerated one (equal at the frozen clock: checked)."""
    problems: list[str] = []
    old_body, new_body = old["answer"].get("body") or {}, new["answer"].get("body") or {}
    norm = {**new["answer"], "body": old_packet(new_body)} if new_body else new["answer"]
    problems += [f"{at}/answer{p}" for p in diff(js(old["answer"]), js(norm))]
    if _text(old["answer"]) != _text(norm):
        problems.append(f"{at}/answer: the serialized answer differs (key order)")
    if len(old["appended"]) != 1 or len(new["appended"]) != 1:
        return [*problems, f"{at}: appended {old['appended']} != {new['appended']}"]
    old_sha, new_sha = json.loads(old["appended"][0][1])["sha"], str(new_body.get("sha"))
    if old_sha != old_body.get("sha"):
        problems.append(f"{at}: the old mark did not log the sha of the text at the frozen clock")
    if new_sha != new["sent"].get("sha"):
        problems.append(f"{at}: the new mark did not log the shown packet's sha")
    shas[old_sha] = new_sha
    want = [old["appended"][0][0], old["appended"][0][1].replace(old_sha, new_sha)]
    if want != new["appended"][0]:
        problems.append(f"{at}/appended: {want!r} != {new['appended'][0]!r}")
    return problems


def compare_writes_set(name: str, s: dict[str, Any], clock: str) -> tuple[list[str], dict[str, int]]:
    expected = s["expected"]
    problems: list[str] = []
    declared = {"e": 0, "f": 0}
    if expected.get("changed"):
        problems.append(f"/{name}/changed: the OLD writes changed {expected['changed']}")
    got, invariants = new_writes(s["docs"], clock, s["steps"])
    problems += [f"/{name}{p}" for p in invariants]
    shas: dict[str, str] = {}
    for i, (step, old, new) in enumerate(zip(s["steps"], expected["steps"], got["steps"], strict=True)):
        at = f"/{name}/steps[{i}]({step['op']})"
        if step.get("declared") == "e":  # the old 500 -> a 400, nothing appended
            declared["e"] += 1
            ok = ("raises" in old["answer"] and not old["appended"] and new["answer"].get("code") == 400
                  and str(new["answer"].get("error", "")).startswith(writes.CSV_UNREADABLE) and not new["appended"])  # fmt: skip
            if not ok:
                problems.append(f"{at}: declared (e) not as declared: old {old}, new {new['answer']} {new['appended']}")
            continue
        if step["op"] == "mark":
            declared["f"] += 1
            problems += _mark_problems(at, old, new, shas)
            continue
        problems += [f"{at}/answer{p}" for p in diff(js(old["answer"]), js(new["answer"]))]
        if _text(old["answer"]) != _text(new["answer"]):
            problems.append(f"{at}/answer: the serialized answer differs (key order)")
        if old["appended"] != new["appended"]:  # byte for byte
            problems.append(f"{at}/appended: {old['appended']!r} != {new['appended']!r}")
    old_next = copy.deepcopy(expected["view"])
    last = ((old_next.get("body") or {}).get("scout") or {}).get("last_packet")
    if isinstance(last, dict) and last.get("sha") in shas:  # decision (f), as the next GET shows it
        last["sha"] = shas[last["sha"]]
    problems += [f"/{name}/view{p}" for p in diff(js(old_next), js(got["view"]))]
    if _text(old_next) != _text(got["view"]):
        problems.append(f"/{name}/view: the serialized answer differs (key order)")
    return problems, declared


def compare_writes(golden: dict[str, Any]) -> tuple[list[str], dict[str, int]]:
    problems: list[str] = []
    declared = {"e": 0, "f": 0}
    for name, s in golden["sets"].items():
        p, d = compare_writes_set(name, s, golden["clock"])
        problems += p
        declared = {k: declared[k] + d[k] for k in declared}
    return problems, declared


def writes_report(golden: dict[str, Any]) -> int:
    problems, declared = compare_writes(golden)
    for p in problems[:60]:
        print("  DIFF", p)
    print(f"declared: (e) {declared['e']} former-500 CSVs, (f) {declared['f']} packet marks")
    print("VALIDATION WRITES GOLDENS MATCH" if not problems else f"VALIDATION WRITES GOLDENS DIFFER ({len(problems)})")
    return 1 if problems else 0


def write_writes_goldens() -> int:
    sets: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    for name in WRITE_WORLDS:
        docs = SETS[name]()
        steps = WRITE_STEPS[name]()
        files, cases = split_cases(docs)
        oracle = run_writes_oracle({"clock": CLOCK, "steps": steps}, files, cases)
        meta = oracle.pop("meta")
        sets[name] = {"docs": docs, "steps": steps, "expected": oracle}
    golden = {"provenance": meta, "clock": CLOCK, "sets": sets}
    WRITES_GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=None) + "\n", encoding="utf-8", newline="\n")
    summary_ = {
        name: {
            "steps": len(s["steps"]),
            "ok": sum(1 for x in s["expected"]["steps"] if x["answer"].get("code") == 200),
            "refused": sum(1 for x in s["expected"]["steps"] if x["answer"].get("code") == 400),
            "raised": [x["answer"]["raises"] for x in s["expected"]["steps"] if "raises" in x["answer"]],
            "appended": sum(len(x["appended"]) for x in s["expected"]["steps"]),
            "changed": s["expected"]["changed"],
        }
        for name, s in sets.items()
    }
    print(json.dumps({"golden": str(WRITES_GOLDEN), "bytes": WRITES_GOLDEN.stat().st_size, "old": meta,
                      "summary": summary_}, indent=1, ensure_ascii=False))  # fmt: skip
    return writes_report(json.loads(WRITES_GOLDEN.read_text(encoding="utf-8")))


def main(argv: list[str]) -> int:
    if argv[1:] == ["real"]:
        return real()
    if argv[1:] == ["goldens"]:
        return write_goldens()
    if argv[1:] == ["writes-goldens"]:
        return write_writes_goldens()
    if argv[1:] == ["writes-check"]:  # the stored writes golden against the new code, without the oracle
        return writes_report(json.loads(WRITES_GOLDEN.read_text(encoding="utf-8")))
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
