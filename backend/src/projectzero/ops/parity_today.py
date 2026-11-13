# ruff: noqa: E501
# (the synthetic worlds: one record per line)
"""Today parity: the pure port against the OLD code as oracle, with a FIXED clock and no write (review 030a).

    python -m projectzero.ops.parity_today goldens   # (re)generates golden_v1/oracle_today.json (needs the old repo)
    python -m projectzero.ops.parity_today check     # the stored golden against the new code (no oracle)
    python -m projectzero.ops.parity_today real      # the real snapshot through the importer and the route vs the old

The oracle (``scripts/oracle/today_oracle.py``) runs the old ``services/today.view(date)`` once per world over a
scratch data folder holding the world's documents, the clock frozen at the world's ``clock`` (naive Berlin wall time),
the old view's stubs as the new side decides ((c) the two Scout sections answer ``[]``, (d) the scheduler raises and
the source network has no candidate, (e) ``_ready_proposals`` answers ``[]``), the pipeline's IMQ save in memory and
every other write blocked (the folder is checked unchanged). Each world is answered twice on both sides: as served,
and ``uncut`` (``MAX_ACTIONS`` lifted) so that every ranked action is compared, not only the first 7. The new side is the PURE port
(``today.inputs_from_docs`` -> ``today.view``) over the same documents at the same clock. Every answer is compared
value by value AND as serialized text (key order); the inputs and the documents are checked unchanged.

Declared differences, normalised here and nowhere else:

* (c) the old ``considered.native`` / ``considered.scout00`` (0 under the stubs, checked) are not in the new payload;
* (f) the new payload ends with ``snapshot`` (the Machine details' note): checked equal to ``SNAPSHOT_NOTE`` with the
  routes' ``at`` and the newest prepared case's ``prepared_at`` read from the documents here, then dropped.

(d) and (e) are the same stub on both sides: no difference in the payload.

The worlds hold INVENTED names only (the Project A rules are code: a candidate text naming Project A, or resembling a
portfolio company by its keywords; no real company name is in a document):

* ``main`` (2026-11-13): every action type and its rank / urgency branch: CONTACT_FOUNDER from the high slot (two,
  verified 82 and 78; an unresolved founder, ``sent_to_omar`` and a contacted company give none); ASK_OMAR_CONFLICT
  from the pipeline (potential conflict, unclear, a Project A relationship; top >= 65: rank 1, high) and from the
  triage (a relationship and a resemblance in INBOX order, a decided candidate left out); PREPARE_FOUNDER_CALL from the
  research queue through every contact state (not contacted, replied, follow-up due, no response, awaiting, call
  completed) and from the calls (two overdue tied at rank 2, one due, a fourth due row cut by ``[:3]`` before the
  filter, an upcoming one); REVIEW_VERIFICATION (and its replacement by a prepared case, the Omar-negative hold and its
  re-opening by later evidence); EVENT_ACTION at 2 and 5 days (a third cut by ``[:2]``, a planned, a sold-out and a
  past one left out); TRIAGE_REVIEW with NEEDS_MOHAMED over the attention budget of 2 (a decided candidate's route
  dropped); WATCH_TRIGGER high (two triggers of one company) and low (a dismissed trigger, a junk line); CASE_READY
  READY FOR MOHAMED, WAITING FOR HUMAN and DECIDE_WATCH_OR_DROP (an awaiting-founder, a stale and a gated case
  left out); more than 7 actions; every exception row.
* ``expired``: ``main`` at 2026-11-16, after the last prepared case expired: no CASE_READY (``considered.cases`` 0),
  the note's timestamps unchanged, the triage card unchanged.
* ``quiet``: rank ties (emerging and wildcard CONTACT_FOUNDER at the same verified score; TRIAGE_REVIEW calibration
  and a low WATCH_TRIGGER at rank 8, low, kept in section order); one unclear conflict below 65 (rank 5.5, the "1
  possible portfolio conflict for Omars" text); events at 10 and 13 days (rank 6), one without a city; one due call.
* ``failing``: a WATCH trigger whose label is a number (the section is "temporarily unavailable") and a route without
  a state (the triage section unavailable, ``triage: null``).
* ``norun``: routes but no compression run time (``triage: null``, the card still shown), a non-object attention
  budget (the defaults), a dropped company only.
* ``broken``: the pipeline and the call store exist but do not parse (the pipeline, prepared-case and calls sections
  "temporarily unavailable", the hold empty); the events and the triage still answer.
* ``empty``: no document at all.

In ``main`` one Radar company qualifies for IMQ: the old pipeline read saved its snapshot (in memory, ``saves`` 1;
the later old reads saw it), the new read saves nothing (a): the payload is the same.

Exit 1 on any difference.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from projectzero.conviction.operator import OperatorInputs, fingerprint
from projectzero.core.paths import REPO_ROOT
from projectzero.dealflow.ranking.names import slug
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js
from projectzero.today import UNREADABLE, inputs_from_docs, view
from projectzero.today import core as today_core
from projectzero.today.core import SNAPSHOT_NOTE

ORACLE = REPO_ROOT / "scripts" / "oracle" / "today_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_today.json"
CLOCK = "2026-11-13T09:00:00"
REAL_CLOCK = "2026-11-13T09:00:00"  # the real snapshot: before the last prepared case expires (2026-11-15 19:36)
EXPIRED_CLOCK = "2026-11-16T09:00:00"  # after the last prepared case (2026-11-01 19:36) passed its 14 days
TRIGGERS = "watch/triggers.jsonl"
DROPPED_KEYS = ("native", "scout00")  # decision (c)
UNCUT = 10**6  # MAX_ACTIONS lifted on both sides: every ranked action is compared, not only the first 7

FULL = {"founders": True, "funding": True, "traction": True}
NO_TRACTION = {"founders": True, "funding": True}
STRONG = {"founder": 22, "venture_scale": 17, "why_now": 13, "taste": 12, "insight": 8}
WEAK = {"founder": 8, "venture_scale": 9, "why_now": 6, "taste": 5, "insight": 2}


# ------------------------------------------------------------------ the synthetic worlds (invented names only)
def jl(rows: list[Any]) -> str:
    return "".join((r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)) + "\n" for r in rows)


def entry(company: str, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "company": company,
        "one_liner": f"{company} builds software for industrial operators",
        "status": "new",
        "scores": dict(STRONG),
        "earliness": "pre_seed",
        "conflict": "none",
        "archetype": 5,
        "verified": {},
        "founders": [],
        "discovery_date": "2026-11-01",
    }
    base.update(kw)
    return base


def person(pid: str, name: str, **kw: Any) -> dict[str, Any]:
    return {"id": pid, "name": name, **kw}


def case(
    e: dict[str, Any], fc: Any, prepared_at: str, code: str, label: str, decisions: list[str], **kw: Any
) -> dict[str, Any]:
    """A prepared case whose fingerprint matches the record as stored (the new ``fingerprint`` over the record with
    its slug; a mismatch would make the old code read it STALE: the parity would show it)."""
    fp = fingerprint({**e, "slug": slug(e["company"])}, OperatorInputs(founder_calls=fc))
    card = {"next_action": {"code": code, "label": label, "why": f"the invented case of {e['company']} says so"},
            "conflict": {"gated": kw.pop("gated", False)}, "decisions": [{"text": t} for t in decisions]}  # fmt: skip
    return {"prepared_at": prepared_at, "fingerprint": kw.pop("fp", fp), "card": card, **kw}


def ev(eid: str, name: str, start: str, **kw: Any) -> dict[str, Any]:
    return {"id": eid, "name": name, "start": start, "city": "Berlin", "url": f"https://events.invented.example/{eid}",
            "status": "new", "human_verified": True, **kw}  # fmt: skip


def cand(cid: str, name: str, description: str, decision: str = "new") -> dict[str, Any]:
    return {"id": cid, "name": name, "description": description, "decision": decision, "source": "invented-feed"}


def proposal(cid: str, machine: str = "KEEP") -> dict[str, Any]:
    return {"candidate_id": cid, "status": "proposed", "proposal": machine, "prompt_version": "v3",
            "input_sha": "invented", "stage": "stage1", "confidence": "medium"}  # fmt: skip


def route(name: str, state: str, priority: int | None, reason: str, **kw: Any) -> dict[str, Any]:
    return {"name": name, "state": state, "reason": reason, "priority": priority, "machine_proposal": "KEEP", **kw}


def trigger(
    tid: str, name: str, high: bool, first: str, label: Any, kind: str, evidence: str, **kw: Any
) -> dict[str, Any]:
    return {"id": tid, "name": name, "high_value": high, "first_observed": first, "label": label,
            "source_kind": kind, "evidence": evidence, "url": f"https://signals.invented.example/{tid}", **kw}  # fmt: skip


LONG = ("The invented registry shows a new filing with a capital increase, two new directors from an industrial "
        "group, and a renamed holding company that matches the founders' earlier venture in every detail listed.")  # fmt: skip


def founder_calls(
    *extra: tuple[str, str, str | None, str, dict[str, Any]], linked: dict[str, str] | None = None
) -> dict[str, Any]:
    """The call store: ``extra`` = (call id, company name, founder name or None, call date, next action)."""
    d: dict[str, Any] = {"version": 1, "label": "FOUNDER-REPORTED", "companies": {}, "founders": {}, "calls": {}}
    for i, (call_id, company, founder, when, na) in enumerate(extra, start=1):
        co, fo = f"co-{i}", f"fo-{i}"
        d["companies"][co] = {"id": co, "name": company, "linked_pipeline_slug": (linked or {}).get(company, "")}
        call = {"id": call_id, "company_id": co, "date": when, "call_type": "first", "next_action": na,
                "created": f"{when} 10:00:00", "updated": f"{when} 10:00:00"}  # fmt: skip
        if founder:
            d["founders"][fo] = {"id": fo, "name": founder}
            call["founder_id"] = fo
        if company == "Invented Nettlecombe":
            call["assessment"] = {"recommendation": "Follow up", "confidence": "medium"}
        d["calls"][call_id] = call
    return d


def main_docs() -> dict[str, Any]:
    fc = founder_calls(
        (
            "call-2",
            "Invented Wren Tools",
            "Invented Yusuf Hale",
            "2026-10-22",
            {"text": "Send the pilot terms", "due": "2026-11-01"},
        ),
        (
            "call-1",
            "Invented Yarrow Health",
            "Invented Zora Lind",
            "2026-10-20",
            {"text": "Share the reference list", "due": "2026-11-01"},
        ),
        ("call-4", "Invented Moss Freight", None, "2026-11-03", {"text": "Ask for the data room", "due": "2026-11-13"}),
        (
            "call-3",
            "Invented Linden Power",
            "Invented Ines Aldo",
            "2026-11-02",
            {"text": "Book the technical call", "due": "2026-11-13"},
        ),
        (
            "call-5",
            "Invented Kew Materials",
            "Invented Hugo Pell",
            "2026-11-04",
            {"text": "Send the memo", "due": "2026-11-15"},
        ),
        ("call-6", "Invented Nettlecombe", "Invented Nia Rowe", "2026-11-10", {"text": "Send the deck", "done": True}),
        linked={"Invented Nettlecombe": slug("Invented Nettlecombe")},
    )
    signals = [
        entry("Invented Arclight Systems", verified=FULL, founders=[{"name": "Invented Ada Brenner"}]),
        entry(
            "Invented Bramble Robotics",
            verified=FULL,
            conflict="similar",
            founders=[{"name": "Invented Ben Okafor"}],
            imq_trigger={
                "kind": "funding",
                "date": "2026-11-05",
                "url": "https://news.invented.example/bramble",
                "fact": "Invented Bramble Robotics opened its seed round",
                "by": "operator",
            },
        ),
        entry(
            "Invented Corvid Labs",
            verified=FULL,
            founders=[{"name": "Invented Cleo Varga"}],
            outreach=[{"kind": "outreach_sent", "date": "2026-11-10", "channel": "email"}],
        ),
        entry("Invented Wexcombe", verified=FULL, founders=[{"name": "Invented Wim Dorr"}]),
        entry(
            "Invented Yelverton", verified=FULL, founders=[{"name": "Invented Ada Brenner"}], sent_to_omar="2026-11-01"
        ),
        entry("Invented Dunmore Analytics", verified=FULL, conflict="potential_conflict"),
        entry(
            "Invented Eskerfield",
            conflict="unclear",
            scores={**WEAK, "founder": 20, "venture_scale": 14, "why_now": 11},
        ),
        entry("Invented Fennick Bio", one_liner="Seed round led by Project A partners", verified={}),
        entry("Invented Galloway Freight", verified=NO_TRACTION),
        entry(
            "Invented Harrow Metrics",
            verified=NO_TRACTION,
            conflict="unclear",
            outreach=[
                {"kind": "outreach_sent", "date": "2026-11-01"},
                {"kind": "reply_received", "date": "2026-11-08"},
            ],
        ),
        entry(
            "Invented Ilford Quantum",
            verified=NO_TRACTION,
            conflict="complementary",
            outreach=[{"kind": "outreach_sent", "date": "2026-10-29", "channel": "linkedin"}],
        ),
        entry("Invented Juniper Grid", verified={"founders": True}),
        entry("Invented Kestrel Defence", verified={}, omar_outcome="negative", omar_outcome_at="2026-11-05T10:00:00"),
        entry(
            "Invented Vellacott",
            verified={"funding": True},
            omar_outcome="negative",
            omar_outcome_at="2026-11-01T10:00:00",
            imq_trigger={"recorded": "2026-11-09T12:00:00"},
        ),
        entry("Invented Larch Dynamics", verified=FULL, status="dropped", founders=[{"name": "Invented Ada Brenner"}]),
        entry(
            "Invented Mallow Sensors",
            verified=NO_TRACTION,
            outreach=[
                {"kind": "outreach_sent", "date": "2026-09-20"},
                {"kind": "follow_up_sent", "date": "2026-10-15"},
            ],
        ),
        entry("Invented Nettlecombe", verified=NO_TRACTION),
        entry("Invented Ovenden Works", scores=dict(WEAK), earliness="unknown"),
        entry("Invented Pellow Farms", scores=dict(WEAK), earliness="unknown"),
        entry("Invented Quarry Point", scores=dict(WEAK), earliness="unknown"),
        entry("Invented Ruddock Labs", scores=dict(WEAK), earliness="unknown"),
        entry("Invented Selby Optics", scores=dict(WEAK), earliness="unknown"),
    ]
    by = {e["company"]: e for e in signals}
    cases = {
        slug("Invented Juniper Grid"): case(
            by["Invented Juniper Grid"],
            fc,
            "2026-11-01T19:36:00",
            "VERIFY_AND_CALL",
            "Verify the founders' prior exit",
            ["Is the pilot paid?", "Does the grid operator sign?"],
        ),
        slug("Invented Ovenden Works"): case(
            by["Invented Ovenden Works"],
            fc,
            "2026-10-31T09:00:00",
            "PREP_CALL",
            "Prepare a founder call",
            ["Is the team full-time?"],
            seen_at="2026-11-02T08:00:00",
        ),
        slug("Invented Pellow Farms"): case(
            by["Invented Pellow Farms"], fc, "2026-10-30T16:58:00", "DECIDE_WATCH_OR_DROP", "Decide watch or drop", []
        ),
        slug("Invented Quarry Point"): case(
            by["Invented Quarry Point"],
            fc,
            "2026-10-30T12:00:00",
            "AWAIT_FOUNDER_RESPONSE",
            "Wait for the founder",
            ["Reply?"],
        ),
        slug("Invented Ruddock Labs"): case(
            by["Invented Ruddock Labs"],
            fc,
            "2026-10-30T12:00:00",
            "PREP_CALL",
            "Prepare a founder call",
            ["Stale?"],
            fp="an-older-fingerprint",
        ),
        slug("Invented Selby Optics"): case(
            by["Invented Selby Optics"], fc, "2026-10-30T12:00:00", "ASK_OMAR", "Ask Omar", ["Conflict?"], gated=True
        ),
    }
    people = [
        person("p-1", "Invented Ada Brenner", identity_status="resolved"),
        person("p-2", "Invented Ben Okafor", provenance="user_provided"),
        person("p-3", "Invented Cleo Varga", identity_status="resolved"),
        person("p-4", "Invented Wim Dorr"),
    ]
    events = [
        ev("ev-1", "Invented Founders Forge Night", "2026-11-15"),
        ev("ev-2", "Invented Deep Tech Breakfast", "2026-11-18", city="Munich"),
        ev("ev-3", "Invented Robotics Salon", "2026-11-19"),
        ev("ev-4", "Invented Seed Sprint", "2026-11-14", status="planned"),
        ev("ev-5", "Invented Climate Pitch", "2026-11-16", price={"availability": "https://schema.org/SoldOut"}),
        ev("ev-6", "Invented Past Meetup", "2026-11-01"),
    ]
    inbox = [
        cand("c-205", "Invented Rookwood", "Pre-seed round led by Project A for industrial robotics"),
        cand("c-101", "Invented Quillon", "AI agents for freight forwarders: quoting, tenders, rates, bookings"),
        cand("c-150", "Invented Sablewood", "Angel round backed by Project A partners", decision="rejected"),
        cand("c-104", "Invented Tamworth Optics", "Photonic sensors for factory lines"),
        cand("c-106", "Invented Ashby Motion", "Motion control for small robots"),
        cand("c-107", "Invented Brindle Works", "Welding inspection software"),
        cand("c-108", "Invented Carrow Data", "Plant data pipelines"),
        cand("c-109", "Invented Dalby Air", "Air quality sensors"),
        cand("c-110", "Invented Elm Retail", "Shop analytics"),
        cand("c-111", "Invented Frome Fleet", "Fleet maintenance planning"),
        cand("c-112", "Invented Garth Bio", "Lab automation", decision="rejected"),
        cand("c-113", "Invented Hale Chem", "Chemical process control"),
    ]
    routes = {
        "c-104": route("Invented Tamworth Optics", "NEEDS_MOHAMED", 41, "Sparse but strong: " + LONG, resurfaced=True),
        "c-106": route("Invented Ashby Motion", "NEEDS_MOHAMED", 33, "Only a human can move it: founders unknown"),
        "c-107": route("Invented Brindle Works", "CALIBRATION_SAMPLE", 5, "Weekly calibration sample"),
        "c-108": route("Invented Carrow Data", "BACKGROUND_RESEARCH", 20, "Waiting for more evidence"),
        "c-109": route("Invented Dalby Air", "MACHINE_WATCH", 14, "Watch for a round"),
        "c-110": route("Invented Elm Retail", "DEFERRED_LOW_PRIORITY", 2, "Consumer retail"),
        "c-111": route("Invented Frome Fleet", "CONFLICT_GATED", 25, "Resembles a portfolio company"),
        "c-112": route("Invented Garth Bio", "NEEDS_MOHAMED", 50, "Decided since the run"),
        "c-113": route("Invented Hale Chem", "CASE_PREPARING", 31, "Queued for case preparation", resurfaced=True),
    }
    return {
        "real_data.json": {"week": "2026-W46", "signals": signals},
        "people.json": {"people": people},
        "founder_calls.json": fc,
        "case_prep/cases.json": {"cases": cases},
        "config.json": {"home_base": "Berlin", "attention_budget": {"human_review_daily_limit": 2, "invented_key": 9}},
        TRIGGERS: jl(
            [
                trigger(
                    "w-2",
                    "Invented Tamworth Optics",
                    False,
                    "2026-11-08T08:00:00",
                    "New hire",
                    "careers_page",
                    "A head of manufacturing joined",
                    url="",
                    source="careers page",
                ),
                trigger(
                    "w-1",
                    "Invented Tamworth Optics",
                    True,
                    "2026-11-10T08:00:00",
                    "Funding round",
                    "registry_filing",
                    LONG,
                    candidate_id="c-104",
                ),
                "not a json line",
                trigger(
                    "w-3",
                    "Invented Ulverston Labs",
                    False,
                    "2026-11-09T08:00:00",
                    "Website change",
                    "company_site",
                    "The product page now lists a second sensor",
                ),
                trigger(
                    "w-4",
                    "Invented Ulverston Labs",
                    True,
                    "2026-11-11T08:00:00",
                    "Press mention",
                    "news_article",
                    "Dismissed earlier",
                ),
                {"kind": "status", "trigger_id": "w-4", "status": "dismissed", "at": "2026-11-12T09:00:00"},
            ]
        ),
        "events.json": {"events": events, "leads": []},
        "event_sources.json": {"sources": []},
        "inbox.json": {"candidates": inbox},
        "triage_proposals.json": {"proposals": {c: proposal(c) for c in ("c-101", "c-205", "c-150", "c-104", "c-106")}},
        "queue_routing.json": {
            "at": "2026-11-12T23:05:10",
            "elsewhere": 6,
            "runs": [{"at": "2026-11-12T23:05:10"}],
            "routes": routes,
        },
    }


def quiet_docs() -> dict[str, Any]:
    fc = founder_calls(
        (
            "call-1",
            "Invented Pike Robotics",
            "Invented Pia Moor",
            "2026-11-01",
            {"text": "Send the term sheet", "due": "2026-11-13"},
        )
    )
    tie = {"founder": 23, "venture_scale": 18, "why_now": 13, "taste": 10, "insight": 9}
    signals = [
        entry(
            "Invented Ormond Atlas",
            archetype=15,
            verified=FULL,
            scores=dict(tie),
            founders=[{"name": "Invented Oda Brix"}],
        ),
        entry(
            "Invented Tarn Robotics",
            archetype=7,
            emerging=True,
            verified=FULL,
            scores=dict(tie),
            founders=[{"name": "Invented Tom Aske"}],
        ),
        entry("Invented Umber Fields", conflict="unclear", scores=dict(WEAK)),
        entry("Invented Pellow Farms", scores=dict(WEAK), earliness="unknown"),
    ]
    pellow = signals[3]
    return {
        "real_data.json": {"signals": signals},
        "people.json": {
            "people": [
                person("p-1", "Invented Oda Brix", identity_status="resolved"),
                person("p-2", "Invented Tom", aliases=["Invented Tom Aske"], identity_status="resolved"),
            ]
        },
        "founder_calls.json": fc,
        "case_prep/cases.json": {
            "cases": {
                slug("Invented Pellow Farms"): case(
                    pellow, fc, "2026-11-10T10:00:00", "DECIDE_WATCH_OR_DROP", "Decide watch or drop", []
                )
            }
        },
        TRIGGERS: jl(
            [
                trigger(
                    "w-1",
                    "Invented Vane Instruments",
                    False,
                    "2026-11-09T08:00:00",
                    "Website change",
                    "company_site",
                    "A new careers page",
                )
            ]
        ),
        "events.json": {
            "events": [
                ev("ev-1", "Invented Hardware Summit", "2026-11-26", city=""),
                ev("ev-2", "Invented Founder Breakfast", "2026-11-23"),
            ]
        },
        "inbox.json": {
            "candidates": [
                cand("c-1", "Invented Ash Signal", "Signal processing"),
                cand("c-2", "Invented Birch Cloud", "Cloud tools"),
            ]
        },
        "triage_proposals.json": {"proposals": {"c-1": proposal("c-1")}},
        "queue_routing.json": {
            "at": "2026-11-12T22:00:00",
            "routes": {
                "c-2": route("Invented Birch Cloud", "CALIBRATION_SAMPLE", None, "Weekly calibration sample"),
                "c-1": route("Invented Ash Signal", "CALIBRATION_SAMPLE", 4, "Weekly calibration sample"),
            },
        },
    }


def failing_docs() -> dict[str, Any]:
    return {
        "real_data.json": {"signals": [entry("Invented Wold Systems", verified=NO_TRACTION)]},
        TRIGGERS: jl(
            [
                trigger(
                    "w-1",
                    "Invented Wold Systems",
                    True,
                    "2026-11-09T08:00:00",
                    5,
                    "registry_filing",
                    "A number as label",
                )
            ]
        ),
        "inbox.json": {"candidates": [cand("c-1", "Invented Ash Signal", "Signal processing")]},
        "queue_routing.json": {
            "at": "2026-11-12T22:00:00",
            "routes": {"c-1": {"name": "Invented Ash Signal", "priority": 3}},
        },
    }


def norun_docs() -> dict[str, Any]:
    return {
        "real_data.json": {"signals": [entry("Invented Yew Dynamics", verified=FULL, status="dropped")]},
        "config.json": {"attention_budget": ["not", "an", "object"]},
        "inbox.json": {"candidates": [cand("c-1", "Invented Ash Signal", "Signal processing")]},
        "queue_routing.json": {
            "routes": {"c-1": route("Invented Ash Signal", "NEEDS_MOHAMED", 12, "Founders unknown")}
        },
    }


def broken_docs() -> dict[str, Any]:
    """Two stores that exist but do not parse (raw text in place of JSON): the pipeline and the call store."""
    return {
        "real_data.json": "{ an unreadable pipeline",
        "founder_calls.json": "{ an unreadable call store",
        "events.json": {"events": [ev("ev-1", "Invented Founders Forge Night", "2026-11-15")]},
        "inbox.json": {
            "candidates": [
                cand("c-205", "Invented Rookwood", "Pre-seed round led by Project A for industrial robotics")
            ]
        },
        "triage_proposals.json": {"proposals": {"c-205": proposal("c-205")}},
    }


WORLDS: dict[str, tuple[Any, str]] = {
    "main": (main_docs, CLOCK),
    "expired": (main_docs, EXPIRED_CLOCK),
    "quiet": (quiet_docs, CLOCK),
    "failing": (failing_docs, CLOCK),
    "norun": (norun_docs, CLOCK),
    "broken": (broken_docs, CLOCK),
    "empty": (dict, CLOCK),
}


# ------------------------------------------------------------------ the oracle
def files_of(docs: dict[str, Any]) -> dict[str, bytes]:
    return {
        k: (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=2)).encode("utf-8")
        for k, v in docs.items()
    }


def run_oracle(worlds: dict[str, tuple[dict[str, Any], str]]) -> dict[str, Any]:
    return oracle_over({name: (files_of(docs), clock) for name, (docs, clock) in worlds.items()})


def oracle_over(worlds: dict[str, tuple[dict[str, bytes], str]]) -> dict[str, Any]:
    """The old view once per world, over a scratch data folder holding the world's files byte for byte."""
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-today-oracle-") as tmp:
        data = Path(tmp) / "data"
        for name, (files, _clock) in worlds.items():
            folder = data / name
            folder.mkdir(parents=True)
            for rel, raw in files.items():
                target = (folder / rel).resolve()
                if folder.resolve() not in target.parents:
                    raise SystemExit(f"refusing a path outside the scratch folder: {rel}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
        srcf, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
        inp = {"worlds": [{"name": n, "clock": c} for n, (_d, c) in worlds.items()]}
        srcf.write_bytes(json.dumps(inp, ensure_ascii=False).encode("utf-8"))
        env = {k: v for k, v in os.environ.items() if k != "SUPABASE_DB_URL" and not k.endswith(("_API_KEY", "_TOKEN"))}
        env.update(
            {
                "PZ_DATA": str(data),
                "PZ_TESTING": "1",
                "PZ_CASE_PREP": "0",
                "PYTHONPATH": str(OLD_REPO / "backend" / "src"),
            }
        )
        run = subprocess.run([str(python), str(ORACLE), str(srcf), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_bytes().decode("utf-8"))
        return out


# ------------------------------------------------------------------ the new side and the declared normalisation
def expected_snapshot(docs: dict[str, Any]) -> dict[str, Any]:
    """Decision (f), read from the documents independently of the port."""
    q = docs.get("queue_routing.json")
    doc = docs.get("case_prep/cases.json")
    cases = ((doc if isinstance(doc, dict) else {}).get("cases") or {}).values()
    stamps = [c["prepared_at"] for c in cases if isinstance(c, dict) and c.get("prepared_at")]
    return {"note": SNAPSHOT_NOTE, "triage_at": q.get("at") if isinstance(q, dict) else None,
            "cases_prepared_at": max(stamps) if stamps else None}  # fmt: skip


def as_read(docs: dict[str, Any]) -> dict[str, Any]:
    """The documents as the readers see them: a JSON document given as raw TEXT (a file that does not parse) is
    ``UNREADABLE``; the JSONL logs are their text."""
    return {k: UNREADABLE if isinstance(v, str) and not k.endswith(".jsonl") else v for k, v in docs.items()}


def _answer(inputs: Any, today: Any, now: datetime) -> dict[str, Any]:
    try:
        return {"ok": js(view(inputs, today, now))}
    except Exception as exc:  # the old route would have answered 500
        return {"raises": type(exc).__name__}


def new_side(docs: dict[str, Any], clock: str) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """The new answer and the ``uncut`` one (``MAX_ACTIONS`` lifted, as the oracle did)."""
    now = datetime.fromisoformat(clock)
    today = now.date()
    docs_before = copy.deepcopy(docs)
    inputs = inputs_from_docs(as_read(docs), today, now)
    inputs_before = copy.deepcopy(inputs, {id(UNREADABLE): UNREADABLE})  # the sentinel is compared by identity
    problems: list[str] = []
    answer = _answer(inputs, today, now)
    module = vars(today_core)
    shown = module["MAX_ACTIONS"]
    module["MAX_ACTIONS"] = UNCUT
    try:
        uncut = _answer(inputs, today, now)
    finally:
        module["MAX_ACTIONS"] = shown
    if inputs != inputs_before:
        problems.append("/inputs: Today changed its inputs")
    if docs != docs_before:
        problems.append("/docs: inputs_from_docs changed the documents")
    return answer, uncut, problems


def normalise_old(answer: dict[str, Any], problems: list[str]) -> dict[str, Any]:
    """(c): the two dropped sections' ``considered`` keys (0 under the stubs)."""
    out = copy.deepcopy(answer)
    body = out.get("ok")
    if isinstance(body, dict):
        for k in DROPPED_KEYS:
            if body["considered"].pop(k, None) != 0:
                problems.append(f"/considered/{k}: the stubbed section did not answer 0")
    return out


def normalise_new(answer: dict[str, Any], docs: dict[str, Any], problems: list[str]) -> dict[str, Any]:
    """(f): the snapshot note, checked then dropped."""
    out = copy.deepcopy(answer)
    body = out.get("ok")
    if isinstance(body, dict):
        if list(body)[-1:] != ["snapshot"]:
            problems.append("/snapshot: not the last key of the payload")
        got = body.pop("snapshot", None)
        if got != expected_snapshot(docs):
            problems.append(f"/snapshot: {got!r} != {expected_snapshot(docs)!r}")
    return out


def _text(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def compare_world(name: str, w: dict[str, Any]) -> list[str]:
    expected = w["expected"]
    problems: list[str] = []
    for k in ("changed", "blocked"):
        if expected.get(k):
            problems.append(f"/{name}/{k}: the OLD read wrote {expected[k]}")
    got, uncut, invariants = new_side(w["docs"], w["clock"])
    problems += [f"/{name}{p}" for p in invariants]
    for label, old_answer, new_answer in (("", {k: expected[k] for k in ("ok", "raises") if k in expected}, got),
                                          ("/uncut", expected["uncut"], uncut)):  # fmt: skip
        found: list[str] = []
        old = normalise_old(old_answer, found)
        new = normalise_new(new_answer, w["docs"], found)
        problems += [f"/{name}{label}{p}" for p in found]
        problems += [f"/{name}{label}{p}" for p in diff(js(old), js(new))]
        if _text(old) != _text(new):
            problems.append(f"/{name}{label}: the serialized answer differs (key order)")
    return problems


def compare_goldens(golden: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for name, w in golden["worlds"].items():
        problems += compare_world(name, w)
    return problems


def summary(golden: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, w in golden["worlds"].items():
        e = w["expected"]
        body = e.get("ok") or {}
        out[name] = {
            "clock": w["clock"],
            "actions": [a["type"] for a in body.get("actions") or []],
            "uncut": [a["type"] for a in (e["uncut"].get("ok") or {}).get("actions") or []],
            "more": body.get("more"),
            "considered": body.get("considered"),
            "exceptions": [x["text"] for x in body.get("exceptions") or []],
            "triage": None if not body.get("triage") else body["triage"]["total"],
            "imq_saves": e.get("saves"),
            "raises": e.get("raises"),
        }
    return out


def read_golden(path: Path = GOLDEN) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(path.read_bytes().decode("utf-8"))
    return out


def write_goldens() -> int:
    worlds = {name: (fn(), clock) for name, (fn, clock) in WORLDS.items()}
    oracle = run_oracle(worlds)
    by_name = {w.pop("name"): w for w in oracle["worlds"]}
    golden = {"provenance": oracle["meta"],
              "worlds": {n: {"clock": c, "docs": d, "expected": by_name[n]} for n, (d, c) in worlds.items()}}  # fmt: skip
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    # NOT sort_keys: the documents' insertion order is part of the input (and of what the oracle recorded)
    GOLDEN.write_bytes((json.dumps(golden, ensure_ascii=False, indent=None) + "\n").encode("utf-8"))
    return report(read_golden(), "TODAY GOLDENS")


def report(golden: dict[str, Any], label: str) -> int:
    problems = compare_goldens(golden)
    print(json.dumps({"golden": str(GOLDEN), "bytes": GOLDEN.stat().st_size, "old": golden["provenance"],
                      "summary": summary(golden)}, indent=1, ensure_ascii=False))  # fmt: skip
    for p in problems[:60]:
        print("  DIFF", p)
    print(f"{label} MATCH" if not problems else f"{label} DIFFER ({len(problems)})")
    return 1 if problems else 0


def real() -> int:  # pragma: no cover - needs the hosted database and the old repository
    """The real snapshot imported by the production importer into a throw-away schema, through ``GET /api/today``,
    against the OLD view over a byte-exact copy at the same pinned clock (before the prepared cases expire), served and
    ``uncut``. Declared (c) and (f) only, normalised as for the goldens; every table is checked unchanged by the reads.
    Aggregates only are printed."""
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
    from projectzero.ops.parity_validation import _fingerprint

    load_dotenv()
    settings = Settings.from_env()
    snapshot_ = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    files = {f.path: f.raw for f in snapshot_.files()}
    old = oracle_over({"real": (files, REAL_CLOCK)})["worlds"][0]
    docs: dict[str, Any] = {}
    for path in ("queue_routing.json", "case_prep/cases.json"):  # what the snapshot note is read from (f)
        if path in files:
            try:
                docs[path] = json.loads(files[path].decode("utf-8-sig"))
            except ValueError:
                docs[path] = None
    schema = f"pz_rehearse_{_secrets.token_hex(4)}"
    problems = [f"/old/{k}: the OLD read wrote {old[k]}" for k in ("changed", "blocked") if old.get(k)]
    report_: dict[str, Any] = {}
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
        got: dict[str, Any] = {}
        module = vars(today_core)
        shown = module["MAX_ACTIONS"]
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            for label, cut in (("served", shown), ("uncut", UNCUT)):
                module["MAX_ACTIONS"] = cut
                try:
                    r = client.get("/api/today")
                finally:
                    module["MAX_ACTIONS"] = shown
                got[label] = {"ok": js(r.json())} if r.status_code == 200 else {"raises": r.status_code}
        with transaction(settings.db_url) as c:
            after = _fingerprint(c, schema)
        served_old = {k: old[k] for k in ("ok", "raises") if k in old}
        for label, expected in (("served", served_old), ("uncut", old["uncut"])):
            found: list[str] = []
            o = normalise_old(expected, found)
            n = normalise_new(got[label], docs, found)
            problems += [f"/{label}{p}" for p in found]
            problems += [f"/{label}{p}" for p in diff(js(o), js(n))]
            if _text(o) != _text(n):
                problems.append(f"/{label}: the serialized answer differs (key order)")
        changed = sorted(t for t in before if before[t] != after.get(t))
        if changed:
            problems.append(f"/stored: the Today read changed {changed}")
        body = got["uncut"].get("ok") or {}
        served = got["served"].get("ok") or {}
        report_ = {"clock": REAL_CLOCK, "old": {k: old.get(k) for k in ("saves", "skipped")},
                   "served": [a["type"] for a in served.get("actions") or []], "more": served.get("more"),
                   "uncut": [a["type"] for a in body.get("actions") or []], "considered": body.get("considered"),
                   "exceptions": len(body.get("exceptions") or []), "machine_working": bool(body.get("machine_working")),
                   "triage_total": (body.get("triage") or {}).get("total"), "tables_checked": len(before)}  # fmt: skip
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    report_["differences"] = len(problems)
    print(json.dumps(report_, indent=2, default=str, ensure_ascii=False))
    for line in problems[:60]:
        print("  DIFF", line)
    print("TODAY REAL PARITY PASSED" if not problems else "TODAY REAL PARITY FAILED")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else "check"
    if mode == "goldens":
        return write_goldens()
    if mode == "check":
        return report(read_golden(), "TODAY CHECK")
    if mode == "real":
        return real()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
