# ruff: noqa: E501
# (the synthetic corpus: one record per line)
"""Map parity: the pure port against the OLD code as oracle, with a FIXED clock (review 025).

    python -m projectzero.ops.parity_map goldens   # (re)generates golden_v1/oracle_map.json
    python -m projectzero.ops.parity_map check     # the stored golden against the new code (no oracle)
    python -m projectzero.ops.parity_map real      # the real snapshot, imported, through the API routes

The oracle (``scripts/oracle/map_oracle.py``) runs the old route functions of ``api/routers/home.py`` over a scratch
data folder: ``geo_intel``, ``geo_ecosystem`` for every ecosystem of that answer plus unknown / folded names,
``geo_search`` over a fixed query list, ``sourcing_day`` (a plan per ecosystem at a fixed date, every refusal, extra
days) and, last because it writes, ``map`` (plus the old ``new_signals`` count). The new side is the PURE port
(``map.inputs_model.inputs_from_docs`` -> ``map.intel`` / ``map.pins``) over the same documents, with the old route
error mapping (``KeyError`` -> 404 for the ecosystem, ``KeyError`` / ``ValueError`` -> 400 for the plan, message
``str(e).strip("'")``); ``built_at`` is the clock and ``build_s`` 0.0 on both sides (the oracle freezes ``time``).
Every answer is compared value by value AND as serialized text (key order), and the inputs are checked unchanged.

The synthetic data folders hold INVENTED names only (``inject``: the declared sources and the coverage summary are
given, as the old ``tests/test_geo_intel.py`` monkeypatched them; the other sets derive them from the documents):

* ``munich`` (inject): acceptance 28 / 31 and the integrations: Munich reached through Garching / München, an early
  scout find with founders, a HIGH-SIGNAL event (the plan's 18:00 stop), people, a WATCH trigger and a watch
  candidate, Conviction records (one placeable WITHOUT coordinates: geocoded in memory; one whose location names two
  gazetteer cities: the gazetteer ORDER picks the pin, the earliest mention picks the ecosystem), news events whose
  KEY order is not sorted (``detail.news`` order, a ``Counter`` tie on themes), a source network whose order decides
  ``source_candidates[:6]``, an institution from ``ecosystems.json``, a search whose ``results[0]`` is decided by the
  collection order.
* ``blind`` (inject): acceptance 29 (Tallinn UNDER-COVERED vs Hamburg LOW SIGNAL) and unknown geography never guessed
  ("Europe", "Cambridge, MA, USA", "UK"), a home base that is not Karlsruhe (travel by km).
* ``noisy`` (inject): acceptance 30: 50 funded Berlin rows (machine REJECT) do not outrank early Karlsruhe rows; the
  per-source cap (``+N more from the same lists``).
* ``watchers`` (inject): page-watcher lines hidden (UI text, event titles, ``NOT_AN_ENTITY``), a machine REJECT is
  not early, rejected (cancelled) / skipped / past / far events left out.
* ``chain``: no injection: the coverage registry, declared sources and summary come from the documents
  (``coverage_registry.json`` ecosystems with and without coordinates, ``ecosystems.json`` cities / institutions).
* ``broken``: tolerance: unreadable scout / news / people / events stores empty only their layer; odd records.
* ``empty``: no documents but an empty ``sources.json`` (the old code SEEDED the default Deal Flow registry when
  ``sources.json`` was missing, and wrote it; the database's source table always exists).

Acceptance 32 (``convergence`` on hand-made units) is checked directly in ``tests/map``. Identical recorded
answers are stored once (``{"same_as": key}``). Exit 1 on any difference.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT
from projectzero.map import intel, pins
from projectzero.map.inputs_model import MapInputs, inputs_from_docs
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js

ORACLE = REPO_ROOT / "scripts" / "oracle" / "map_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_map.json"
CLOCK = "2026-11-12T10:00:00"
PLAN_DATE = "2026-11-19"  # a Thursday, the day of the Munich pitch night
EXTRA_CITIES = ["Atlantis", "munich", "  ZÜRICH ", "zurich", ""]
QUERIES = ["", "a", "invented", "kinet", "isar", "tum", "garch", "munchen", "münchen", "hub", "pitch", "neuron",
           "tallinn", "ber", "lena", "zz-nothing", "INVENTED ISARBOT", "rhine"]  # fmt: skip
REFUSALS: list[dict[str, Any]] = [
    {"city": "Atlantis", "date": "2026-11-19"},
    {"city": "Atlantis", "date": "tomorrow"},  # the city is checked first
    {"city": "", "date": ""},
    {},
    {"city": None, "date": None},
    {"city": 7, "date": "2026-11-19"},
]
COVERAGE_FAMILIES = ("spinouts", "programs", "events", "grants", "emerging_companies", "founder_formation", "general")
STRONG = {f: "HEALTHY" for f in COVERAGE_FAMILIES}
INJECT = {
    "declared_sources": [{"id": "s-lab", "families": ["spinouts"]}, {"id": "s-prog", "families": ["programs"]},
                         {"id": "s-wire", "families": ["general"]}, {"id": "s-grant", "families": ["grants"]},
                         {"id": "s-events", "families": ["events", "founder_formation"]}],
    "coverage_all": [
        {"city": "Munich", "country": "DE", "families": {**STRONG, "founder_formation": "UNKNOWN"}},
        {"city": "Berlin", "country": "DE", "families": STRONG},
        {"city": "Tallinn", "country": "EE", "families": {f: "GAP" for f in COVERAGE_FAMILIES}},
        {"city": "Hamburg", "country": "DE", "families": STRONG},
        {"city": "München", "country": "DE", "families": {**STRONG, "founder_formation": "UNKNOWN", "general": "PARTIAL"}},  # placed to Munich: the LATER row wins
        {"city": "Cambridge", "country": "GB", "families": {"spinouts": "HEALTHY", "programs": None}},
        {"city": "Nowhere-on-Sea", "country": "", "families": {}},
    ],
}  # fmt: skip


# ------------------------------------------------------------------ the synthetic data folders (invented names only)
# fmt: off
def sources() -> dict[str, Any]:
    return {"sources": [
        {"id": "s-lab", "name": "Invented Lab Transfer", "stage": "pre_company", "url": "https://lab.invented.example"},
        {"id": "s-prog", "name": "Invented Venture Programme", "stage": "pre_company", "url": "https://prog.invented.example"},
        {"id": "s-grant", "name": "Invented Grant Office", "stage": "grant", "url": "https://grant.invented.example"},
        {"id": "s-wire", "name": "Invented City Wire", "stage": "mixed", "url": "https://wire.invented.example"},
        {"id": "s-events", "name": "Invented Event Board", "stage": "pre_company", "url": "https://events.invented.example"},
        "not a source", {"name": "no id"},
    ]}


def cand(cid: str, name: str, loc: Any, src: str, decision: str = "new", seen: str = "2026-11-01", **kw: Any) -> dict[str, Any]:
    return {"id": cid, "name": name, "location": loc, "source_id": src, "source": src, "decision": decision,
            "first_seen": seen, "why": [f"{name} from {src}"], **kw}


def event(eid: str, name: str, city: str, start: str, **kw: Any) -> dict[str, Any]:
    return {"id": eid, "name": name, "city": city, "start": start, "url": f"https://{eid}.invented.example",
            "type": "founder_meetup", "description": "Startup founders pitch to investors", **kw}


def signal(company: str, location: Any, **kw: Any) -> dict[str, Any]:
    return {"company": company, "status": "new", "location": location, "one_liner": f"{company} builds things",
            "founders": [{"name": "Ida Inventa"}, "Ole Fictiv"], "scores": {"founder": 18, "venture_scale": 12, "why_now": 9},
            "verified": {"founders": True}, "earliness": "pre_seed", "funding_status": "Pre-seed",
            "discovery_date": "2026-10-20", "discovery_source": "Invented Scout Lane", "why_found": "Strong team", **kw}


def person(pid: str, name: str, loc: Any, **kw: Any) -> dict[str, Any]:
    return {"id": pid, "name": name, "location": loc, "role": "Venture lead", "company": "Invented Hub",
            "founder_potential": "none", "relationship_strength": "met once", "why_interesting": "runs a programme",
            "last_interaction": "2026-10-01", **kw}


def news_event(eid: str, headline: str, etype: str, day: str, themes: list[str], **kw: Any) -> dict[str, Any]:
    return {"event_id": eid, "company": "", "headline": headline, "summary": "", "event_type": etype, "event_date": day,
            "materiality": "MEDIUM", "noise": False, "themes": themes,
            "sources": [{"publisher": "Invented Startup Daily", "url": f"https://news.invented.example/{eid}"}], **kw}


def scout_item(iid: str, name: str, loc: str, **kw: Any) -> dict[str, Any]:
    return {"id": iid, "entity_name": name, "location": loc, "status": "NEW INTAKE", "cycle_id": "009",
            "signal_types": ["spinout", "round_forming"], "stage": "pre-company", "founders": ["Dr. Invented Example"],
            "key_fact": f"{name}: robotics spin-off preparing a pre-seed", "date_discovered_effective": "2026-11-05", **kw}


def net(cid: str, name: str, url: str, state: str, family: Any = "founder_move") -> dict[str, Any]:
    return {"id": cid, "name": name, "url": url, "family": family, "state": state, "discovered_via": [], "history": [],
            "discovered_at": "2026-10-01"}


def munich_docs() -> dict[str, Any]:
    inbox = [
        cand("m1", "Invented Kinetiq Robotics", "Munich, Germany", "s-lab"),
        cand("m2", "Invented Graspwerk", "Garching", "s-lab"),
        cand("m3", "Invented Isarbot", "Munich", "s-prog"),
        cand("m4", "Invented Torqan", "München", "s-grant"),
        cand("m5", "Invented Watchful Optics", "Munich", "s-wire", decision="watch"),
        cand("m6", "Invented Baseline Co", "Munich", "s-lab", decision="baseline"),
        cand("m7", "Invented Noise Co", "Munich", "s-lab", noise=True),
        cand("m8", "Invented Old Signal", "Munich", "s-lab", seen="2026-03-01"),
        {**cand("m9", "Invented Run Only", "Ottobrunn", "s-events", seen=""), "first_seen_run": "2026-10-30 19:00"},
        cand("m10", "Invented Isar Analytics", "Munich", "s-wire", decision="research"),
        cand("s1", "Invented Neckar Lab", "Stuttgart, DE", "s-lab"),
        cand("h1", "Invented Heidelberg Bio", "Heidelberg", "s-lab"),
    ]
    props = {"m1": {"status": "proposed", "proposal": "RESEARCH", "capital_stage": "PRE_COMPANY", "entity_type": "VENTURE"},
             "m3": {"status": "proposed", "proposal": "RESEARCH", "capital_stage": "ROUND_FORMING"},
             "m10": {"status": "proposed", "proposal": "WATCH", "capital_stage": "FIRST_INSTITUTIONAL"},
             "s1": "not a proposal"}
    sigs = [
        signal("Invented Alpine Sensors", "Munich", scout_provenance=[{"scout_cycle_id": "007"}, "bad", {"scout_cycle_id": "009"}, {"scout_cycle_id": "007"}]),
        signal("Invented Neckar Batteries", "Stuttgart", lat=48.78, lng=9.18, verified={"founders": True, "traction": True, "funding": True, "team": True}),
        signal("Invented Dropped Co", "Munich", status="dropped"),
        signal("Invented Rhine Dynamics", "Mannheim near Heidelberg", scout_provenance={"scout_cycle_id": "004"}),
        signal("Invented Legacy Scores", "Karlsruhe", scores={"founder": "high", "venture_scale": ""}),
        signal("Invented Nowhere Co", "Somewhere far"),
        signal("Invented Lat Only", "Munich", lat=48.1),
        signal("Invented Odd Archetype", "Munich", archetype=[1, 2], lat=48.2, lng=11.5),
        {"status": "new", "location": "Munich"},
        "not a record",
    ]
    scout = {"cycles": {"009": {}}, "items": [
        scout_item("si-1", "Invented Neuron Hands", "Munich, Germany"),
        scout_item("si-2", "Invented Late Scale", "Munich", stage="Series B", signal_types=["hiring", "customer pilot", "funding"], founders=[]),
        scout_item("si-3", "Invented Rejected Find", "Munich", status="REJECTED"),
        scout_item("si-4", "Invented Vague Find", "Europe"),
        scout_item("si-5", "Invented Isar Founders", "Garching bei München", signal_types=["stealth"], founders=["Invented Founder A", "Invented Founder B"]),
    ]}
    news = {"events": {
        "nw-z": news_event("nw-z", "Munich robotics startup Invented Kinetiq Robotics wins a grant", "grant", "2026-11-05", ["robotics"], company="Invented Kinetiq Robotics"),
        "nw-a": news_event("nw-a", "Munich accelerator Invented Isar Founders Hub opens a cohort", "accelerator", "2026-11-05", ["ai"]),
        "nw-m": news_event("nw-m", "Invented Graspwerk from Munich raises a Series B", "funding", "2026-11-04", ["robotics"], company="Invented Graspwerk"),
        "nw-b": news_event("nw-b", "München: Invented Kinetiq Robotics hires a CTO", "hire", "2026-11-03", ["ai"], company="invented kinetiq robotics"),
        "nw-n": news_event("nw-n", "Munich noise", "launch", "2026-11-03", ["ai"], noise=True),
        "nw-l": news_event("nw-l", "Munich low", "launch", "2026-11-03", ["ai"], materiality="LOW"),
        "nw-c": news_event("nw-c", "Munich curated", "launch", "2026-11-03", ["ai"], curated=True),
        "nw-o": news_event("nw-o", "Munich old story about Invented Torqan", "partnership", "2026-01-03", ["energy"]),
        "nw-x": news_event("nw-x", "A story with no place", "launch", "2026-11-03", ["ai"]),
        "nw-bad": {"event_id": "nw-bad", "headline": "Munich broken record", "materiality": "HIGH"},
    }, "seeded": []}
    people_doc = {"people": [
        person("p1", "Invented Lena Vogel", "Munich"),
        person("p2", "Invented Max Former", "Munich, Germany", founder_potential="High", relationship_strength="", next_action="Ask about the spin-off", next_action_date="2026-11-01"),
        person("p3", "Invented Kai Garching", "Garching"),
        person("p4", "Invented Karla Ruhe", "Karlsruhe", watch=True),
        person("p5", "Invented No Place", ""),
        {"name": "no id"},
    ]}
    events_doc = {"events": [
        event("ev-pitch", "Invented Isar Pitch Night", "Munich", "2026-11-19T18:00", status="planned", lat=48.1351, lng=11.582),
        event("ev-later", "Invented Robotics Founders Meetup", "Munich", "2026-12-05"),
        event("ev-cancel", "Cancelled: Invented Expo", "Munich", "2026-11-20"),
        event("ev-skip", "Invented Skipped Day", "Munich", "2026-11-18", status="skipped"),
        event("ev-far", "Invented Far Future", "Munich", "2027-03-01"),
        event("ev-past", "Invented Past Night", "Munich", "2026-10-01"),
        event("ev-ka", "Invented Karlsruhe Founders Night", "Karlsruhe", "2026-11-26T19:30", status="planned", lat=49.0, lng=8.4),
        event("ev-noplace", "Invented Online Pitch", "", "2026-11-25", format="virtual"),
    ], "leads": []}
    network = {"candidates": {
        "src-x": net("src-x", "Invented Munich founder meetup list", "https://founders.invented.de/", "PROBATION"),
        "src-r": net("src-r", "Invented rejected", "bad", "REJECTED", family=["x"]),
        "src-a": net("src-a", "Invented university list", "https://hub.invented.org/list", "DISCOVERED", family="university_lab"),
        "src-5": net("src-5", "Invented five", "https://five.invented.de/", "VALIDATING", family=None),
        "src-2": net("src-2", "Invented two", "https://two.invented.org/", "DEGRADED"),
        "src-9": net("src-9", "Invented nine", "https://nine.invented.de/a", "DISCOVERED"),
        "src-1": net("src-1", "Invented one", "https://one.invented.de", "PROBATION"),
        "src-8": net("src-8", "Invented eight", "https://eight.invented.de", "VALIDATING"),
        "src-7": net("src-7", "Invented seven", "https://seven.invented.de", "VALIDATING"),
        "src-ok": net("src-ok", "Invented active", "https://ok.invented.de", "ACTIVE"),
    }}
    eco = {"cities": [{"name": "Tartu", "country": "EE"}],
           "institutions": [{"name": "Invented Isar Founders Hub", "city": "Munich", "kind": "accelerator", "why": "runs cohorts", "url": "https://hub.invented.example"},
                            {"name": "Invented Unplaced Lab", "city": "Atlantis", "kind": "lab"},
                            {"name": "No kind", "city": "Munich"}]}
    triggers = "\n".join(json.dumps(x) for x in [
        {"id": "t1", "name": "Invented Isarbot", "predicate": "new round"},
        {"id": "t2", "name": "Invented Torqan"},
        {"kind": "status", "trigger_id": "t2", "status": "done"},
        {"id": "t3", "key": "invented graspwerk"},
    ]) + "\nnot json\n"
    return {"sources.json": sources(), "inbox.json": {"candidates": inbox}, "triage_proposals.json": {"proposals": props},
            "real_data.json": {"week": "2026-W46", "signals": sigs}, "scout_intake.json": scout, "news/events.json": news,
            "people.json": people_doc, "events.json": events_doc, "sources/network.json": network,
            "ecosystems.json": eco, "watch/triggers.jsonl": triggers}


def blind_docs() -> dict[str, Any]:
    inbox = [cand("u1", "Invented Somewhere Co", "Europe", "s-lab"), cand("u2", "Invented US Co", "Cambridge, MA, USA", "s-lab"),
             cand("u3", "Invented Uk Co", "UK", "s-lab"), cand("u4", "Invented Blank Co", None, "s-lab"),
             cand("u5", "Invented Cambridge Lab", "Cambridge, United Kingdom", "s-lab")]
    sigs = [signal("Invented Faraway Robotics", "Singapore"), signal("Invented Tallinn Bits", "Tallinn, Estonia")]
    scout = {"items": [scout_item("si-u", "Invented Floating Find", "Germany")]}
    return {"sources.json": sources(), "inbox.json": {"candidates": inbox}, "real_data.json": {"signals": sigs},
            "scout_intake.json": scout, "config.json": {"home_base": {"city": "Basel", "lat": 47.5596, "lng": 7.5886}}}


def noisy_docs() -> dict[str, Any]:
    noisy = [cand(f"b{i}", f"Invented Funded Co {i}", "Berlin", "s-wire") for i in range(50)]
    early = [cand("k1", "Invented Lab One", "Karlsruhe", "s-lab"), cand("k2", "Invented Lab Two", "Karlsruhe", "s-lab"),
             cand("k3", "Invented Grant Three", "Karlsruhe", "s-grant"), cand("k4", "Invented Prog Four", "Karlsruhe", "s-prog"),
             cand("k5", "Invented Lab Five", "Karlsruhe", "s-lab"), cand("k6", "Invented Lab Six", "Karlsruhe", "s-lab")]
    props = {f"b{i}": {"status": "proposed", "proposal": "REJECT", "capital_stage": "ALREADY_INSTITUTIONALLY_FUNDED"} for i in range(50)}
    return {"sources.json": sources(), "inbox.json": {"candidates": noisy + early}, "triage_proposals.json": {"proposals": props}}


def watchers_docs() -> dict[str, Any]:
    inbox = [cand("j1", "Invented B|E Masterclass", "Munich", "s-lab"), cand("j2", "Show 15 more", "Munich", "s-lab"),
             cand("j3", "Invented Digital Health Summit 2026", "Munich", "s-lab"), cand("j4", "Invented Ecosystem Evening", "Munich", "s-lab"),
             cand("j5", "Invented Rejected Robotics", "Munich", "s-lab"), cand("j6", "UNKNOWN", "Munich", "s-lab"),
             cand("j7", "Invented Founders Night 2027", "Munich", "s-lab"), cand("ok", "Invented Kinetiq Robotics", "Munich", "s-lab")]
    props = {"j4": {"status": "proposed", "proposal": "RESEARCH", "entity_type": "NOT_AN_ENTITY"},
             "j5": {"status": "proposed", "proposal": "REJECT", "entity_type": "VENTURE", "capital_stage": "PRE_COMPANY"}}
    events_doc = {"events": [
        event("ev-ok", "Invented Pitch Night", "Munich", "2026-11-20T18:00"),
        event("ev-no", "Cancelled: Invented Sunset Hike", "Munich", "2026-11-17"),
        event("ev-skip", "Invented Skipped Day", "Munich", "2026-11-18", status="skipped"),
        event("ev-multi", "Invented Two Day Summit", "Munich", "2026-11-11", end="2026-11-13", status="planned"),
    ]}
    return {"sources.json": sources(), "inbox.json": {"candidates": inbox}, "triage_proposals.json": {"proposals": props},
            "events.json": events_doc}


def chain_docs() -> dict[str, Any]:
    reg = sources()
    reg["sources"] = [s for s in reg["sources"] if isinstance(s, dict) and s.get("id")]
    for s in reg["sources"]:
        s.update({"kind": "watcher", "parser": "page_diff", "geo": ["DE"], "enabled": True, "country": "Germany",
                  "location": "Munich, Germany", "last_scan": "2026-11-10 08:00", "last_ok": "2026-11-10 08:00",
                  "last_result_count": 3, "failures_in_row": 0})
    inbox = [cand("c1", "Invented Tartu Photonics", "Tartu, Estonia", "s-lab"), cand("c2", "Invented Kaunas Grid", "Kaunas", "s-grant"),
             cand("c3", "Invented Rhine Robotics", "Invented-on-Rhine", "s-lab"), cand("c4", "Invented Munich Labs", "Munich", "s-lab"),
             cand("c5", "Invented Zurich Quantum", "Zurich", "s-prog"), cand("c6", "Invented Zürich Bio", "Zürich, CH", "s-prog")]
    return {"sources.json": reg, "inbox.json": {"candidates": inbox},
            "coverage_registry.json": {"ecosystems": [{"city": "Invented-on-Rhine", "country": "DE"},
                                                      {"city": "Tartu", "country": "EE", "aliases": ["Tartu linn"]}]},
            "ecosystems.json": {"cities": [{"name": "Kaunas", "country": "LT"}],
                                "institutions": [{"name": "Invented Tartu Science Park", "city": "Tartu", "kind": "park"}]},
            "people.json": {"people": [person("p-t", "Invented Tiina Tamm", "Tartu linn", founder_potential="medium")]},
            "config.json": {"home_base": {"city": "Karlsruhe", "lat": 49.0069, "lng": 8.4037}},
            "sources/network.json": {"candidates": {"n-ee": net("n-ee", "Invented Estonian list", "https://list.invented.ee/", "DISCOVERED"),
                                                    "n-lt": net("n-lt", "Invented grant list", "https://grants.invented.org/", "PROBATION", family="grant")}}}


def broken_docs() -> dict[str, Any]:
    inbox = [cand("x1", "Invented Text Why", "Munich", "s-lab", why="a string"), cand("x2", "Invented Int Why", "Munich", "s-lab", why=5),
             {"name": "Invented No Id", "location": "Munich"}, "not a record", cand("x3", "Invented Ok Co", "Munich", "s-lab"),
             cand("x4", "Invented Int Location", 42, "s-lab")]
    return {"sources.json": sources(), "inbox.json": {"candidates": inbox}, "scout_intake.json": [1],
            "news/events.json": [1], "people.json": [], "events.json": {"leads": []},
            "real_data.json": {"signals": {"a": signal("Invented Dict Co", "Munich"), "b": "x"}},
            "triage_proposals.json": {"proposals": {"x3": ["not", "a", "dict"]}},
            "sources/network.json": [], "config.json": {"home_base": "Karlsruhe"}}


SETS: dict[str, dict[str, Any]] = {
    "munich": {"docs": munich_docs, "inject": INJECT, "plans": [{"city": "Munich", "date": "2026-11-26"}, {"city": "munich", "date": "2026-11-19"}]},
    "blind": {"docs": blind_docs, "inject": INJECT, "plans": []},
    "noisy": {"docs": noisy_docs, "inject": INJECT, "plans": [{"city": "Karlsruhe", "date": "2026-02-30"}]},
    "watchers": {"docs": watchers_docs, "inject": INJECT, "plans": [{"city": "Munich", "date": "2026-11-21"}]},
    "chain": {"docs": chain_docs, "inject": None, "plans": []},
    "broken": {"docs": broken_docs, "inject": None, "plans": []},
    "empty": {"docs": lambda: {"sources.json": {"sources": []}}, "inject": None, "plans": []},
}
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
    with tempfile.TemporaryDirectory(prefix="pz-map-oracle-") as tmp:
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


# ------------------------------------------------------------------ the new side (the old route mapping)
def _answer(fn: Callable[[], Any], miss: int = 400) -> dict[str, Any]:
    try:
        body = fn()
    except (KeyError, ValueError) as exc:
        return {"code": miss, "body": {"ok": False, "error": str(exc).strip("'")}}
    except Exception as exc:  # the old route would have answered 500
        return {"raises": type(exc).__name__}
    return {"code": 200, "body": js(body)}


def inputs_of(docs: dict[str, Any], inject: dict[str, Any] | None, today: date) -> MapInputs:
    inputs = inputs_from_docs(docs, today)
    if inject:
        inputs = dataclasses.replace(inputs, declared_sources=copy.deepcopy(inject["declared_sources"]),
                                     coverage_all=copy.deepcopy(inject["coverage_all"]))  # fmt: skip
    return inputs


def new_side(spec: dict[str, Any], clock: str) -> tuple[dict[str, Any], list[str]]:
    today = datetime.fromisoformat(clock).date()
    docs_before = copy.deepcopy(spec["docs"])
    inputs = inputs_of(spec["docs"], spec.get("inject"), today)
    inputs_before = copy.deepcopy(inputs)
    intel_a = _answer(lambda: intel.view(inputs, today, built_at=clock))
    cities = [e["city"] for e in (intel_a.get("body") or {}).get("ecosystems", [])]

    def detail(city: str) -> dict[str, Any]:  # the old route: KeyError -> 404
        return _answer(lambda: intel.detail(inputs, city, today), miss=404)

    def search(q: str) -> dict[str, Any]:
        return _answer(lambda: {"results": intel.search(inputs, q, today)})

    def plan(body: dict[str, Any]) -> dict[str, Any]:  # the old route: str(body.get(...) or ""), errors -> 400
        city, day = str(body.get("city") or ""), str(body.get("date") or "")
        return _answer(lambda: intel.sourcing_day(inputs, city, day, today))

    out: dict[str, Any] = {
        "intel": intel_a,
        "ecosystem": {c: detail(c) for c in [*cities, *spec["extra_cities"]]},
        "search": {q: search(q) for q in spec["queries"]},
        "sourcing_day": [],
    }
    bodies = [{"city": c, "date": spec["plan_date"]} for c in cities] + list(spec["plans"])
    for body in bodies:
        out["sourcing_day"].append({"body": body, "answer": plan(body)})
    m = _answer(lambda: pins.map_view(inputs, today))
    out["new_signals"] = (m.get("body") or {}).pop("new_signals", None)
    out["map"] = m
    invariants = []
    if inputs != inputs_before:
        invariants.append("/inputs: the Map changed its inputs")
    if spec["docs"] != docs_before:
        invariants.append("/docs: inputs_from_docs changed the documents")
    return out, invariants


# ------------------------------------------------------------------ the golden (identical answers stored once)
def _key(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=False)


def _cells(o: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    """(label, container, key) for every recorded answer, in a fixed order."""
    cells: list[tuple[str, Any, Any]] = [("intel", o, "intel"), ("map", o, "map")]
    cells += [(f"ecosystem/{c}", o["ecosystem"], c) for c in o["ecosystem"]]
    cells += [(f"search/{q}", o["search"], q) for q in o["search"]]
    cells += [(f"sourcing_day[{i}]", row, "answer") for i, row in enumerate(o["sourcing_day"])]
    return cells


def compact(o: dict[str, Any]) -> dict[str, Any]:
    o = copy.deepcopy(o)
    seen: dict[str, str] = {}
    for label, box, k in _cells(o):
        s = _key(box[k])
        if s in seen:
            box[k] = {"same_as": seen[s]}
        else:
            seen[s] = label
    return o


def expand(o: dict[str, Any]) -> dict[str, Any]:
    o = copy.deepcopy(o)
    by_label: dict[str, Any] = {}
    for label, box, k in _cells(o):
        v = box[k]
        if isinstance(v, dict) and set(v) == {"same_as"}:
            box[k] = copy.deepcopy(by_label[v["same_as"]])
        by_label[label] = box[k]
    return o


def compare_goldens(golden: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for name, s in golden["sets"].items():
        expected = expand(s["expected"])
        expected.pop("map_wrote", None)
        got, invariants = new_side(s, golden["clock"])
        problems += [f"/{name}{p}" for p in diff(js(expected), js(got))]
        problems += [f"/{name}{p}" for p in invariants]
        for label, box, k in _cells(expected):  # key order, explicitly (dict == ignores it)
            other = dict(_cells_by_label(got)).get(label)
            if other is not None and _key(box[k]) != _key(other):
                problems.append(f"/{name}/{label}: the serialized answer differs (key order)")
    return problems


def _cells_by_label(o: dict[str, Any]) -> list[tuple[str, Any]]:
    return [(label, box[k]) for label, box, k in _cells(o)]


def write_goldens() -> int:
    sets: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    for name, spec in SETS.items():
        docs = spec["docs"]()
        inp = {"clock": CLOCK, "inject": spec["inject"], "extra_cities": EXTRA_CITIES, "queries": QUERIES,
               "plan_date": PLAN_DATE, "plans": REFUSALS + spec["plans"]}  # fmt: skip
        oracle = run_oracle(inp, _files(docs))
        meta = oracle.pop("meta")
        sets[name] = {"docs": docs, "inject": spec["inject"], "extra_cities": EXTRA_CITIES, "queries": QUERIES,
                      "plan_date": PLAN_DATE, "plans": REFUSALS + spec["plans"], "expected": compact(oracle)}  # fmt: skip
    golden = {"provenance": meta, "clock": CLOCK, "sets": sets}
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    # NOT sort_keys: the documents' insertion order is part of the input (and of what the oracle recorded)
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=None) + "\n", encoding="utf-8", newline="\n")
    problems = compare_goldens(json.loads(GOLDEN.read_text(encoding="utf-8")))
    print(json.dumps({"golden": str(GOLDEN), "bytes": GOLDEN.stat().st_size, "old": meta,
                      "summary": summary(golden)}, indent=1, ensure_ascii=False))  # fmt: skip
    for p in problems[:60]:
        print("  DIFF", p)
    print("MAP GOLDENS MATCH" if not problems else f"MAP GOLDENS DIFFER ({len(problems)})")
    return 1 if problems else 0


def summary(golden: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, s in golden["sets"].items():
        e = expand(s["expected"])
        body = e["intel"].get("body") or {}
        out[name] = {
            "ecosystems": len(body.get("ecosystems", [])),
            "states": body.get("counts"),
            "where_to_go": [w["city"] for w in (body.get("where_to_go") or {}).get("ranked", [])],
            "details_404": sum(1 for a in e["ecosystem"].values() if a.get("code") == 404),
            "plans": [r["answer"].get("code", r["answer"].get("raises")) for r in e["sourcing_day"]].count(200),
            "refusals": [
                r["answer"].get("body", {}).get("error") for r in e["sourcing_day"] if r["answer"].get("code") == 400
            ],
            "map": {k: len(v) for k, v in (e["map"].get("body") or {}).items() if isinstance(v, list)},
            "map_wrote": e.get("map_wrote"),
            "new_signals": e.get("new_signals"),
        }
    return out


# ------------------------------------------------------------------ the real snapshot, through the API routes
REAL_CLOCK = "2026-11-12T09:00:00"
REAL_PLAN_DATE = "2026-11-19"
REAL_QUERIES = ["", "a", "mun", "berlin", "karl", "tum", "robot", "ai", "lab", "hub", "zz-nothing"]
_SCOUT_LINK = re.compile(r"^/scout-intake\?item=[^\"]*$")


def _old_scout_links(v: Any) -> Any:
    """Decision (d), the one declared difference: a Scout card links to ``/scout-intake?item=<id>`` (the old bare
    ``/scout-intake``); every other value is compared as is."""
    if isinstance(v, dict):
        return {k: ("/scout-intake" if k == "link" and isinstance(x, str) and _SCOUT_LINK.match(x) else _old_scout_links(x))
                for k, x in v.items()}  # fmt: skip
    if isinstance(v, list):
        return [_old_scout_links(x) for x in v]
    return v


def real() -> int:  # pragma: no cover - needs the hosted database and the old repository
    """The real snapshot imported by the production importer into a throw-away schema, through the API routes, against
    the OLD routes over a byte-exact copy at the same clock: the intelligence, every ecosystem (plus unknown / folded
    names), the searches, a plan per ecosystem and every refusal, and the pins (``new_signals`` against the old Home
    count). Declared: (a) the old pins answer geocoded and SAVED, the new one only answers (the stored Conviction
    records are checked unchanged); (d) the Scout links. Aggregates only are printed."""
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
    files = {f.path: f.raw for f in snapshot_.files()}
    inp = {"clock": REAL_CLOCK, "inject": None, "extra_cities": EXTRA_CITIES, "queries": REAL_QUERIES,
           "plan_date": REAL_PLAN_DATE, "plans": REFUSALS}  # fmt: skip
    old = run_oracle(inp, files)
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

        def stored() -> Any:
            with transaction(settings.db_url) as c:
                return c.execute(_sql.SQL("select to_jsonb(e) from {}.conviction_entries e order by id")
                                 .format(_sql.Identifier(schema))).fetchall()  # fmt: skip

        before = stored()
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: utc_instant(REAL_CLOCK)
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:

            def ans(r: Any) -> dict[str, Any]:
                return {"code": r.status_code, "body": _old_scout_links(r.json())}

            got: dict[str, Any] = {"intel": ans(client.get("/api/map/intel"))}
            cities = [e["city"] for e in (old["intel"].get("body") or {}).get("ecosystems", [])]
            got["ecosystem"] = {c: ans(client.get("/api/map/ecosystem", params={"city": c}))
                                for c in [*cities, *EXTRA_CITIES]}  # fmt: skip
            got["search"] = {q: ans(client.get("/api/map/search", params={"q": q})) for q in REAL_QUERIES}
            bodies = [{"city": c, "date": REAL_PLAN_DATE} for c in cities] + list(REFUSALS)
            got["sourcing_day"] = [{"body": b, "answer": ans(client.post("/api/map/sourcing_day", json=b))}
                                   for b in bodies]  # fmt: skip
            m = ans(client.get("/api/map/pins"))
            got["new_signals"] = (m.get("body") or {}).pop("new_signals", None)
            got["map"] = m
        expected = {k: old[k] for k in got}
        for k in got:
            problems += [f"/{k}{p}" for p in diff(js(expected[k]), js(got[k]))]
        if json.dumps(expected["intel"], ensure_ascii=False) != json.dumps(got["intel"], ensure_ascii=False):
            problems.append("/intel: the serialized answer differs (key order)")
        if stored() != before:
            problems.append("/stored: a Map read changed a Conviction record")
        body = got["intel"].get("body") or {}
        report = {"ecosystems": len(body.get("ecosystems", [])), "states": body.get("counts"),
                  "where_to_go": len((body.get("where_to_go") or {}).get("ranked", [])),
                  "details": len(got["ecosystem"]), "plans": len(got["sourcing_day"]),
                  "pins": {k: len(v) for k, v in (got["map"].get("body") or {}).items() if isinstance(v, list)},
                  "new_signals": got["new_signals"], "old_map_wrote": old.get("map_wrote")}  # fmt: skip
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    report["differences"] = len(problems)
    print(json.dumps(report, indent=2, default=str, ensure_ascii=False))
    for p in problems[:60]:
        print("  DIFF", p)
    print("MAP PARITY PASSED" if not problems else "MAP PARITY FAILED")
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
        print("MAP GOLDENS MATCH" if not problems else f"MAP GOLDENS DIFFER ({len(problems)})")
        return 1 if problems else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
