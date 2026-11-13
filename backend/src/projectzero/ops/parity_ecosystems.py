"""Ecosystems parity: the port against the OLD code as oracle, with a FIXED clock (review 022).

    python -m projectzero.ops.parity_ecosystems goldens   # (re)generate tests/fixtures/golden_v1/oracle_ecosystems.json

The oracle (``scripts/oracle/ecosystems_oracle.py``) runs the old ``ecosys.city_registry``, ``ecosys.city_page`` for
every curated and detected city (plus an unknown one), ``coverage.report`` and ``connectors.load_registry`` over a
scratch data folder, then an adopt script (``coverage.adopt_candidate``) with the coverage view and the source
registry after each step. The new side is the PURE port (``ecosystems.cities`` / ``coverage`` / ``adopt``) over the
same documents; each adopt decision is applied in memory (``adopt.with_adoption``, as the stored state reads after
the route's transaction) before the next step.

The synthetic data folder holds INVENTED names only. ``main`` exercises every coverage state (HEALTHY by records and
by a productive city source, PARTIAL fresh / stale / failing, UNKNOWN, GAP), every family and country rule, the
city matching (aliases, country tokens, detected cities), the ORGS merge (``ecosystems.json``), custom ecosystems
(``coverage_registry.json``), a standalone source override (``coverage_sources.json``), an archived adoption
(``coverage_adopted.json``) whose source id differs from its derived id and whose current URL is empty, the
event-source "never productive" quirk, the radar-sources migration and the unknown-``earliness`` raise; its adopt
script follows plan revision 3 (no confirm, unknown, limited, no URL, a first adoption, a repeat, an existing
``cov-`` source, the historical retry with and without confirm, two more adoptions). ``variant`` covers the
documents' defaults and malformed bodies; ``broken_regions`` records that the old coverage raised. Identical views in
consecutive steps are stored once (``{"same_as": index}``). Exit 1 on any difference.

Review 036a: the adopt ROUTE refuses a ``confirm`` that is not a JSON boolean (a 400, before any connection); the
pure ``adopt_plan`` compared here takes the route's boolean, so the script's ``1`` / ``"yes"`` / ``""`` steps still
record the old truthiness of the decision itself (the hosted ``test_strict_confirm_hosted`` covers the route).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT
from projectzero.dealflow.sources.normalize import load_registry
from projectzero.ecosystems import adopt, cities, coverage
from projectzero.ecosystems.inputs import CoverageInputs
from projectzero.events import engine
from projectzero.events.when import BERLIN
from projectzero.network.view import berlin_today
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js

ORACLE = REPO_ROOT / "scripts" / "oracle" / "ecosystems_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_ecosystems.json"
CLOCK = "2026-11-11T12:00:00"
UNKNOWN_CITY = "Nowhere-on-Sea"


def utc_instant(berlin_wall_clock: str) -> datetime:
    return datetime.fromisoformat(berlin_wall_clock).replace(tzinfo=BERLIN).astimezone(UTC)


# ------------------------------------------------------------------ the synthetic data folder (invented names only)
# fmt: off
def src(sid: str, name: str, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"id": sid, "name": name, "url": f"https://{sid}.example.org/list", "kind": "watcher",
                            "parser": "page_diff", "geo": ["DE"], "sectors": ["ai_sw"], "stage": "pre_company",
                            "reliability": "medium", "freshness": "weekly", "enabled": True, "last_scan": None,
                            "last_ok": None, "last_result_count": None, "failures_in_row": 0,
                            "yield": {"kept": 0, "research": 0, "rejected": 0}, "country": "Germany",
                            "geo_scope": "country"}
    return base | kw


FRESH = "2026-11-10 08:00"


def deal_flow_sources() -> list[dict[str, Any]]:
    return [
        src("x-talent-berlin", "Invented Talent Exits", last_scan=FRESH, last_ok=FRESH, last_result_count=4),
        src("x-seed-wire", "Invented Seed Funding Wire", kind="rss", stage="announcement", geo=["DACH"],
            last_scan=FRESH, last_ok="2026-11-09 07:00", last_result_count=0),
        src("x-spinout-eu", "Invented University Transfer Spin-offs", geo=["EU"], country="EU",
            geo_scope="region-eu", last_scan="2026-08-01 10:00", last_ok="2026-08-01 10:00",
            last_result_count=3),
        src("x-grant-ee", "Invented Grant Programme", stage="grant", geo=["EE"], country="Estonia",
            last_scan=FRESH, failures_in_row=2),
        src("x-accel-ch", "Invented Accelerator Cohort", geo=[], country="Switzerland",
            location="Zurich, Switzerland", last_scan="2026-11-05 09:00", last_ok="2026-11-05 09:00",
            last_result_count=2),
        src("x-global-never", "Invented Global Register", geo=["Global"], country=""),
        src("x-off", "Invented Disabled Talent List", enabled=False, last_scan=FRESH, last_ok=FRESH,
            last_result_count=9),
        src("x-standalone", "Invented Standalone List", geo=[], country="", last_scan=FRESH, last_ok=FRESH,
            last_result_count=5),
        src("x-global-grants", "Invented Pan Register", geo=[], country=""),
        src("cov-legacy-historic", "Invented Historic Watcher", stage="mixed", last_scan="2026-11-08 10:00",
            last_ok="2026-11-08 10:00", last_result_count=0, coverage_families=["emerging_companies"]),
        src("cov-invented-existing-feed", "Invented Existing Feed", geo=["AT"], country="Austria"),
        src("x-region-nordics", "Invented Nordic Founder Signals", kind="api", geo=[], country="",
            geo_scope="region-nordics", last_scan="2026-11-01 08:00", last_ok="2026-11-01 08:00",
            last_result_count=3),
        src("x-city-only", "Invented Munich Press Desk", geo=[], country="", geo_scope="", city="Munich",
            last_scan=FRESH, last_ok=FRESH, last_result_count=1),
        src("x-two-letter", "Invented Baltic Batch", geo=["lt"], country="lv", last_scan="2026-11-10 05:00",
            last_ok="2026-11-10 05:00", last_result_count=1),
        src("x-uk", "Invented London Research Desk", geo=["UK"], country="UK", last_scan=FRESH, last_ok=FRESH,
            last_result_count=2),
        src("x-usa", "Invented Faraway List", geo=[], country="USA"),
        src("x-old-date", "Invented Odd Date List", geo=["FR"], country="France", last_scan="yesterday",
            last_ok="not a date", last_result_count=1),
    ]


def inbox() -> list[Any]:
    def c(cid: str, name: str, loc: Any, **kw: Any) -> dict[str, Any]:
        return {"id": cid, "name": name, "location": loc, **kw}

    return [
        c("c1", "Invented Berlin Robotics", "Berlin, Germany", source_id="x-talent-berlin", detected_on="2026-11-01"),
        c("c2", "Invented Isar Labs", "München, Germany", source_id="x-other", source_ids=["x-seed-wire"],
          first_seen="2026-10-20"),
        c("c3", "Invented Baltic Grid", "", country="Estonia", source_id="x-grant-ee", detected_on="2026-11-02"),
        c("c4", "Invented Glim One", "Glimmerton, UK", detected_on="2026-11-03"),
        c("c5", "Invented Glim Two", "Glimmerton (UK)", detected_on="2026-11-03"),
        c("c6", "Invented Glim Three", "Glimmerton / GB", detected_on="2026-11-03"),
        c("c7", "Invented Fern One", "Fernwick", detected_on="2026-11-03"),
        c("c8", "Invented Fern Two", "Fernwick, IE", country="IE", detected_on="2026-11-03"),
        c("c9", "Invented Remote Co", "Remote"),
        c("c10", "Invented Country Co", "Estonia"),
        c("c11", "Invented Short Co", "Ab"),
        {"name": "Invented No Id", "location": "Berlin"},
        c("c12", "Invented Old London", "London, UK", source_id="x-uk", detected_on="2026-06-01"),
        c("c13", "Invented New London", "London", source_id="x-uk", detected_on="2026-11-02"),
        c("c14", "Invented Harbour Co", "Nordhafen", source_id="x-standalone", detected_on="2026-11-05"),
        c("c15", "Invented Lake Co", "Quellbrunn am See", source_id="x-other", detected_on="2026-11-05"),
        c("c16", "Invented Undated Munich", "Munich", source_id="x-city-only", detected_on="unknown"),
        c("c17", "Invented Lowercase", "tallinn", country="ee", source_id="x-two-letter", detected_on="2026-11-07"),
        c("c18", "Invented Paris Co", "Paris, France", source_id="x-old-date", detected_on="2026-11-07"),
        "not a record",
    ]


def signals() -> list[dict[str, Any]]:
    def s(company: Any, loc: Any, **kw: Any) -> dict[str, Any]:
        base = {"company": company, "location": loc, "scores": {"founder": 14, "venture_scale": 14, "why_now": 11,
                "taste": 10, "insight": 5}, "earliness": "pre_seed", "status": "new"}
        return base | kw

    return [
        s("Invented Robotics GmbH", "Karlsruhe", discovery_date="2026-11-01", source_id="x-talent-berlin",
          one_liner="Invented arms", sent_to_omar="2026-11-02"),
        s("Invented Grid Labs", "Munich, Germany", earliness="seed", discovery_date="2026-10-15",
          verified={"founders": True, "traction": True, "funding": True}, source_id="x-seed-wire"),
        s("Invented Dropped AG", "Berlin", status="dropped", discovery_date="2026-11-01"),
        s("Invented Lake AI", "Zurich", earliness="unknown", discovery_date="2026-09-01"),
        s("Invented Odd Stage", "Heidelberg", earliness="weird_stage", discovery_date="2026-11-01"),
        s(None, "Fernwick", discovery_date="2026-11-01"),  # no company: coverage counts it, the city pages do not
        s("Invented Created Only", "Darmstadt", created="2026-10-01"),
        s("Invented Nowhere Co", None),
    ]


def people() -> list[dict[str, Any]]:
    return [
        {"id": "p1", "name": "Ada Invented", "location": "Berlin", "last_interaction": "2026-11-01",
         "last_observed": "2026-11-02", "sources": [{"source_id": "x-talent-berlin"}], "next_action": "coffee",
         "next_action_date": "2026-11-10", "relationship_strength": "warm", "role": "CTO",
         "company": "Invented Robotics GmbH"},
        {"id": "p2", "name": "Bo Fictional", "location": "München", "created": "2026-09-01"},
        {"id": "p3", "name": "Cy Madeup", "location": "Glimmerton", "country": "GB", "sources": []},
        {"name": "No Id Person", "location": "Berlin"},
        {"id": "p5", "name": "Di Imaginary", "location": "Karlsruhe, DE", "relationship_strength": "strong",
         "created": "2026-10-10"},
        {"id": "p6", "name": "Ed Unplaced", "country": "Estonia", "sources": [{"source_id": "x-grant-ee"}]},
    ]


def events() -> list[dict[str, Any]]:
    def ev(eid: str, name: str, start: Any, city: str, **kw: Any) -> dict[str, Any]:
        return {"id": eid, "name": name, "start": start, "city": city, "url": f"https://{eid}.example.org",
                "organizer": "Invented Founders Club", "type": "founder_meetup", **kw}

    out = [
        ev("ev-hack", "Invented Robotics Hackathon", "2026-11-20", "Karlsruhe", type="hackathon",
           sources=[{"source_id": "ev-cyberforum"}], source="Invented feed",
           description="A hackathon weekend for founders building robotics startups."),
        ev("ev-demo", "Invented Demo Day", "2026-12-01T18:00", "Munich", type="demo_day",
           sources=[{"source": "ev-luma-munich"}]),
        ev("ev-glim", "Invented Glimmerton Meetup", "2026-11-25", "Glimmerton"),
        ev("ev-alias", "Invented Isar Evening", "2026-11-28", "München"),
        ev("ev-nostart", "Invented Undated Night", None, "Berlin"),
        ev("ev-today", "Invented Today Breakfast", "2026-11-11T08:00", "Karlsruhe"),
    ]
    for i in range(7):  # more past events than the city page shows (6)
        out.append(ev(f"ev-past-{i}", f"Invented Past Night {i}", f"2026-10-0{i + 1}", "Karlsruhe"))
    return out


def candidates_doc() -> dict[str, Any]:
    def cand(name: str, url: str, country: str, city: str, family: str, **kw: Any) -> dict[str, Any]:
        return {"source_name": name, "url": url, "country": country, "city": city, "signal_family": family,
                "source_type": "official_db", "expected_stage_visibility": "mixed",
                "why_it_matters": "Invented reason.", "access_mode": "html", "expected_reliability": "high",
                "likely_freshness": "weekly", "access_limitations": ""} | kw

    return {
        "registry_id": "INVENTED-REGISTRY", "version": "0.9", "generated_at": "2026-11-01",
        "sources": [
            cand("Invented Historic Watcher", "", "Germany", "Nordhafen", "first_funding"),
            cand("Invented Paywalled Register", "https://paywall.example.org", "EE", "national", "grants",
                 access_limitations="Login required for the full list; paywall on exports"),
            cand("Invented Structured API", "https://api.example.org/list", "Lithuania", "Vilnius",
                 "research_spinout", access_mode="structured", access_limitations="API key credential needed",
                 expected_stage_visibility="pre-seed"),
            cand("Invented Offline List", "ftp://offline.example.org", "Latvia", "Riga", "events"),
            cand("Invented Existing Feed", "https://feed.example.org", "Austria", "none", "general"),
            cand("Invented Accelerator Batch", "https://accel.example.org/batch", "Austria", "Quellbrunn",
                 "accelerator", source_type="accelerator", expected_stage_visibility="stealth_exit",
                 likely_freshness="biweekly", expected_reliability=""),
            cand("Invented Accelerator Batch", "https://other.example.org", "Austria", "", "programs"),  # same id
            cand("Invented Grant Pool", "https://grants.example.org", "Atlantis", "", "grants",
                 expected_stage_visibility="", likely_freshness="quarterly"),
            cand("Invented Talent Board", "https://talent.example.org", "de", "Nordhafen", "founder_formation"),
            cand("Invented Unknown Family", "https://odd.example.org", "Norway", "Oslo", "something_else"),
        ],
    }


def corpus() -> dict[str, Any]:
    all7 = ["founder_formation", "emerging_companies", "spinouts", "grants", "programs", "events", "general"]
    return {
        "sources.json": {"sources": deal_flow_sources()},
        "inbox.json": {"candidates": inbox(), "last_run": "2026-11-10T08:00:00"},
        "real_data.json": {"signals": signals()},
        "people.json": {"people": people()},
        "events.json": {"events": events(), "leads": []},
        "event_sources.json": {"sources": [{"id": "ev-cyberforum", "city": "Karlsruhe"}]},
        "event_health.json": {"scan_time": FRESH, "totals": {}, "sources": [
            {"id": "ev-cyberforum", "status": "ok", "last_ok": "2026-11-10 06:00", "raw": 4},
            {"id": "ev-devpost", "status": "failed", "last_ok": ""},
            {"id": "ev-luma-munich", "status": "ok", "last_ok": "2026-11-10 06:00", "events": 3},
            {"id": "ev-utum", "status": "error", "last_ok": "2026-08-01 06:00", "attempted_at": "2026-11-10 06:00"},
            {"id": "ev-luma-berlin", "status": "ok", "last_ok": "2026-11-10 06:00", "raw": 2},
        ]},
        "radar_sources.json": {"sources": [
            {"id": "gh-legacy", "kind": "github_users", "name": "Invented legacy GitHub city search"},
            {"id": "oa-invented", "name": "OpenAlex — invented works, EE", "kind": "openalex_works", "country": "EE"},
        ]},
        "radar_health.json": {"sources": [
            {"id": "gh-munich", "attempted_at": "2026-11-10 05:00", "last_ok": "2026-11-10 05:00", "raw": 5,
             "status": "ok"},
            {"id": "gh-berlin", "attempted_at": "2026-11-10 05:00", "status": "failed"},
            {"id": "oa-invented", "attempted_at": "2026-09-01 05:00", "last_ok": "2026-09-01 05:00", "raw": 0,
             "status": "ok"},
        ]},
        "ecosystems.json": {
            "cities": [{"name": "Nordhafen", "country": "DE", "note": "Invented harbour city.", "travel_hours": 2.5},
                       {"name": "Munich", "country": "DE"}, {"country": "DE"}],
            "institutions": [
                {"name": "Nordhafen Institute of Invented Technology", "kind": "university", "city": "Nordhafen",
                 "lat": 54.1, "lng": 9.9, "why": "Invented campus", "url": "https://niit.example.org"},
                {"name": "Invented Munich Hub", "kind": "hub", "city": "Munich"},
                {"name": "Invented No Kind", "city": "Munich"},
            ],
        },
        "coverage_registry.json": {"ecosystems": [
            {"city": "Quellbrunn", "country": "at", "region": "Invented Alps", "aliases": ["Quellbrunn am See"]},
            {"city": "Nordhafen", "country": "", "region": "Invented North", "aliases": ["Nordhaven"]},
            {"city": "Tallinn", "country": "EE", "aliases": ["Reval"]},
            {"city": "", "country": "DE"},
        ]},
        "coverage_sources.json": {"sources": {
            "x-standalone": {"families": all7, "countries": [], "cities": ["Nordhafen"], "note": "Invented audit."},
            "x-global-grants": {"families": ["grants"], "countries": "global"},
            "cov-legacy-historic": {"families": ["emerging_companies"], "countries": ["DE"], "cities": ["Nordhafen"],
                                    "note": "adopted from coverage audit"},
            "x-not-configured": {"families": ["events"], "countries": ["FR"]},
        }},
        "coverage_adopted.json": {"adopted": {
            "cand-invented-historic-watcher": {"source_id": "cov-legacy-historic", "on": "2026-10-01 09:30",
                                               "by": "operator"},
            "cand-gone-from-the-catalog": {"source_id": "cov-gone", "on": "2026-09-01 10:00", "by": "operator"},
            "cand-invented-grant-pool": {},  # a falsy record: the old code treated the candidate as not adopted
        }},
        "coverage_candidates.json": candidates_doc(),
    }


def variant() -> dict[str, Any]:
    """The documents' defaults and malformed bodies (no candidates file, no adoptions, no event health)."""
    return {
        "sources.json": {"sources": []},
        "people.json": {"people": [{"id": "v1", "name": "Vi Invented", "location": "Glimmerton"}]},
        "radar_regions.json": {"regions": [{"region": "Invented",
                                            "cities": [["Nordhafen", "DE"], ["Glimmerton", "gb"]]}]},
        "radar_sources.json": {"schema": 2, "sources": []},
        "radar_health.json": [],
        "ecosystems.json": {"cities": "not a list"},
        "coverage_registry.json": {"ecosystems": []},
    }


def broken_regions() -> dict[str, Any]:
    return {"sources.json": {"sources": []},
            "radar_regions.json": {"regions": [{"region": "X", "cities": [["Nordhafen", "DE", "extra"]]}]}}


STEPS: list[dict[str, Any]] = [
    {"id": "cand-invented-structured-api"},  # no confirm
    {"id": "cand-no-such-candidate", "confirm": True},  # unknown
    {"id": "cand-invented-paywalled-register", "confirm": True},  # access limitation
    {"id": "cand-invented-offline-list", "confirm": True},  # no http URL
    {"id": "cand-invented-structured-api", "confirm": True},  # a first adoption (structured access is allowed)
    {"id": "cand-invented-structured-api", "confirm": True},  # the repeat: already, its recorded id
    {"id": "cand-invented-existing-feed", "confirm": True},  # its cov- source exists: already, nothing written
    {"id": "cand-invented-historic-watcher", "confirm": True},  # archived adoption, empty URL: the archived id
    {"id": "cand-invented-historic-watcher"},  # the same without confirm: the confirmation refusal
    {"id": "cand-invented-accelerator-batch", "confirm": 1},  # a different candidate
    {"id": "cand-invented-grant-pool", "confirm": "yes"},  # a falsy archived record: adopted now
    {"id": "cand-invented-talent-board", "confirm": ""},  # an empty confirm
]
SETS: dict[str, Any] = {
    "main": {"docs": corpus, "steps": STEPS, "extra_cities": [UNKNOWN_CITY, ""]},
    "variant": {"docs": variant, "steps": [], "extra_cities": [UNKNOWN_CITY]},
    "broken_regions": {"docs": broken_regions, "steps": [], "extra_cities": []},
}
# fmt: on


# ------------------------------------------------------------------ the oracle
def _files(docs: dict[str, Any]) -> dict[str, bytes]:
    return {k: json.dumps(v, ensure_ascii=False, indent=2).encode("utf-8") for k, v in docs.items()}


def run_oracle(inp: dict[str, Any], files: dict[str, bytes]) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-ecosystems-oracle-") as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        for rel, raw in files.items():
            target = (data / rel).resolve()
            if data.resolve() not in target.parents:
                raise SystemExit(f"refusing a path outside the scratch folder: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        srcf, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
        srcf.write_text(json.dumps(inp), encoding="utf-8")
        env = {**os.environ, "PZ_DATA": str(data), "PZ_TESTING": "1", "PYTHONPATH": str(OLD_REPO / "backend" / "src")}
        env.pop("SUPABASE_DB_URL", None)
        run = subprocess.run([str(python), str(ORACLE), str(srcf), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_text(encoding="utf-8"))
        return out


# ------------------------------------------------------------------ the new side
def _try(fn: Any) -> Any:
    try:
        return {"ok": js(fn())}
    except Exception as exc:
        return {"raises": type(exc).__name__}


def inputs_of(docs: dict[str, Any]) -> CoverageInputs:
    """``CoverageInputs`` from the old files, as the importer + the stores would give them."""
    return CoverageInputs(
        sources=load_registry(docs["sources.json"])["sources"],
        event_health=docs.get("event_health.json"),
        radar_regions=docs.get("radar_regions.json"),
        radar_sources=docs.get("radar_sources.json"),
        radar_health=docs.get("radar_health.json"),
        inbox=(docs.get("inbox.json") or {"candidates": []}).get("candidates"),
        signals=(docs.get("real_data.json") or {"signals": []}).get("signals", []),
        people=(docs.get("people.json") or {"people": []}).get("people"),
        events=(docs.get("events.json") or {"events": []}).get("events", []),
        coverage_sources=docs.get("coverage_sources.json"),
        coverage_adopted=docs.get("coverage_adopted.json"),
        coverage_registry=docs.get("coverage_registry.json"),
        coverage_candidates=docs.get("coverage_candidates.json"),
        ecosystems_doc=docs.get("ecosystems.json"),
    )


def _views(inputs: CoverageInputs, now: datetime) -> dict[str, Any]:
    return {"coverage": _try(lambda: coverage.coverage_view(inputs, now)),
            "sources": _try(lambda: load_registry({"sources": inputs.sources}))}  # fmt: skip


def new_side(docs: dict[str, Any], clock: str, steps: list[dict[str, Any]], extra: list[str]) -> dict[str, Any]:
    now = utc_instant(clock)
    today = berlin_today(now)
    ev_doc = docs.get("events.json") or {"events": [], "leads": []}
    src_doc = docs.get("event_sources.json") or {}
    src_city = {s.get("id"): s.get("city", "") for s in src_doc.get("sources") or [] if isinstance(s, dict)}
    sigs = (docs.get("real_data.json") or {}).get("signals")
    ppl = (docs.get("people.json") or {"people": []}).get("people")
    eco_doc = docs.get("ecosystems.json")

    def listing() -> list[dict[str, Any]]:
        return engine.listing(ev_doc["events"], today, src_city)

    registry = _try(lambda: cities.city_registry(sigs, listing(), ppl, eco_doc, today))
    names = [c["name"] for c in (registry.get("ok") or {}).get("cities", [])] + list(extra)
    out: dict[str, Any] = {
        "registry": registry,
        "eco": {n: _try(lambda n=n: cities.eco_view(n, sigs, listing(), ppl, eco_doc, today)) for n in names},
    }
    inputs = inputs_of(docs)
    out.update(_views(inputs, now))
    out["steps"] = []
    for body in steps:
        try:
            decision = adopt.adopt_plan(inputs, body.get("id"), bool(body.get("confirm")))
            answer: Any = {"ok": js(decision.response)}
            inputs = adopt.with_adoption(inputs, decision, now)
        except Exception as exc:
            answer = {"raises": type(exc).__name__}
        out["steps"].append({"body": answer, **_views(inputs, now)})
    return out


# ------------------------------------------------------------------ the golden (identical step views stored once)
def compact(oracle: dict[str, Any]) -> dict[str, Any]:
    prev = [{"coverage": oracle["coverage"], "sources": oracle["sources"]}]
    steps = []
    for st in oracle["steps"]:
        row = {"body": st["body"]}
        for key in ("coverage", "sources"):
            same = next((i for i, p in enumerate(prev) if p[key] == st[key]), None)
            row[key] = {"same_as": same} if same is not None else st[key]
        prev.append({"coverage": st["coverage"], "sources": st["sources"]})
        steps.append(row)
    return {**oracle, "steps": steps}


def expand(expected: dict[str, Any]) -> dict[str, Any]:
    prev = [{"coverage": expected["coverage"], "sources": expected["sources"]}]
    steps = []
    for st in expected["steps"]:
        row = {"body": st["body"]}
        for key in ("coverage", "sources"):
            v = st[key]
            row[key] = prev[v["same_as"]][key] if isinstance(v, dict) and set(v) == {"same_as"} else v
        prev.append({"coverage": row["coverage"], "sources": row["sources"]})
        steps.append(row)
    return {**expected, "steps": steps}


def compare_goldens(golden: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for name, s in golden["sets"].items():
        expected = expand(s["expected"])
        got = new_side(s["docs"], golden["clock"], s["steps"], s["extra_cities"])
        problems += [f"/{name}{p}" for p in diff(js(expected), js(got))]
    return problems


def write_goldens() -> int:
    sets: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    for name, spec in SETS.items():
        docs = spec["docs"]()
        oracle = run_oracle({"clock": CLOCK, "extra_cities": spec["extra_cities"], "steps": spec["steps"]},
                            _files(docs))  # fmt: skip
        meta = oracle.pop("meta")
        sets[name] = {"docs": docs, "steps": spec["steps"], "extra_cities": spec["extra_cities"],
                      "expected": compact(oracle)}  # fmt: skip
    golden = {"provenance": meta, "clock": CLOCK, "sets": sets}
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=None, sort_keys=True) + "\n", encoding="utf-8",
                      newline="\n")  # fmt: skip
    problems = compare_goldens(json.loads(GOLDEN.read_text(encoding="utf-8")))
    print(json.dumps({"golden": str(GOLDEN), "bytes": GOLDEN.stat().st_size, "old": meta,
                      "summary": summary(golden)}, indent=1, ensure_ascii=False))  # fmt: skip
    for p in problems[:60]:
        print("  DIFF", p)
    print("ECOSYSTEMS GOLDENS MATCH" if not problems else f"ECOSYSTEMS GOLDENS DIFFER ({len(problems)})")
    return 1 if problems else 0


def summary(golden: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, s in golden["sets"].items():
        exp = expand(s["expected"])
        cov = exp["coverage"].get("ok") or {}
        states: dict[str, int] = {}
        for e in cov.get("ecosystems", []):
            for f in e["families"].values():
                states[f["state"]] = states.get(f["state"], 0) + 1
        out[name] = {
            "cities": len((exp["registry"].get("ok") or {}).get("cities", [])),
            "eco_raises": sorted(c for c, v in exp["eco"].items() if "raises" in v),
            "coverage": exp["coverage"].get("raises") or {
                "ecosystems": len(cov.get("ecosystems", [])), "counts": cov.get("counts"),
                "family_states": states, "sources_declared": cov.get("sources_declared"),
                "with_override": cov.get("sources_with_override"),
                "new_ecosystems": len(cov.get("new_ecosystems", [])),
                "candidates": {k: cov.get("candidates", {}).get(k) for k in ("total", "adopted")}},
            "steps": [st["body"].get("ok", st["body"]) for st in exp["steps"]],
        }  # fmt: skip
    return out


REAL_CLOCK = "2026-11-12T09:00:00"


def real() -> int:  # pragma: no cover - needs the hosted database and the old repository
    """The real snapshot imported by the production importer into a throw-away schema, against the OLD code over a
    byte-exact copy: the registry, every city's view (and an unknown one), coverage, then an adopt script on a real
    eligible candidate (adopt, repeat) with coverage and the stored registry after each step. Aggregates only."""
    import secrets as _secrets

    from fastapi.testclient import TestClient
    from psycopg import sql as _sql

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.dealflow.sources.store import SourcesStore
    from projectzero.ecosystems.store import EcosystemsStore
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot

    load_dotenv()
    settings = Settings.from_env()
    snapshot = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    files = {f.path: f.raw for f in snapshot.files()}
    now = utc_instant(REAL_CLOCK)
    schema = f"pz_rehearse_{_secrets.token_hex(4)}"
    report: dict[str, Any] = {}
    problems: list[str] = []
    admin = connect(settings.db_url, autocommit=True)
    try:
        admin.execute(_scratch_sql(schema).encode())
        conn = connect(settings.db_url)
        try:
            applied = apply_plan(build_plan(snapshot), schema=schema, conn=conn)
            assert applied.get("applied"), applied
        finally:
            conn.close()
        with transaction(settings.db_url) as c:
            inputs = EcosystemsStore(c, schema).inputs(now)
        adopted = coverage.candidate_sources(inputs)
        pick = next((x for x in adopted if not x.get("adopted") and str(x.get("url") or "").startswith("http")
                     and not adopt.adopt_plan(inputs, x["id"], True).response.get("already")
                     and adopt.adopt_plan(inputs, x["id"], True).writes), None)  # fmt: skip
        steps = [{"id": pick["id"], "confirm": True}, {"id": pick["id"], "confirm": True}] if pick else []
        old = run_oracle({"clock": REAL_CLOCK, "steps": steps, "extra_cities": [UNKNOWN_CITY]}, files)
        report["oracle"] = old["meta"]
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: now
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            got = client.get("/api/ecosystems/registry").json()
            problems += [f"/registry{p.split(':')[0]}" for p in diff(js(old["registry"].get("ok")), got)]
            for name, exp in old["eco"].items():
                r = client.get("/api/ecosystems/eco", params={"city": name})
                if "raises" in exp:
                    if r.status_code == 200:
                        problems.append(f"/eco/{name}: old raised {exp['raises']}, new answered")
                else:
                    problems += [f"/eco/{name}{p.split(':')[0]}" for p in diff(js(exp["ok"]), r.json())]
            report["cities"] = len(old["eco"])
            cov = client.get("/api/ecosystems/coverage").json()
            problems += [f"/coverage{p.split(':')[0]}" for p in diff(js(old["coverage"].get("ok")), cov)]
            report["ecosystems"] = len(cov.get("ecosystems", []))
            for i, (step, exp) in enumerate(zip(steps, old["steps"], strict=True)):
                r = client.post("/api/ecosystems/coverage/adopt", json=step).json()
                problems += [f"/step{i}/body{p.split(':')[0]}" for p in diff(js(exp["body"].get("ok")), r)]
                cov = client.get("/api/ecosystems/coverage").json()
                problems += [f"/step{i}/coverage{p.split(':')[0]}" for p in diff(js(exp["coverage"].get("ok")), cov)]
                with transaction(settings.db_url) as c:
                    reg = load_registry({"sources": SourcesStore(c, schema).stored()})
                problems += [f"/step{i}/sources{p.split(':')[0]}" for p in diff(js(exp["sources"].get("ok")), js(reg))]
            report["adopt_steps"] = len(steps)
            report["adopted_candidate"] = bool(pick)
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    report["differences"] = len(problems)
    print(json.dumps(report, indent=2, default=str))
    for p in problems[:60]:
        print("  DIFF", p)
    print("ECOSYSTEMS PARITY PASSED" if not problems else "ECOSYSTEMS PARITY FAILED")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["goldens"]:
        return write_goldens()
    if argv[1:] == ["real"]:
        return real()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
