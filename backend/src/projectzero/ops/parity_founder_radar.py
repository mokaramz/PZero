# ruff: noqa: E501
# (the synthetic corpus and the write script: one case per line)
"""Founder Radar parity: the pure port against the OLD code as oracle, with a FIXED clock (review 026a).

    python -m projectzero.ops.parity_founder_radar goldens   # (re)generates golden_v1/oracle_founder_radar.json
    python -m projectzero.ops.parity_founder_radar real      # the real snapshot, imported, through the API routes

The oracle (``scripts/oracle/founder_radar_oracle.py``) runs the old route functions of ``api/routers/founder_radar.py``
over a scratch data folder: the GET, ``radar_proposals``, the old ``region_health`` / ``next_batch``, and a write
script (``radar_action`` with every action and each refusal, ``radar_import`` in both formats, ``radar_company``,
``radar_promote``, ``boardy_brief``, ``radar_pair``, ``radar_review``) with, after each write, the answer, the whole GET
body and the stored people.json, radar_companies.json, radar_research.json and radar_metrics.json (bodies as stored, key
order included). The new side is the PURE port (``founder_radar.routes``): each write's ``Outcome`` documents become the
next step's inputs, a merge adds its tombstone to the reserved ids.

The synthetic data folders hold INVENTED names only. ``main`` rebuilds the old tests' scenarios: a GitHub login-only
record (login normalisation), a resolved founder, a researcher, an original-MVP pipeline record (repair), placeholder
records (one quarantined, one with human work invalidated), an organisation and a navigation heading, a Network person
without radar fields, three same-name people (an employer merge and a conflicting GitHub id), a handle-only record with
a proposed identity, pipeline signals, a research record whose ``proposals`` / ``pages`` / ``pairings`` insertion order
differs from JSONB order (disputed facts, alternatives, template text, machine inferences, founders named / handle-only
/ malformed / rejected, a future-dated activity), companies with stored founder references and leaked ``_dirty`` flags,
health, regions, cursor and a metrics history. ``later``: the same folder read at a second clock. ``defaults``:
missing / malformed regions, health, metrics, companies and research. ``empty``: no files at all.

Planned differences (review 026a), declared and normalised; everything else must be identical:
* (a) reads never write: the oracle restores whatever a GET / ``radar_proposals`` wrote. The stored companies are
  compared with their founder references derived (the old routes persisted references even on a refusal) and the old
  leaked ``_dirty`` flags removed (``normalized_companies``).
* (b) ids: the oracle pins the old ``hash`` to ``int(sha1(str(key)))`` and the theme terms sorted (no collision occurs
  in the script; collisions and tombstones are unit-tested).
* (c) merge: the old code deleted the other person; the new people list leaves the tombstone out (identical), and
  ``Outcome.merged`` names it.
* (e) no write on no change: the new side's unchanged steps write nothing; their stored documents must still equal the
  old ones (the script records no metrics in between).
* (f) an unknown ``state``: the old route raised (500), the new one answers 400 (``DECLARED_F``).
Identical recorded values are stored once (``{"__same__": 1}``, rows ``{"__row__": id}``, see ``compact``). Exit 1 on any
difference.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT
from projectzero.founder_radar import routes
from projectzero.founder_radar.catalog import STATES
from projectzero.founder_radar.clock import Clock
from projectzero.founder_radar.companies import companies_queue
from projectzero.founder_radar.records import migrate_all
from projectzero.founder_radar.sources import next_batch, region_health
from projectzero.network.view import berlin_now, berlin_today, listing
from projectzero.ops.parity_founder_calls import utc_instant
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js

ORACLE = REPO_ROOT / "scripts" / "oracle" / "founder_radar_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_founder_radar.json"
CLOCK = "2026-11-12T10:00:00"
LATER = "2026-11-20T08:30:00"
DOCS = ("people.json", "radar_companies.json", "radar_research.json", "radar_metrics.json")
WRITE_OPS = ("action", "import", "company", "promote", "boardy", "pair", "review")
DECLARED_F = {"code": 400, "body": {"ok": False, "error": routes.STATE_REFUSAL + ", ".join(STATES)}}

# ------------------------------------------------------------------ the synthetic data folder (invented names only)
# fmt: off
LARK = "dom:larkspur.example"
QUILL = "name:quillbright robotics"
LOGIN, ILSA, TEODOR, RHEA = "p-vexmorrow-1201", "p-ilsa-marrowfield-4410", "p-teodor-vanstrel-0913", "p-rhea-quintaval-0042"
TBD, CORE, ORG, HEAD = "p-founders-tbd-7001", "p-core-team-7002", "p-brightwater-systems-gmbh-7003", "p-about-quillbright-7004"
OSKAR, WENNA_A, WENNA_B, WENNA_C = "p-oskar-fenwright", "p-wenna-calloway-5101", "p-wenna-calloway-5102", "p-wenna-calloway-5103"
ZORVIK = "p-zorvik-8820"
RECENT, OLD_DAY = "2026-10-30", "2026-06-01"


def ev(cat: str, claim: str, url: str = "https://github.com/invented", src: str = "GitHub", **kw: Any) -> dict[str, Any]:
    return {"category": cat, "claim": claim, "source": src, "source_url": url, "retrieved": "2026-10-20 09:00"} | kw


def radar_person(pid: str, name: str, **kw: Any) -> dict[str, Any]:
    """A record as the old ingest stored it (every migrated field present)."""
    p: dict[str, Any] = {
        "id": pid, "name": name, "created": "2026-10-20", "provenance": "radar_detected", "recommended": [], "startups": [], "watch": False,
        "aliases": [], "identity_status": "needs identity resolution", "identity_evidence": [], "former_roles": [], "founder_status": "UNKNOWN",
        "country": "", "institutions": [], "profile_urls": [], "github_id": "", "openalex_id": "", "orcid": "", "patent_inventor_id": "",
        "companies": [], "events": [], "ecosystems": [], "sources": [], "evidence": [], "signal_categories": {}, "evidence_confidence": "UNRESOLVED",
        "last_signal": "", "state_history": [{"from": "", "to": "detected", "on": "2026-10-20 09:00", "note": "detected by founder scan", "by": "radar"}],
        "intro_route": "", "relationship_owner": "Mohamed", "contact_channel": "", "machine_research": "", "human_judgment": "",
        "boardy": {"status": "", "history": []}, "opportunities": [], "updated": "2026-10-20", "why_surfaced": "founder scan",
        "signal": None, "dismissed_reason": "", "radar_state": "detected", "last_observed": "2026-10-20",
    }
    p.update(kw)
    if p.get("company") and p["company"] not in p["companies"]:
        p["companies"] = [*p["companies"], p["company"]]
    return p


def people() -> list[dict[str, Any]]:
    gh_src = [{"source": "GitHub — builders in Munich", "source_id": "gh-munich", "url": "https://github.com/invented", "route": "github-api"}]
    pz_src = [{"source": "Project Zero pipeline", "source_id": "pz-data", "url": "", "route": "pz-data"}]
    return [
        radar_person(LOGIN, "vexmorrow", github_id="1201", company="Quillbright Robotics", location="Munich", country="DE", region="DACH", sources=gh_src,
                     profile_urls=["https://github.com/vexmorrow"],
                     evidence=[ev("builder", "31 public repositories"), ev("entrepreneurial", "profile bio: co-founder building warehouse robots"),
                               ev("trajectory", "3 repos pushed this month", activity_date=RECENT)]),
        radar_person(ILSA, "Ilsa Marrowfield", github_id="4410", company="Quillbright Robotics", location="Munich", country="DE", region="DACH",
                     identity_status="resolved", sources=gh_src, profile_urls=["https://github.com/ilsamarrow", "https://quillbright.example/team"],
                     evidence=[ev("builder", "24 public repositories"), ev("builder", "maintains an open motion planner"),
                               ev("entrepreneurial", "co-founder of Quillbright Robotics", "https://quillbright.example/team", "official site"),
                               ev("trajectory", "shipped a release", activity_date=RECENT), ev("project_a", "repo/bio themes: robotics, industrial"),
                               ev("talent_magnet", "112 followers")]),
        radar_person(TEODOR, "Teodor Vanstrel", openalex_id="A9912", institutions=["Invented Institute of Optics"], location="Vienna", country="AT",
                     region="DACH", identity_status="resolved",
                     evidence=[ev("technical", "12 works on photonic sensing", "https://openalex.org/A9912", "OpenAlex"),
                               ev("technical_theme", "theme: energy infrastructure", "https://openalex.org/A9912", "OpenAlex"),
                               ev("trajectory", "paper published", "https://openalex.org/A9912", "OpenAlex", activity_date=OLD_DAY)]),
        radar_person(RHEA, "Rhea Quintaval", company="Larkspur Analytics", identity_status="verified by operator", founder_status="verified founder",
                     sources=pz_src, why_surfaced="founder of pipeline company Larkspur Analytics", location="Porto", country="PT",
                     identity_evidence=["named in Mohamed's own data (pipeline)"],
                     evidence=[ev("entrepreneurial", "named founder of Larkspur Analytics", "", "Project Zero pipeline"),
                               ev("project_a", "company archetype 7", "", "Project Zero pipeline")]),
        radar_person(TBD, "Founders TBD", company="Larkspur Analytics", sources=pz_src),
        radar_person(CORE, "Core Team", company="Quillbright Robotics", sources=pz_src, watch=True, notes="ask at the demo day"),
        radar_person(ORG, "Brightwater Systems GmbH", github_id="7003", sources=gh_src, location="Munich"),
        radar_person(HEAD, "About Quillbright", sources=gh_src, name_attributed=True),
        {"id": OSKAR, "name": "Oskar Fenwright", "created": "2026-03-02", "provenance": "user_provided", "recommended": [], "startups": [],
         "relationship_strength": "warm", "last_interaction": "2026-10-01", "next_action": "send the robotics deck", "next_action_date": "2026-11-10",
         "company": "Pellucid Grid", "location": "Porto", "watch": True},
        radar_person(WENNA_A, "Wenna Calloway", github_id="5101", company="Fernhollow AI", location="Munich", country="DE", region="DACH",
                     identity_status="resolved", sources=gh_src, evidence=[ev("builder", "18 public repositories")]),
        radar_person(WENNA_B, "Wenna Calloway", openalex_id="A5102", company="Fernhollow AI", institutions=["Fernhollow AI"], location="Munich",
                     evidence=[ev("technical", "4 works on agent planning", "https://openalex.org/A5102", "OpenAlex"),
                               ev("trajectory", "talk at a robotics meetup", "https://fernhollow.example/news", "official site", activity_date=RECENT)]),
        radar_person(WENNA_C, "Wenna Calloway", github_id="5103", company="Fernhollow AI", location="Berlin"),
        radar_person(ZORVIK, "zorvik", github_id="8820", name_attributed=False, aliases=["zorvik"], company="Larkspur Analytics", location="Porto",
                     country="PT", evidence=[ev("builder", "Zorvik Talmadge (zorvik) builds the Larkspur data pipeline", "https://github.com/zorvik")]),
    ]


def companies_doc() -> dict[str, Any]:
    """The founder references the old GET had persisted (from the migrated people, at an earlier day), the stored
    company records, and two leaked ``_dirty`` flags."""
    base = {"companies": {
        QUILL: {"notes": "seen at a demo day"},
        LARK: {"facts": [{"field": "founded", "value": "2023", "claim": "since 2023", "source_url": "", "confirmed": False}],
               "description": "Industrial robotics analytics for energy infrastructure and defence logistics", "access_routes": []},
        "name:old leftover co": {"description": "a record no person links any more"},
    }}
    earlier = utc_instant("2026-10-01T08:00:00")
    rows = listing(migrate_all(people(), Clock.at(earlier)).people, berlin_today(earlier))
    _q, refs = companies_queue(rows, companies_doc=base, research_doc=None, signals=signals(), now=earlier, today=berlin_today(earlier))
    doc = refs.doc
    doc["companies"][QUILL]["_dirty"] = True
    doc["companies"]["name:old leftover co"]["_dirty"] = True
    return doc


def prop(pid: str, field_: str, value: Any, passage: str, url: str, conf: str = "high", rank: int = 2, **kw: Any) -> tuple[str, dict[str, Any]]:
    return pid, {"id": pid, "field": field_, "value": value, "passage": passage, "url": url, "source_label": "official site",
                 "source_type": "official domain", "activity_date": "", "retrieved": "2026-11-01 09:00", "confidence": conf,
                 "reason": "explicit wording on the official site", "status": "pending", "person": None, "source_rank": rank} | kw


NEWS, TEAM, HOME = "https://larkspur.example/news/2026-launch", "https://larkspur.example/about/team", "https://larkspur.example/"


def research_doc() -> dict[str, Any]:
    def person(n: str, r: str) -> dict[str, Any]:
        return {"name": n, "role": r, "company": "Larkspur Analytics"}

    proposals = dict([
        prop("founded-news-long-identifier-0001", "founded", "2025", "Larkspur Analytics was founded in 2025 in Porto.", NEWS, rank=1),
        prop("status-01", "status", "currently operating", "Larkspur Analytics is currently operating three pilots.", TEAM),
        prop("f2", "founded", "2024", "Since 2024 the team has been building.", HOME, conf="medium", rank=3),
        prop("status-dup-homepage", "status", "Currently operating", "We are currently operating pilots.", HOME, conf="medium", rank=3),
        prop("fit-inference-77", "project_a_fit", "MEDIUM", "industrial robotics analytics", HOME, conf="medium", rank=3,
             reason="company description overlaps Project A themes: robotics, energy", evidence_kind="machine_inference"),
        prop("acc", "access_route", "hello@larkspur.example", "Write to hello@larkspur.example.", TEAM, conf="medium"),
        prop("founder-rhea-quintaval-team", "founder", "Rhea Quintaval", "Rhea Quintaval, Co-Founder & CEO of Larkspur Analytics.", TEAM,
             person=person("Rhea Quintaval", "Co-Founder & CEO")),
        prop("fz", "founder", "Zorvik Talmadge", "Zorvik Talmadge, co-founder and CTO of Larkspur Analytics.", TEAM,
             person=person("Zorvik Talmadge", "co-founder")),
        prop("founder-malformed-x", "founder", "Read More", "Read More about the team.", TEAM, conf="low", person=person("Read More", "founder")),
        prop("fdone", "founder", "Ilsa Marrowfield", "Ilsa Marrowfield, founder.", TEAM, status="rejected", person=person("Ilsa Marrowfield", "founder")),
        prop("recent-activity-future-dated", "recent_activity", "dated item on news page (harbour pilot)", "On 30 December 2026 the pilot starts.",
             NEWS, rank=1, activity_date="2026-12-30"),
        prop("ra", "recent_activity", "dated item on news page (port operator pilot)", "On 2 November 2026 we started a pilot.", NEWS, rank=1,
             activity_date="2026-11-02"),
        prop("linkedin-rq", "linkedin_profile", "https://www.linkedin.com/in/rhea-quintaval", "LinkedIn", TEAM, conf="medium"),
        prop("h", "hiring_signal", "we are hiring", "We are hiring robotics engineers.", HOME, conf="medium", rank=3),
        prop("stage-confirmed-earlier", "stage", "pre-seed", "Larkspur Analytics raised a pre-seed round.", NEWS, rank=1, status="confirmed"),
        prop("tmpl", "status", "Home About Team", "Home About Team", HOME, conf="low", rank=3, template_text=True),
    ])
    pages = {
        NEWS: {"status": 200, "final_url": NEWS, "chars": 1800, "retrieved": "2026-11-01 09:00"},
        TEAM: {"status": 200, "final_url": TEAM, "chars": 2400, "retrieved": "2026-11-01 09:00"},
        HOME: {"status": 200, "final_url": HOME, "chars": 3100, "retrieved": "2026-11-01 09:00"},
        "https://larkspur.example/login": {"status": "skipped", "reason": "login wall", "retrieved": "2026-11-01 09:00"},
        "https://larkspur.example/x": {"status": 404, "reason": "blocked: not found", "retrieved": "2026-11-01 09:00"},
    }
    return {"domains": {
        LARK: {"domain": "larkspur.example", "pages": pages, "pending": [], "done": True, "proposals": proposals,
               "history": [{"proposal": "tmpl-old", "from": "pending", "to": "rejected", "by": "operator", "on": "2026-11-01 09:10:00", "person": None}],
               "pairings": {"an-earlier-pairing-with-a-long-identifier": {"person_id": RHEA, "founder_ref_id": "ref-x", "proposed_name": "Rhea Quintaval",
                                                                          "by": "operator", "on": "2026-11-01 09:11:00"}},
               "previous_runs": [], "refreshed_at": "2026-11-01 09:00", "last_research": "2026-11-01 09:00", "note": ""},
        QUILL: {"domain": "", "pages": {}, "pending": [], "done": False, "proposals": {}, "history": [],
                "note": "no official domain — research needs a domain"},
    }}


def signals() -> list[dict[str, Any]]:
    return [
        {"company": "Larkspur Analytics", "website": "https://larkspur.example", "location": "Porto", "earliness": "pre_seed", "archetype": 7,
         "one_liner": "industrial robotics analytics", "funding_status": "pre-seed (claimed)", "discovery_date": "2026-11-03",
         "founders": [{"name": "Rhea Quintaval"}]},
        {"company": "Pellucid Grid", "location": "Porto", "one_liner": "grid software", "discovery_date": "2026-07-01"},
    ]


def health_doc() -> dict[str, Any]:
    cities = [
        {"city": "Munich", "country": "DE", "source_id": "gh-munich", "status": "ok", "attempted": True, "last_attempt": "2026-11-10 08:00",
         "last_ok": "2026-11-10 08:00", "raw": 6, "note": "", "next": "in 2 scan(s)"},
        {"city": "Zürich", "country": "CH", "source_id": "gh-zurich", "status": "not attempted this scan", "attempted": False, "last_attempt": "",
         "last_ok": "", "raw": 0, "note": "", "next": "next scan"},
    ]
    return {"scan_time": "2026-11-10 08:00", "totals": {"people": 13}, "note": "one scan",
            "sources": [{"id": "gh-munich", "name": "GitHub — builders in Munich", "kind": "github_users", "status": "ok", "note": "6 users", "last_ok": "2026-11-10 08:00"},
                        {"id": "oa-de-robotics", "name": "OpenAlex — robotics", "kind": "openalex_works", "status": "failed", "note": "timeout"},
                        {"id": "linkedin", "name": "LinkedIn", "kind": "optional", "status": "config_required", "note": "manual only"},
                        {"id": "apollo", "name": "Apollo", "kind": "optional", "status": "ok"},
                        {"id": "epo", "name": "EPO", "kind": "optional", "status": "config_required", "note": "needs a key"}],
            "regions": [{"region": "DACH", "cities": cities}]}


def regions_doc() -> dict[str, Any]:
    return {"regions": [{"region": "DACH", "cities": [["Munich", "DE"], ["Zürich", "CH"], ["Vienna", "AT"], ["Berlin", "DE"]]},
                        {"region": "Iberia", "cities": [["Porto", "PT"], ["Lisbon", "PT"]]}]}


def metrics_doc() -> dict[str, Any]:
    day = {"date": "2026-11-10", "gold_now": 0, "strong_investigation": 0, "founder_claims_unresolved": 3, "research_talent": 1}
    return {"history": [{**day, "date": "2026-11-09"}, day], "latest": day}


def corpus() -> dict[str, Any]:
    return {"people.json": {"people": people()}, "radar_companies.json": companies_doc(), "radar_research.json": research_doc(),
            "real_data.json": {"week": "2026-W45", "signals": signals()}, "radar_health.json": health_doc(), "radar_regions.json": regions_doc(),
            "radar_cursor.json": {"next": 3, "batches_completed": 1}, "radar_metrics.json": metrics_doc()}


def defaults_corpus() -> dict[str, Any]:
    return {"people.json": {"people": people()[1:3]}, "radar_regions.json": {"regions": "not a list"}, "radar_cursor.json": "not an object"}


CUSTOM_CSV = ("name,linkedin,company,role,location,country\n"
              "Juno Avenhart,linkedin.com/in/juno-avenhart,Pellucid Grid,Founder,Porto,PT\n"
              "Ilsa Marrowfield,https://www.linkedin.com/in/ilsa-marrowfield/,Quillbright Robotics,CTO,Munich,DE\n"
              "Brightwater Labs GmbH,,,,,\n"
              "Cassius Wrenfold,,,,Vienna,AT\n"
              "CEO,,,,,\n")
LINKEDIN_CSV = ("\ufeffNotes:\n"
                "\"When exporting your connection data, some addresses may be missing.\"\n\n"
                "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
                "Mireille,Ostrand,https://www.linkedin.com/in/mireille-ostrand,mireille@pellucid.example,Pellucid Grid,Co-Founder,03 Nov 2026\n"
                "Bram,Okonkwo-Haas,https://www.linkedin.com/in/bram-oh,,Fernhollow AI,Engineer,01 Oct 2026\n"
                "Team,,,,,,\n")
CUSTOM_CSV_AGAIN = ("name,linkedin,company,role,location,country\n"
                    "Juno Avenhart,https://linkedin.com/in/juno-avenhart/,Pellucid Grid,CEO,Porto,PT\n"
                    "Ilsa Marrowfield,https://www.linkedin.com/in/ilsa-marrowfield/,Quillbright Robotics,CTO,Munich,DE\n")
URL ="https://larkspur.example/about/team"


def act(pid: str, action: str, **kw: Any) -> dict[str, Any]:
    return {"op": "action", "body": {"id": pid, "action": action, **kw}}


STEPS: list[dict[str, Any]] = [
    {"op": "get"},
    {"op": "proposals", "body": {"key": LARK}},
    {"op": "proposals", "body": {"key": "dom:unknown.example"}},
    {"op": "region_health", "args": {"rows_by_id": {"gh-munich": {"status": "ok", "attempted_at": "2026-11-12 09:00", "last_ok": "2026-11-12 09:00", "raw": 4, "note": "4 users"},
                                                    "gh-porto": {"status": "not attempted — rate limited", "note": "rate limited"}},
                                     "prev": health_doc()["regions"]}},
    {"op": "next_batch"},
    act("p-nobody", "watch"),
    act(ILSA, "watch", note="strong builder"),
    act(ILSA, "watch"),
    act(ILSA, "link_company", company="Fernhollow AI"),
    act(ILSA, "link_company", company="Fernhollow AI"),  # (e) nothing changes
    act(ILSA, "link_event", event="Porto Robotics Night"),
    act(TEODOR, "research", note="photonics"),
    act(WENNA_C, "dismiss", note="duplicate profile"),
    act(TEODOR, "intro_path", route="via the optics lab"),
    act(LOGIN, "opportunity"),
    act(ILSA, "opportunity", name="Quillbright spin-out"),
    act(LOGIN, "boardy"),
    act(ILSA, "boardy", status="introduction requested"),
    act(TEODOR, "state", state="contacted", note="emailed"),
    {**act(TEODOR, "state", state="nonsense"), "declared": "f"},
    act(TEODOR, "linkedin", url="linkedin.com/in/teodor-vanstrel"),
    act(TEODOR, "linkedin", url="https://www.linkedin.com/in/teodor-vanstrel", verified=True),
    act(ILSA, "linkedin", url="https://www.linkedin.com/in/ilsa-marrowfield/", verified=True, fact="profile matches", confirm=True, founder=True, note="checked"),
    act(TEODOR, "evidence", url="https://optics.example/teodor", claim="leads a lab"),
    act(TEODOR, "evidence", url="https://www.linkedin.com/in/x", label="LinkedIn", claim="x"),
    act(TEODOR, "evidence", url="https://duckduckgo.com/?q=teodor", label="search", claim="x"),
    act(TEODOR, "evidence", kind="trajectory", url="https://optics.example/news", label="lab news", claim="new grant"),
    act(TEODOR, "evidence", kind="trajectory", url="https://optics.example/news", label="lab news", claim="new grant", activity_date="2026-11-05"),
    act(TEODOR, "evidence", kind="builder", url="https://github.com/tvanstrel", label="GitHub profile", claim="maintains a sensor toolkit", field="builder"),
    act(TEODOR, "evidence", kind="builder", url="https://github.com/tvanstrel", label="GitHub profile", claim="maintains a  sensor toolkit", field="builder"),  # deduped: (e)
    act(ZORVIK, "confirm_identity", name="Zorvik Talmadge", handle="zorvik", company="Larkspur Analytics", url=URL, label="team page", fact="x"),
    act(ZORVIK, "confirm_identity", name="Zorvik Talmadge", handle="zorvik", company="Larkspur Analytics", url=URL, label="team page", fact="Zorvik Talmadge works there", confirm=True),
    act(ZORVIK, "confirm_identity", name="Zorvik Talmadge", handle="zorvik", company="Larkspur Analytics", url="https://github.com/zorvik", label="GitHub profile",
        fact="Zorvik Talmadge (zorvik) is co-founder of Larkspur Analytics", confirm=True),
    act(RHEA, "confirm_identity", name="Rhea Quintaval", company="Larkspur Analytics", url=URL, label="team page",
        fact="Rhea Quintaval, Co-Founder & CEO of Larkspur Analytics.", confirm=True),
    act(LOGIN, "investigate_founder", note="bio says co-founder"),
    act(TEODOR, "verify_identity", url="https://optics.example/teodor", label="lab page", fact="Teodor Vanstrel heads the lab"),
    act(TEODOR, "verify_identity", url="https://optics.example/teodor", label="lab page", fact="Teodor Vanstrel heads the lab", confirm=True),
    act(WENNA_A, "merge", other="p-nobody", confirm=True),
    act(WENNA_A, "merge", other=WENNA_C, confirm=True),
    act(WENNA_A, "merge", other=WENNA_B),
    act(WENNA_A, "merge", other=WENNA_B, confirm=True),
    act(WENNA_B, "watch"),
    {"op": "promote", "body": {"id": WENNA_B}},
    {"op": "boardy", "body": {"id": WENNA_B}},
    act(ILSA, "teleport"),
    {"op": "import", "body": {"csv": CUSTOM_CSV, "label": "demo day list"}},
    {"op": "import", "body": {"csv": LINKEDIN_CSV, "include_email": True}},
    {"op": "import", "body": {"csv": CUSTOM_CSV_AGAIN}},  # merges only (re-importing an unresolvable row: see the tests)
    {"op": "import", "body": {}},
    {"op": "company", "body": {}},
    {"op": "company", "body": {"key": LARK, "founded": "2020"}},
    {"op": "company", "body": {"key": LARK, "fact": {"field": "headcount", "value": "9", "claim": "nine people", "url": URL, "label": "team page", "confirm": True}}},
    {"op": "company", "body": {"key": LARK, "fact": {"field": "founded", "value": "2025", "claim": "founded in 2025", "url": URL, "label": "team page"}}},
    {"op": "company", "body": {"key": LARK, "fact": {"field": "recent_activity", "value": "pilot", "claim": "a pilot", "url": URL, "label": "team page", "confirm": True}}},
    {"op": "company", "body": {"key": LARK, "fact": {"field": "early_stage_signal", "value": "maybe", "claim": "early", "url": URL, "label": "team page", "confirm": True}}},
    {"op": "company", "body": {"key": LARK, "fact": {"field": "founded", "value": "", "claim": "founded", "url": URL, "label": "team page", "confirm": True}}},
    {"op": "company", "body": {"key": LARK, "fact": {"field": "founded", "value": "2025", "claim": "Larkspur Analytics was founded in 2025", "url": NEWS, "label": "news", "confirm": True}}},
    {"op": "company", "body": {"key": LARK, "fact": {"field": "founded", "value": "2025", "claim": "Larkspur Analytics was founded in 2025", "url": NEWS, "label": "news", "confirm": True}}},
    {"op": "company", "body": {"key": LARK, "fact": {"field": "early_stage_signal", "value": "yes", "claim": "pre-seed company", "url": NEWS, "label": "news", "confirm": True}}},
    {"op": "company", "body": {"key": LARK, "evidence": {"url": "https://www.linkedin.com/company/larkspur", "label": "LinkedIn", "claim": "x"}}},
    {"op": "company", "body": {"key": QUILL, "evidence": {"url": "https://quillbright.example/", "label": "homepage", "claim": "builds warehouse robots", "field": "one_liner"},
                               "description": "Warehouse robotics", "notes": "met Ilsa at the demo day"}},
    {"op": "company", "body": {"key": "name:nowhere co", "notes": "an unknown key creates a record"}},
    {"op": "company", "body": {"key": QUILL}},  # (e)
    {"op": "promote", "body": {"id": LOGIN}},
    {"op": "promote", "body": {"id": "p-nobody"}},
    {"op": "promote", "body": {"id": ILSA, "how": "demo day", "introduced_by": "Oskar Fenwright", "stage": "replied", "last_interaction": "2026-11-11",
                               "next_action": "intro call", "next_action_date": "2026-11-19", "channel": "email", "notes": "warm intro"}},
    {"op": "promote", "body": {"id": TEODOR, "introduced_by": "Someone Unknown", "stage": "not a network state"}},
    {"op": "boardy", "body": {"id": "p-nobody"}},
    {"op": "boardy", "body": {"id": ILSA}},
    {"op": "boardy", "body": {"id": TEODOR, "desired": "a coffee", "exclusions": "no pitch"}},
    {"op": "pair", "body": {"key": LARK, "proposal": "nope", "person": ZORVIK}},
    {"op": "pair", "body": {"key": LARK, "proposal": "status-01", "person": ZORVIK}},
    {"op": "pair", "body": {"key": LARK, "proposal": "fdone", "person": ZORVIK}},
    {"op": "pair", "body": {"key": LARK, "proposal": "founder-malformed-x", "person": ZORVIK}},
    {"op": "pair", "body": {"key": LARK, "proposal": "fz", "person": OSKAR}},
    {"op": "pair", "body": {"key": LARK, "proposal": "fz", "person": RHEA}},
    {"op": "pair", "body": {"key": LARK, "proposal": "fz", "person": ZORVIK}},
    {"op": "proposals", "body": {"key": LARK}},
    {"op": "review", "body": {"key": "dom:unknown.example", "confirm": ["status-01"]}},
    {"op": "review", "body": {"key": LARK, "confirm": ["founded-news-long-identifier-0001", "status-01", "acc", "founder-rhea-quintaval-team", "fz",
                                                       "founder-malformed-x", "recent-activity-future-dated", "stage-confirmed-earlier", "no-such-proposal"],
                              "reject": ["fit-inference-77", "fdone"],
                              "bindings": {"founder-rhea-quintaval-team": RHEA, "fz": ZORVIK, "founder-malformed-x": WENNA_B}}},
    {"op": "review", "body": {"key": LARK, "confirm": ["founded-news-long-identifier-0001", "status-01", "fz", "founder-malformed-x"],
                              "reject": ["fit-inference-77"], "bindings": {"founder-malformed-x": WENNA_B}}},  # the replay
    {"op": "review", "body": {"key": LARK, "confirm": ["ra", "founder-malformed-x"], "bindings": {"founder-malformed-x": ILSA}}},
    {"op": "proposals", "body": {"key": LARK}},
    {"op": "get", "at": LATER},
]
LATER_STEPS: list[dict[str, Any]] = [{"op": "get", "at": LATER}, {"op": "proposals", "body": {"key": LARK}, "at": LATER}]
DEFAULT_STEPS: list[dict[str, Any]] = [
    {"op": "get"},
    {"op": "region_health", "args": {"rows_by_id": {"gh-berlin": {"status": "ok", "attempted_at": "2026-11-12 09:00", "last_ok": "2026-11-12 09:00", "raw": 3, "note": "3 users"}},
                                     "prev": []}},
    {"op": "next_batch"},
    {"op": "proposals", "body": {"key": QUILL}},
    act(ILSA, "watch"),
    {"op": "import", "body": {"csv": CUSTOM_CSV}},
    {"op": "company", "body": {"key": QUILL, "notes": "first record"}},
    {"op": "review", "body": {"key": QUILL}},
    {"op": "pair", "body": {"key": QUILL, "proposal": "x", "person": ILSA}},
    {"op": "get"},
]
EMPTY_STEPS: list[dict[str, Any]] = [
    {"op": "get"},
    {"op": "proposals", "body": {"key": QUILL}},
    act(ILSA, "watch"),
    {"op": "promote", "body": {"id": ILSA}},
    {"op": "boardy", "body": {"id": ILSA}},
    {"op": "import", "body": {"csv": LINKEDIN_CSV}},
    {"op": "company", "body": {"key": QUILL, "description": "first"}},
    {"op": "get"},
]
# fmt: on
SETS: dict[str, Any] = {
    "main": {"docs": corpus, "steps": STEPS},
    "later": {"docs": corpus, "steps": LATER_STEPS},
    "defaults": {"docs": defaults_corpus, "steps": DEFAULT_STEPS},
    "empty": {"docs": dict, "steps": EMPTY_STEPS},
}


def _files(docs: dict[str, Any]) -> dict[str, bytes]:
    return {k: json.dumps(v, ensure_ascii=False, indent=2).encode("utf-8") for k, v in docs.items()}


def run_oracle(inp: dict[str, Any], files: dict[str, bytes]) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-founder-radar-oracle-") as tmp:
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
        env = {
            k: v for k, v in os.environ.items() if not (k == "SUPABASE_DB_URL" or k.endswith(("_API_KEY", "_TOKEN")))
        }
        env |= {"PZ_DATA": str(data), "PZ_TESTING": "1", "PYTHONHASHSEED": "0",
                "PYTHONPATH": str(OLD_REPO / "backend" / "src")}  # fmt: skip
        run = subprocess.run([str(python), str(ORACLE), str(srcf), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_text(encoding="utf-8"))
        return out


# ------------------------------------------------------------------ the new side
def _try(fn: Callable[[], tuple[int, Any]]) -> dict[str, Any]:
    try:
        code, body = fn()
    except Exception as exc:
        return {"raises": type(exc).__name__}
    return {"code": code, "body": js(body)}


def _key(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


@dataclass
class Store:
    """The new side's state between steps: what the DB layer would hold."""

    docs: dict[str, Any]
    reserved: set[str] = field(default_factory=set)

    def people(self) -> list[dict[str, Any]]:
        d = self.docs.get("people.json")
        return list(d.get("people") or []) if isinstance(d, dict) else []

    def signals(self) -> Any:
        d = self.docs.get("real_data.json")
        return d.get("signals", []) if isinstance(d, dict) else []

    def inputs(self) -> routes.Inputs:
        return routes.Inputs(
            people=self.people(), companies=self.docs.get("radar_companies.json"),
            research=self.docs.get("radar_research.json"), health=self.docs.get("radar_health.json"),
            regions=self.docs.get("radar_regions.json"), metrics=self.docs.get("radar_metrics.json"),
            signals=self.signals(), reserved_ids=frozenset(self.reserved),
        )  # fmt: skip

    def stored(self) -> dict[str, Any]:
        return {n: js(self.docs.get(n)) for n in DOCS}

    def apply(self, o: routes.Outcome) -> list[str]:
        wrote = []
        if o.people is not None:
            body = dict(self.docs.get("people.json") or {})
            body["people"] = o.people
            self.docs["people.json"] = body
            wrote.append("people.json")
        if o.merged is not None:
            self.reserved.add(o.merged[1])
        for name, doc in (("radar_companies.json", o.companies), ("radar_research.json", o.research),
                          ("radar_metrics.json", o.metrics)):  # fmt: skip
            if doc is not None:
                self.docs[name] = doc
                wrote.append(name)
        return wrote


def check_outcome(before: routes.Inputs, o: routes.Outcome) -> list[str]:
    """The ``*_changed`` lists name exactly the new or changed entries, in the new document's order; documents that
    equal the input are never returned (decision e)."""
    problems = []
    if o.people is not None:
        was = {_key(p.get("id")): _key(p) for p in before.people}
        want = [p.get("id") for p in o.people if was.get(_key(p.get("id"))) != _key(p)]
        if o.people_changed != want:
            problems.append(f"people_changed {o.people_changed} != {want}")
        if _key(o.people) == _key(before.people):
            problems.append("an unchanged people list was returned")
    elif o.people_changed:
        problems.append("people_changed without people")
    for name, doc, changed, old in (("companies", o.companies, o.companies_changed, before.companies),
                                    ("domains", o.research, o.research_changed, before.research)):  # fmt: skip
        if doc is None:
            if changed:
                problems.append(f"{name} changed without a document")
            continue
        if _key(doc) == _key(old):
            problems.append(f"an unchanged {name} document was returned")
        b = (old or {}).get(name) or {}
        want = [k for k, v in doc[name].items() if k not in b or _key(b[k]) != _key(v)]
        if changed != want:
            problems.append(f"{name}_changed {changed} != {want}")
    return problems


def normalized_companies(doc: Any, people_doc: Any, signals: Any, research: Any, wall: str) -> Any:
    """Decision a: the companies document with its founder references derived as a read derives them (the old routes
    persisted them on refusals and reads too) and without the old leaked ``_dirty`` flags."""
    if doc is None:
        return None
    ppl = (people_doc or {}).get("people") or [] if isinstance(people_doc, dict) else []
    now = berlin_now(utc_instant(wall))
    rows = listing(ppl, now.date())
    _q, refs = companies_queue(
        rows, companies_doc=doc, research_doc=research, signals=signals, now=now, today=berlin_today(now)
    )
    return js(refs.doc)


def new_side(docs: dict[str, Any], clock: str, steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """(the rows, the invariant problems)."""
    st = Store(copy.deepcopy(docs))
    wall = clock
    out: list[dict[str, Any]] = []
    problems: list[str] = []
    fns = {"action": routes.action, "import": routes.import_csv, "company": routes.company, "promote": routes.promote,
           "boardy": routes.boardy_brief, "pair": routes.pair, "review": routes.review}  # fmt: skip
    for i, step in enumerate(steps):
        wall = step.get("at") or wall
        now = utc_instant(wall)
        today = berlin_today(now)
        op = step["op"]
        body = copy.deepcopy(step.get("body") or {})
        row: dict[str, Any] = {}

        def get(now: Any = now, today: Any = today) -> dict[str, Any]:
            return _try(lambda: (200, routes.view(st.inputs(), today=today, now=now)))

        if op == "get":
            row["answer"] = get()
        elif op == "proposals":

            def prop_read(body: dict[str, Any] = body, today: Any = today, now: Any = now) -> tuple[int, Any]:
                return 200, routes.proposals(st.inputs(), body, today=today, now=now).body

            row["answer"] = _try(prop_read)
        elif op == "region_health":
            a = step.get("args") or {}
            row["answer"] = _try(lambda a=a: (200, region_health(a.get("rows_by_id") or {}, a.get("prev") or [],
                                                                 st.docs.get("radar_regions.json"), st.docs.get("radar_cursor.json"))))  # type: ignore[misc]  # fmt: skip
        elif op == "next_batch":
            row["answer"] = _try(
                lambda: (200, list(next_batch(st.docs.get("radar_regions.json"), st.docs.get("radar_cursor.json"))))
            )
        else:
            before = st.inputs()
            frozen = _key(copy.deepcopy(before.__dict__ | {"reserved_ids": sorted(before.reserved_ids)}))
            try:
                o = fns[op](before, body, today=today, now=now)
            except Exception as exc:
                row["answer"] = {"raises": type(exc).__name__}
                o = None
            if o is not None:
                row["answer"] = {"code": o.status, "body": js(o.body)}
                if _key(before.__dict__ | {"reserved_ids": sorted(before.reserved_ids)}) != frozen:
                    problems.append(f"/steps[{i}]: the input was mutated")
                problems += [f"/steps[{i}]: {p}" for p in check_outcome(before, o)]
                row["wrote"] = st.apply(o)
                row["merged"] = list(o.merged) if o.merged else None
            row["stored"] = st.stored()
            row["view"] = get()
        out.append(row)
    return out, problems


# ------------------------------------------------------------------ the golden (repeated values stored once)
# Each recorded part (a GET body's top-level entries, a stored document, any other answer) equal to the last full value
# at the same place is ``{"__same__": 1}``; inside a full GET ``people`` / ``companies`` list or a stored people list,
# a row equal to the last full row with the same id (key) is ``{"__row__": id}``. Equality is order-sensitive (the
# serialized JSON), so expanding restores every key order exactly. GET answers and post-write views share one memo.
SAME, ROW = "__same__", "__row__"
ROW_LISTS = {"get.people": "id", "get.companies": "key", "stored.people.json": "id"}


def _rows(path: str, value: Any) -> list[Any] | None:
    if path == "stored.people.json":
        value = value.get("people") if isinstance(value, dict) else None
    return value if isinstance(value, list) else None


def _setter(d: dict[str, Any], k: str) -> Callable[[Any], None]:
    def put(x: Any) -> None:
        d[k] = x

    return put


def _parts(kind: str, value: Any) -> list[tuple[str, Any, Callable[[Any], None]]]:
    """The packable parts of a recorded value: (memo path, value, setter)."""
    if kind == "stored" and isinstance(value, dict):
        return [(f"stored.{n}", v, _setter(value, n)) for n, v in value.items()]
    body = value.get("body") if isinstance(value, dict) else None
    if isinstance(body, dict) and "people" in body and "leads" in body:  # a GET body
        return [(f"get.{k}", v, _setter(body, k)) for k, v in body.items()]
    if isinstance(value, dict) and "body" in value:
        return [(f"{kind}.body", value["body"], _setter(value, "body"))]
    return []


def compact(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    last: dict[str, str] = {}
    rows_last: dict[str, dict[str, str]] = {}
    out = []
    for st in steps:
        row = copy.deepcopy(st)
        for kind in ("answer", "view", "stored"):
            if kind not in row:
                continue
            for path, v, put in _parts("answer" if kind == "answer" else kind, row[kind]):
                k = _key(v)
                if last.get(path) == k:
                    put({SAME: 1})
                    continue
                last[path] = k
                rows = _rows(path, v)
                idk = ROW_LISTS.get(path)
                if rows is None or idk is None:
                    continue
                seen = rows_last.setdefault(path, {})
                for pos, r in enumerate(rows):
                    if not isinstance(r, dict):
                        continue
                    rid, rk = _key(r.get(idk)), _key(r)
                    if seen.get(rid) == rk:
                        rows[pos] = {ROW: r.get(idk)}
                    else:
                        seen[rid] = rk
        out.append(row)
    return out


def expand(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    last: dict[str, Any] = {}
    rows_last: dict[str, dict[str, Any]] = {}
    out: list[dict[str, Any]] = []
    for st in steps:
        row = copy.deepcopy(st)
        for kind in ("answer", "view", "stored"):
            if kind not in row:
                continue
            for path, v, put in _parts("answer" if kind == "answer" else kind, row[kind]):
                if isinstance(v, dict) and set(v) == {SAME}:
                    put(copy.deepcopy(last[path]))
                    continue
                rows = _rows(path, v)
                idk = ROW_LISTS.get(path)
                if rows is not None and idk is not None:
                    seen = rows_last.setdefault(path, {})
                    for pos, r in enumerate(rows):
                        if isinstance(r, dict) and set(r) == {ROW}:
                            rows[pos] = copy.deepcopy(seen[_key(r[ROW])])
                        elif isinstance(r, dict):
                            seen[_key(r.get(idk))] = r
                last[path] = copy.deepcopy(v)
        out.append(row)
    return out


def compare_goldens(golden: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for name, s in golden["sets"].items():
        expected = expand(s["expected"])
        got, invariants = new_side(s["docs"], golden["clock"], s["steps"])
        problems += [f"/{name}{p}" for p in invariants]
        problems += [f"/{name}{p}" for p in compare_steps(s, expected, got, golden["clock"])]
    return problems


def compare_steps(
    s: dict[str, Any], expected: list[dict[str, Any]], got: list[dict[str, Any]], clock: str
) -> list[str]:
    problems: list[str] = []
    if len(expected) != len(got):
        return [f": {len(expected)} steps != {len(got)}"]
    wall = clock
    signals = (s["docs"].get("real_data.json") or {}).get("signals", [])
    for i, (step, a, b) in enumerate(zip(s["steps"], expected, got, strict=True)):
        wall = step.get("at") or wall
        old_answer = (
            DECLARED_F
            if step.get("declared") == "f" and a.get("answer") == {"raises": "ValueError"}
            else a.get("answer")
        )
        if _key(old_answer) != _key(b.get("answer")):
            problems += [f"/steps[{i}]/answer{p}" for p in diff({"x": js(old_answer)}, {"x": js(b.get("answer"))})] or [
                f"/steps[{i}]/answer: key order differs"
            ]
        if _key(a.get("view")) != _key(b.get("view")):
            problems += [f"/steps[{i}]/view{p}" for p in diff({"x": a.get("view")}, {"x": b.get("view")})] or [
                f"/steps[{i}]/view: key order differs"
            ]
        if "stored" in a:
            sa, sb = a["stored"], b.get("stored") or {}
            for n in DOCS:
                x, y = sa.get(n), sb.get(n)
                if n == "radar_companies.json":
                    x = normalized_companies(x, sa.get("people.json"), signals, sa.get("radar_research.json"), wall)
                    y = normalized_companies(y, sb.get("people.json"), signals, sb.get("radar_research.json"), wall)
                if _key(x) != _key(y):
                    problems += [f"/steps[{i}]/stored/{n}{p}" for p in diff({"x": x}, {"x": y})] or [
                        f"/steps[{i}]/stored/{n}: key order differs"
                    ]
            extra = set(b.get("wrote") or []) - set(a.get("wrote") or [])
            if step["op"] == "pair":
                extra.discard("radar_companies.json")  # the references the old GET had persisted before every pairing
            if extra:
                problems.append(f"/steps[{i}]/wrote: the new side wrote {sorted(extra)} that the old route did not")
    return problems


def write_goldens() -> int:
    sets: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    for name, spec in SETS.items():
        docs = spec["docs"]()
        oracle = run_oracle({"clock": CLOCK, "steps": spec["steps"]}, _files(docs))
        meta = oracle.pop("meta")
        sets[name] = {"docs": docs, "steps": spec["steps"], "expected": compact(oracle["steps"])}
    golden = {"provenance": meta, "clock": CLOCK, "sets": sets}
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    # NOT sort_keys: the documents' insertion order is part of the input (and of what the oracle recorded)
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=None) + "\n", encoding="utf-8", newline="\n")
    problems = compare_goldens(json.loads(GOLDEN.read_text(encoding="utf-8")))
    print(json.dumps({"golden": str(GOLDEN), "bytes": GOLDEN.stat().st_size, "old": meta, "summary": summary(golden)},
                     indent=1, ensure_ascii=False))  # fmt: skip
    for p in problems[:80]:
        print("  DIFF", p[:400])
    print("FOUNDER RADAR GOLDENS MATCH" if not problems else f"FOUNDER RADAR GOLDENS DIFFER ({len(problems)})")
    return 1 if problems else 0


def summary(golden: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, s in golden["sets"].items():
        answers = []
        for st in s["expected"]:
            a = st.get("answer") or {}
            b: dict[str, Any] = a["body"] if isinstance(a.get("body"), dict) else {}
            answers.append(a.get("raises") or b.get("error") or a.get("code"))
        out[name] = {"steps": len(s["expected"]), "answers": answers}
    return out


# ------------------------------------------------------------------ the real snapshot, through the API routes
REAL_CLOCK = "2026-11-12T09:00:00"
REAL_LATER = "2026-11-19T09:00:00"
STRICT = ("radar_companies.json", "radar_research.json")  # json columns: compared with their key order


def real_steps(people_doc: Any, companies_doc: Any) -> list[dict[str, Any]]:
    """A full read; on the first two radar people: watch, public evidence, a state change, an unknown state (declared
    f), dismiss; a note on the first stored company; a full read a week later."""
    ids = [
        p["id"]
        for p in (people_doc or {}).get("people", [])
        if isinstance(p, dict) and p.get("provenance") != "user_provided"
    ]
    keys = list(((companies_doc or {}).get("companies") or {}).keys())
    p1, p2 = [*ids, "p-none", "p-none"][:2]
    steps: list[dict[str, Any]] = [
        {"op": "get"},
        {"op": "action", "body": {"id": p1, "action": "watch"}},
        {
            "op": "action",
            "body": {
                "id": p1,
                "action": "evidence",
                "kind": "technical",
                "url": "https://github.com/invented-parity-check",
                "label": "Parity check",
                "claim": "Public repository maintained",
                "activity_date": "2026-11-01",
            },
        },
        {"op": "action", "body": {"id": p1, "action": "state", "state": STATES[0], "note": "parity"}},
        {"op": "action", "body": {"id": p1, "action": "state", "state": "no-such-state"}, "declared": "f"},
        {"op": "action", "body": {"id": p2, "action": "dismiss", "note": "parity check"}},
        {"op": "action", "body": {"id": "p-never-existed", "action": "watch"}},
    ]
    if keys:
        steps.append({"op": "company", "body": {"key": keys[0], "notes": "Parity note"}})
    steps.append({"op": "get", "at": REAL_LATER})
    return steps


def _by_value(v: Any) -> Any:
    return json.loads(json.dumps(v, sort_keys=True))


def real() -> int:  # pragma: no cover - needs the hosted database and the old repository
    """The real snapshot imported by the production importer into a throw-away schema, through the API routes, against
    the OLD routes over a byte-exact copy at the same clock. Declared: (a), (b), (e), (f) as in the goldens, and the
    people records' key order (stored as JSONB by the Network store since review 013) - the people, the GET answers and
    the metrics are compared by value; the companies and research records strictly, key order included."""
    import secrets as _secrets

    from fastapi.testclient import TestClient
    from psycopg import sql as _sql

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.founder_radar.db import documents as _documents
    from projectzero.founder_radar.store import FounderRadarStore
    from projectzero.network.store import load_people
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot

    load_dotenv()
    settings = Settings.from_env()
    snapshot_ = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    files = {f.path: f.raw for f in snapshot_.files()}
    steps = real_steps(snapshot_.json("people.json", {}), snapshot_.json("radar_companies.json", {}))
    old = run_oracle({"clock": REAL_CLOCK, "steps": steps}, files)["steps"]
    signals = (snapshot_.json("real_data.json", {}) or {}).get("signals", [])
    schema = f"pz_rehearse_{_secrets.token_hex(4)}"
    problems: list[str] = []
    admin = connect(settings.db_url, autocommit=True)
    clock = [utc_instant(REAL_CLOCK)]
    try:
        admin.execute(_scratch_sql(schema).encode())
        conn = connect(settings.db_url)
        try:
            applied = apply_plan(build_plan(snapshot_), schema=schema, conn=conn)
            assert applied.get("applied"), applied
        finally:
            conn.close()

        def stored() -> dict[str, Any]:
            with transaction(settings.db_url) as c:
                store = FounderRadarStore(c, schema)
                return {"people.json": {"people": load_people(c, schema)}, "radar_companies.json": store.load_companies(),
                        "radar_research.json": store.load_research(),
                        "radar_metrics.json": _documents(c, schema)["metrics"]}  # fmt: skip

        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: clock[0]
        wall = REAL_CLOCK
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:

            def ans(r: Any) -> dict[str, Any]:
                return {"code": r.status_code, "body": r.json()}

            for i, (step, a) in enumerate(zip(steps, old, strict=True)):
                if step.get("at"):
                    wall = step["at"]
                    clock[0] = utc_instant(wall)
                if step["op"] == "get":
                    got = ans(client.get("/api/founder-radar"))
                    problems += [
                        f"/steps[{i}]/answer{p}" for p in diff({"x": _by_value(a["answer"])}, {"x": _by_value(got)})
                    ]
                    continue
                expected = (
                    DECLARED_F
                    if step.get("declared") == "f" and a.get("answer") == {"raises": "ValueError"}
                    else a["answer"]
                )
                got = ans(client.post(f"/api/founder-radar/{step['op']}", json=step["body"]))
                problems += [f"/steps[{i}]/answer{p}" for p in diff({"x": _by_value(expected)}, {"x": _by_value(got)})]
                view = ans(client.get("/api/founder-radar"))
                problems += [f"/steps[{i}]/view{p}" for p in diff({"x": _by_value(a["view"])}, {"x": _by_value(view)})]
                sb = stored()
                sa = {**a["stored"], "people.json": {"people": (a["stored"].get("people.json") or {}).get("people")}}
                for n in DOCS:
                    x, y = sa.get(n), sb.get(n)
                    if n == "radar_companies.json":
                        x = normalized_companies(x, sa.get("people.json"), signals, sa.get("radar_research.json"), wall)
                        y = normalized_companies(y, sb.get("people.json"), signals, sb.get("radar_research.json"), wall)
                    if n in STRICT and _key(x) != _key(y):
                        problems += [f"/steps[{i}]/stored/{n}{p}" for p in diff({"x": x}, {"x": y})] or [
                            f"/steps[{i}]/stored/{n}: key order differs"
                        ]
                    elif n not in STRICT:
                        problems += [
                            f"/steps[{i}]/stored/{n}{p}" for p in diff({"x": _by_value(x)}, {"x": _by_value(y)})
                        ]
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    report = {"steps": len(steps), "people": len((snapshot_.json("people.json", {}) or {}).get("people", [])),
              "differences": len(problems)}  # fmt: skip
    print(json.dumps(report, indent=2))
    for p in problems[:60]:
        print("  DIFF", p)
    print("FOUNDER RADAR PARITY PASSED" if not problems else "FOUNDER RADAR PARITY FAILED")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["real"]:
        return real()
    if argv[1:] == ["goldens"]:
        return write_goldens()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
