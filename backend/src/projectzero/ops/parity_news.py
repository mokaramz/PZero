# ruff: noqa: E501
# (the synthetic corpus: one record per line)
"""News parity: the pure port against the OLD code as oracle, with a FIXED clock and no write (review 028a).

    python -m projectzero.ops.parity_news goldens   # (re)generates golden_v1/oracle_news.json
    python -m projectzero.ops.parity_news check     # the stored golden against the new code (no oracle)

The oracle (``scripts/oracle/news_oracle.py``) runs the old ``services/news.py`` / ``services/news_sources.py`` over
a scratch data folder, route by route, each from the FRESH fixture: ``view`` (``GET /api/news``), ``weekly``
(``weekly_review``, ``record=False``), ``sources:<w>`` for ``30``, ``90``, ``180``, ``all`` and an unknown window
(``news_sources.view``), ``refresh_status``. The old GET-time seeding (``seed_cases`` -> ``_save``, then ``load``) is
intercepted IN MEMORY (the whole events-document save, read back by the old ``load``) and recorded as ``saved``;
every other write is blocked and the data folder is checked unchanged. The curated case folder is the set's own
(``CASES_KEY`` of the documents: invented cases; ``None``: a missing folder). The new side is the PURE port
(``news.inputs_from_docs`` -> ``news.view`` / ``weekly_review`` / ``sources_view`` / ``refresh_status``) over the same
documents; ``saved`` is ``news.seed_cases`` under the old guard. Every answer is compared value by value AND as
serialized text (key order), ``saved`` too, and the inputs are checked unchanged.

Declared differences, normalised here and nowhere else:

* (e) the Swiss ticker's technical row: the old one read ``health.source_health()`` (System health, not ported; the
  oracle answers no rows, so the old code took its own ``UNKNOWN`` fallback); the new row is that fallback plus
  ``reason`` (dropped here after checking it is ``HEALTH_REASON``);
* (s) ``unique.by_scope`` of every source row: a ``Counter`` over a SET of scopes, so its key order followed the old
  process's string hashing (``PYTHONHASHSEED``), not the data: its keys are sorted on both sides before the text
  comparison (the values are compared as they are).

The synthetic data folders hold INVENTED names only (the monitored publications are the old feed list's, a code
constant; the cited publications are the old recognition list's):

* ``main``: events of every type and materiality (HIGH / MEDIUM / LOW / NOISE, fund news, a US story), stories that
  are caught early, known but late (via the announcement itself, and below 14 days), missed (a known early signal in
  PZ's window), historical (a curated case), unknown with and without a possible miss, not relevant; ties on date and
  materiality decided by the archive key order; a story that cannot be read (skipped) and one without
  ``entity_key``; a theme group; disagreements (open, resolved by majority, resolved by a primary source, agreeing);
  syndicated copies, press releases, digests, citations of unmonitored publications, external publishers; 18
  benchmark events over 150 days with earlier mentions (sourcing earliness); more than 60 stories; Validation
  entities that tie (inbox, proposals, decisions; a Deal Flow ticker source for the source-alpha row); the curated
  cases: one seeded case updated from its file while KEEPING the operator-added signal, one new case (the legacy
  count guard lets them seed); actions where the last line per event wins (outcome decisions, miss audits, a backcast
  line, junk); runs with and without status (ok, partial, failed, interrupted, none) and per-feed failures (failing,
  blocked, degraded); a disagreement log; a source-metrics cache with four windows (story notes, external notes);
  the source state (a degraded source), extra feeds (probation, disabled), source-network candidates; live outcomes.
* ``guard``: ``seeded`` lists a case whose file is gone: one id for one file, so the legacy guard
  (``len(seeded) < len(files)``) does NOT seed the shipped case (kept).
* ``noop``: the guard lets the cases seed, but the stored curated case equals its file: nothing is added, nothing
  saved.
* ``nocases``: the case folder is missing.
* ``badcase``: a case file that is not JSON: the seeding raises (the old 500) on the views that seed.
* ``broken``: tolerance: the metric cache is a list (every story's source note raises: each story is skipped), a
  run line that is a JSON list (the sources view raises), junk lines.
* ``torn``: the events document is a list (every route raises where the old one did).
* ``empty``: no documents and an empty case folder.

Exit 1 on any difference.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT
from projectzero.dealflow.ranking.names import norm_company
from projectzero.news import inputs_from_docs, refresh_status, seed_cases, sources_view, view, weekly_review
from projectzero.news.core import load
from projectzero.news.inputs_model import CASES_KEY
from projectzero.news.sources import HEALTH_REASON
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js

ORACLE = REPO_ROOT / "scripts" / "oracle" / "news_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_news.json"
CLOCK = "2026-11-12T10:00:00"
WINDOWS = ("30", "90", "180", "all", "7")  # "7": anything else is 90 (decision d)
ROUTES = ["view", "weekly", *(f"sources:{w}" for w in WINDOWS), "refresh_status"]
TODAY = date(2026, 11, 12)


# ------------------------------------------------------------------ the synthetic data folders (invented names only)
# fmt: off
def jl(rows: list[Any]) -> str:
    """A JSONL log as the old writers wrote it (``sort_keys``); a ``str`` row is a raw line, kept as is."""
    return "".join(
        (r if isinstance(r, str) else json.dumps(r, ensure_ascii=False, sort_keys=True)) + "\n" for r in rows
    )


def day(n: int) -> str:
    """The date ``n`` days before the clock's day."""
    return (TODAY - timedelta(days=n)).isoformat()


def key(name: str) -> str:
    return norm_company(name) or ""


def src(pub: str, slug: str, published: str, headline: str, ind: str = "independent", ts: str = "", host: str = "") -> dict[str, Any]:
    s = {"publisher": pub, "url": f"https://{host or 'news.invented.example'}/{slug}", "published": published,
         "headline": headline, "text_sha": f"sha-{slug}", "independence": ind}
    if ts:
        s["published_ts"] = ts
    return s


def ev(eid: str, company: str, headline: str, etype: str, when: str, mat: str, *, geo: list[str] | None = None,
       themes: list[str] | None = None, rnd: str = "", amount: float | None = None, noise: bool = False,
       sources: list[dict[str, Any]] | None = None, summary: str | None = "", backcast: list[Any] | None = None,
       why: str = "rule", **kw: Any) -> dict[str, Any]:
    return {"event_id": eid, "company": company, "entity_key": key(company) if company else "",
            "company_from": "headline" if company else "", "headline": headline, "summary": summary,
            "event_type": etype, "round": rnd, "amount_m": amount, "event_date": when,
            "geo": ["DE"] if geo is None else geo, "themes": ["robotics"] if themes is None else themes, "noise": noise,
            "sources": sources if sources is not None else [src("Sifted", eid, when, headline)],
            "ingested_at": f"{when}T08:00:00", "backcast": backcast or [], "card": None, **kw,
            "materiality": mat, "materiality_why": [why]}


def sig(when: str, kind: str, family: str, text: str, **kw: Any) -> dict[str, Any]:
    precision = {4: "year", 7: "month"}.get(len(when), "day")
    return {"date": when, "precision": precision, "text": text, "family": family,
            "url": f"https://evidence.invented.example/{family}/{when}", "kind": kind, **kw}


def cand(cid: str, name: str, source: str, tier: str, seen: str, decision: str = "new", **kw: Any) -> dict[str, Any]:
    return {"id": cid, "name": name, "source_id": source, "source": source, "discovery_tier": tier,
            "first_seen": seen, "decision": decision, "country": "DE", **kw}


GRANITE = "Invented Granite Robotics"
BASIN = "Invented Basin Photonics"


def case_a(updated: bool) -> dict[str, Any]:
    """The curated case already seeded in ``main``; its file carries an updated precursor list and backcast."""
    signals = [sig("2023", "known_early_signal", "university_lab", "Invented chair spinout announced"),
               sig("2024-05", "in_retrospect", "early_funding", "Invented pre-seed round")]
    if updated:
        signals.append(sig("2025-02", "known_early_signal", "accelerator", "Invented programme cohort"))
    return {"event_id": "nw-case-a", "curated": True, "company": GRANITE, "company_from": "curated case",
            "headline": f"{GRANITE} passes a $1.1 billion valuation", "summary": "A secondary sale set the price.",
            "event_type": "valuation", "round": "", "amount_m": 1100, "event_date": day(41), "geo": ["DE"],
            "themes": ["robotics", "ai"], "noise": False,
            "sources": [src("Reuters (via Invented Star)", "case-a-1", day(41), f"{GRANITE} hits $1.1 billion valuation", host="star.invented.example"),
                        src("Sifted", "case-a-2", day(40), f"{GRANITE} valued at $1.1bn")],
            "card": {"what_happened": "Curated.", "why_it_matters": "Benchmark.", "the_company": "", "vc_lesson": "",
                     "watch_next": [], "generated_by": "curated"},
            "backcast": signals, "learning": "",
            "precursor_sources": [{"url": "https://lab.invented.example/news/", "name": "Invented lab news",
                                   "family": "university_lab", "signal_date": "2023" if updated else "2022"}]}


def case_b() -> dict[str, Any]:
    return {"event_id": "nw-case-b", "curated": True, "company": BASIN, "company_from": "curated case",
            "headline": f"{BASIN} raises a $60M Series C", "summary": "Research spinout from an invented institute.",
            "event_type": "funding", "round": "series c", "amount_m": 60, "event_date": day(44), "geo": ["CH"],
            "themes": ["deeptech"], "noise": False,
            "sources": [src("Invented Alpine Herald", "case-b-1", day(44), f"{BASIN} raises $60M", host="herald.invented.example")],
            "backcast": [sig("2021", "known_early_signal", "research_paper", "Invented paper on photonic chips"),
                         sig("2022-03", "known_early_signal", "grant", "Invented national grant")],
            "learning": "The earliest edge was a paper years before Project Zero started."}


def case_text(case: dict[str, Any]) -> str:
    return json.dumps(case, ensure_ascii=False, indent=2) + "\n"


def stored_case_a() -> dict[str, Any]:
    """As the old seeding stored it earlier (the old file's version), plus Mohamed's own signal (``added_by``)."""
    c = case_a(updated=False)
    c["ingested_at"] = "2026-10-01T09:00:00"
    c["backcast"] = [*c["backcast"], sig(day(43), "known_early_signal", "accelerator", "Invented demo day pitch", added_by="mohamed", added_at="2026-11-01T09:00:00")]
    c["entity_key"] = key(GRANITE)
    c["materiality"], c["materiality_why"] = "HIGH", ["valuation milestone"]
    return c


FEED_NAMES = ("Sifted", "Tech.eu", "EU-Startups", "Silicon Canals", "Startbase", "deutsche-startups.de", "Munich Startup", "Maddyness", "UKTN", "ArcticStartup")


def bench_events() -> list[dict[str, Any]]:
    """18 benchmark events over 150 days, most reported by two or three monitored sources (overlap), earlier mentions
    by Munich Startup (sourcing earliness), citations and an external publisher."""
    out: list[dict[str, Any]] = []
    for i in range(18):
        company = f"Invented Bench Co {i}"
        when = day(3 + i * 9)
        h = f"{company} raises €{3 + i % 4}M seed round" + (" in Munich" if i % 3 == 0 else "")
        srcs = [src("Sifted", f"b{i}-s", when, h, ts=f"{when}T0{i % 9}:30" if i % 2 else "")]
        if i % 4 != 3:
            srcs.append(src("Munich Startup" if i % 3 == 0 else "Tech.eu", f"b{i}-m", when, h + (" (Handelsblatt)" if i == 4 else ""), ts=f"{when}T11:15" if i % 2 else ""))
        if i % 5 == 0:
            srcs.append(src("startupticker.ch", f"b{i}-t", day(2 + i * 9), f"{company} sichert sich {3 + i % 4} Millionen Franken", host="www.startupticker.ch"))
        if i in (2, 7, 11):
            srcs.append(src("Invented Herald", f"b{i}-h", when, f"According to Invented sources {company} raised", host="herald.invented.example"))
        if i == 6:
            srcs.append(src("EU-Startups", f"b{i}-e", when, h, ind="syndicated"))
        if i == 9:
            srcs = [src("EU-Startups", f"b{i}-e", when, f"Press release: {company} announced today a seed round")]
        out.append(ev(f"nw-bench-{i:02d}", company, h, "funding", when, "MEDIUM", geo=["DE"] if i % 3 else ["DE", "EU"],
                      themes=["ai"] if i % 2 else ["robotics", "deeptech"], rnd="seed", amount=float(3 + i % 4), sources=srcs,
                      summary=("according to Reuters, the round closed. " if i == 5 else "") + "An invented seed round."))
        if i % 3 == 0:  # an earlier mention: the company appeared in Munich Startup >= 14 days before its round
            out.append(ev(f"nw-bench-{i:02d}-early", company, f"{company} opens a lab in Munich", "expansion", day(3 + i * 9 + 20), "LOW",
                          sources=[src("Munich Startup", f"b{i}-early", day(3 + i * 9 + 20), f"{company} opens a lab in Munich")]))
    return out


def main_events() -> dict[str, Any]:
    events = [
        ev("nw-early", "Invented Kestrel Robotics", "Invented Kestrel Robotics raises €4M seed round led by Invented Partners", "funding", day(2), "MEDIUM",
           rnd="seed", amount=4.0, summary="The Munich team builds robot arms for small factories.",
           sources=[src("Sifted", "early-s", day(2), "Invented Kestrel Robotics raises €4M seed round", ts=f"{day(2)}T06:00"),
                    src("Tech.eu", "early-t", day(2), "Invented Kestrel Robotics secures €5M seed", ts=f"{day(2)}T09:30"),
                    src("EU-Startups", "early-e", day(1), "Invented Kestrel Robotics bags €4.2M seed")]),
        ev("nw-acq", "Invented Lumen Grid", "Invented Volt Holdings acquires Invented Lumen Grid", "acquisition", day(7), "HIGH",
           themes=["industrial", "climate"], why="acquisition",
           sources=[src("Munich Startup", "acq-m", day(7), "Invented Lumen Grid bought for $30M"),
                    src("startupticker.ch", "acq-t", day(7), "Invented Lumen Grid acquired for $30M", ind="primary", host="www.startupticker.ch"),
                    src("Sifted", "acq-s", day(6), "Invented Volt Holdings buys Invented Lumen Grid for $45M")]),
        ev("nw-late", "Invented Harbor Labs", "Invented Harbor Labs raises $25M Series B", "funding", day(4), "HIGH", geo=["UK"], themes=["ai"],
           rnd="series b", amount=25.0, why="large round (25M)",
           sources=[src("UKTN", "late-u", day(4), "Invented Harbor Labs raises $25M Series B"),
                    src("Tech.eu", "late-t", day(4), "Invented Harbor Labs raises $25M Series B", ind="syndicated")]),
        ev("nw-late2", "Invented Fjord Motion", "Invented Fjord Motion lands €2M", "funding", day(4), "MEDIUM", geo=["NORDICS"],
           amount=2.0, sources=[src("ArcticStartup", "late2", day(4), "Invented Fjord Motion lands €2M"),
                                src("Tech.eu", "late2-t", day(3), "Invented Fjord Motion raises €3M")]),  # an OPEN disagreement
        ev("nw-pre", "Invented Tiecoast Energy", "Invented Tiecoast Energy wins a framework agreement", "customer", day(33), "MEDIUM", themes=["industrial"]),
        ev("nw-miss", "Invented Quarry Bio", "Invented Quarry Bio raises €30M Series A", "funding", day(9), "HIGH", geo=["FR"], themes=["deeptech"],
           rnd="series a", amount=30.0, sources=[src("Maddyness", "miss", day(9), "Invented Quarry Bio lève 30 millions d'euros")],
           backcast=[sig(day(42), "known_early_signal", "grant", "Invented national grant listed the team"),
                     sig("2026-09", "in_retrospect", "university_lab", "Invented lab news"),
                     sig("2025", "known_early_signal", "accelerator", "Invented accelerator cohort")]),
        ev("nw-tie-z", "Invented Zephyr Drones", "Invented Zephyr Drones raises €3M seed", "funding", day(3), "MEDIUM", rnd="seed", amount=3.0),
        ev("nw-tie-b", "Invented Beacon Automation", "Invented Beacon Automation raises €3M seed", "funding", day(3), "MEDIUM", rnd="seed", amount=3.0),
        ev("nw-rob5", "Invented Gantry Humanoids", "Invented Gantry Humanoids secures €6M", "funding", day(12), "MEDIUM", amount=6.0),
        ev("nw-unk", "Invented Ostrich AI", "Invented Ostrich AI signs a deal with an invented carmaker", "customer", day(3), "MEDIUM", themes=["ai"]),
        ev("nw-unk2", "", "Invented grant round for climate teams announced", "grant", day(5), "LOW", geo=["EU"], themes=["climate"]),
        ev("nw-fund", "Invented Basalt Ventures", "Invented Basalt Ventures closes €80M Fund II", "fund", day(6), "LOW", themes=["deeptech"], amount=80.0),
        ev("nw-us", "Invented Prairie Cloud", "Invented Prairie Cloud raises $12M", "funding", day(8), "MEDIUM", geo=["US"], themes=["enterprise"], amount=12.0),
        ev("nw-noise", "", "Top 10 startups to watch this week", "other", day(1), "NOISE", noise=True, why="opinion / listicle / event / newsletter format"),
        ev("nw-val", "Invented Summit Robotics", "Invented Summit Robotics hits $1.2 billion valuation", "valuation", day(15), "HIGH", themes=["robotics", "ai"],
           summary="A secondary sale by early employees set the price; the company plans US expansion.", amount=1200.0),
        ev("nw-shut", "Invented Cinder Mobility", "Invented Cinder Mobility shuts down", "shutdown", day(23), "HIGH", geo=["FR"], themes=["industrial"]),
        ev("nw-reg", "Invented Helix Med", "Invented Helix Med receives CE mark approval", "regulatory", day(18), "MEDIUM", geo=["CH"], themes=["deeptech"]),
        ev("nw-acc", "Invented Pebble Labs", "Invented Pebble Labs joins an invented accelerator cohort", "accelerator", day(28), "LOW", themes=["ai"]),
        ev("nw-part", "Invented Copper Systems", "Invented Copper Systems partners with an invented utility", "partnership", day(26), "LOW", themes=["enterprise"]),
        ev("nw-founder", "", "Invented co-founder leaves to start a new startup", "founder", day(20), "MEDIUM", geo=["UK"], themes=["ai"]),
        ev("nw-launch", "Invented Lantern Robotics", "Invented Lantern Robotics launches a picking robot", "launch", day(21), "LOW"),
        ev("nw-exp", "Invented Meadow Health", "Invented Meadow Health expands to the US market", "expansion", day(22), "LOW", themes=[]),
        ev("nw-hire", "Invented Orbit Freight", "Invented Orbit Freight appoints a new CTO", "hire", day(24), "LOW", themes=["industrial"]),
        ev("nw-manual", "", "An invented story added by hand", "manual", day(25), "LOW", themes=[]),
        ev("nw-ledger", "Invented Tidal Robotics", "Invented Tidal Robotics raises €1.5M", "funding", day(10), "MEDIUM", amount=1.5,
           sources=[src("Invented Ledger", "ledger", day(10), "Invented Tidal Robotics raises €1.5M", host="ledger.invented.example")]),
        ev("nw-bad", "Invented Broken Story", "Invented Broken Story raises €2M", "funding", day(11), "MEDIUM", amount=2.0, summary=None),  # cannot be read: skipped
        ev("nw-wiki", "Invented Ochre Labs", "Invented Ochre Labs raises €2M (Handelsblatt)", "funding", day(13), "MEDIUM", amount=2.0,
           sources=[src("Startbase", "wiki", day(13), "Invented Ochre Labs raises €2M, according to Handelsblatt"),
                    src("deutsche-startups.de", "wiki-2", day(13), "#DealMonitor Invented Ochre Labs erhält 2 Millionen Euro")]),
        stored_case_a(),
        *bench_events(),
        *(ev(f"nw-fill-{i:02d}", f"Invented Filler Co {i}", f"Invented Filler Co {i} updates its website", "other", day(30 + i * 3), "LOW", geo=["US"], themes=[])
          for i in range(40)),
    ]
    bad = ev("nw-nokey", "Invented Keyless Co", "Invented Keyless Co raises €2M", "funding", day(14), "MEDIUM", amount=2.0)
    del bad["entity_key"]  # an event without an entity key: unreadable for the check, skipped
    events.insert(12, bad)
    return {"events": {e["event_id"]: e for e in events}, "seeded": ["nw-case-a"]}


def runs() -> str:
    rows: list[Any] = []
    for i in range(9):
        at = f"{day(54 - i * 6)}T07:00:00"
        per = {name: {"ok": True, "items": 20, "seconds": 1.0, "latest": day(54 - i * 6)} for name in FEED_NAMES if name != "Silicon Canals"}
        failed = []
        if i >= 6:
            per["Tech.eu"] = {"ok": False, "error": "URLError: timed out", "http": None, "rate_limited": False, "seconds": 20.0}
            failed.append("Tech.eu: URLError: timed out")
        if i == 8:
            per["Sifted"] = {"ok": False, "error": "HTTPError: HTTP Error 403: Forbidden", "http": 403, "rate_limited": False, "seconds": 1.0}
            per["UKTN"] = {"ok": False, "error": "HTTPError: HTTP Error 500: Server Error", "http": 500, "rate_limited": False, "seconds": 1.0}
            failed += ["Sifted: HTTPError: HTTP Error 403: Forbidden", "UKTN: HTTPError: HTTP Error 500: Server Error"]
        per["startupticker.ch"] = {"ok": True, "items": 3, "reused": "Deal Flow scan (no fetch)"}
        row: dict[str, Any] = {"run_id": f"news-{i}", "at": at, "started_at": at, "trigger": "scheduled", "per_feed": per,
                               "sources_ok": 10 - len(failed), "sources_failed": failed, "items": 200, "new": i, "merged": 1}
        if i == 0:
            row = {"run_id": "news-old", "at": at, "trigger": None, "sources_ok": 9, "sources_failed": ["Silicon Canals: URLError: boom"], "items": 150}
        elif i in (1, 2):
            row["sources_failed"] = [*failed, "Silicon Canals: URLError: boom"]
        if i == 4:
            row["status"] = "ok"
        elif i in (5, 6, 7):
            row["status"] = "partial"
        elif i == 8:
            row["status"] = "failed"
        rows.append(row)
    rows.insert(3, {"run_id": "news-x", "at": f"{day(40)}T07:00:00", "status": "interrupted", "sources_ok": 0, "sources_failed": [], "items": 0})
    rows.insert(5, "not json")
    return jl(rows)


def actions() -> str:
    return jl([
        {"kind": "outcome_decision", "event_id": "nw-acq", "decision": "reject", "at": "2026-11-08T09:00:00"},
        {"kind": "outcome_decision", "event_id": "nw-acq", "decision": "confirm", "at": "2026-11-09T09:00:00", "outcome_id": "oc-acq"},
        {"kind": "outcome_decision", "event_id": "nw-late", "decision": "not_enough", "at": "2026-11-09T10:00:00"},
        {"kind": "miss_audit", "event_id": "nw-miss", "audit_id": "au-first", "at": "2026-11-10T09:00:00"},
        "garbage",
        {"kind": "miss_audit", "event_id": "nw-miss", "audit_id": "au-second", "at": "2026-11-11T09:00:00"},
        {"kind": "backcast_signal", "event_id": "nw-miss", "signal": sig("2026-10", "known_early_signal", "grant", "added")},
        "[1, 2]",
    ])


def metrics_window(n: int) -> dict[str, Any]:
    return {"benchmark_events": n, "sources": {
        "Sifted": {"name": "Sifted", "kind": "feed", "roles": [{"role": "CORE EUROPEAN INTELLIGENCE", "basis": "observed", "evidence": "covered 12/15 material European events reported elsewhere"}],
                   "authority": {"prior": "SPECIALIST MEDIA"}},
        "Munich Startup": {"name": "Munich Startup", "kind": "feed", "roles": [{"role": "EARLY SIGNAL", "basis": "observed", "evidence": "mentioned 4 companies ≥ 14 days before their material event (median 20 days)"},
                                                                              {"role": "ECOSYSTEM SENSOR", "basis": "observed", "evidence": "3 material Munich event(s) no other source had"}],
                           "authority": {"prior": "SPECIALIST MEDIA"}},
        "EU-Startups": {"name": "EU-Startups", "kind": "feed", "roles": [{"role": "SECONDARY COVERAGE", "basis": "observed", "evidence": "syndicated 9/16 · unique 0 of 15 covered events"}],
                        "authority": {"prior": "SPECIALIST MEDIA"}},
        "Tech.eu": {"name": "Tech.eu", "kind": "feed", "roles": [], "authority": {"prior": "SPECIALIST MEDIA"}},
        "Reuters (via Invented Star)": {"name": "Reuters (via Invented Star)", "kind": "external", "roles": [{"role": "CONFIRMATION / AUTHORITY", "basis": "prior", "evidence": "external"}],
                                        "authority": {"prior": "HIGH-QUALITY INDEPENDENT MEDIA"}},
    }}


def main_docs() -> dict[str, Any]:
    ticker = "s-ticker"
    inbox = [
        cand("k1", "Invented Kestrel Robotics GmbH", "s-lab", "pre_company", day(42), decision="kept"),
        cand("k2", "Invented Lumen Grid", ticker, "grant", day(33)),
        cand("k3", "Invented Harbor Labs", "s-wire", "announcement", day(6)),
        cand("k4", "Invented Fjord Motion", ticker, "pre_company", day(11), decision="watch"),
        cand("k5", "Invented Tiecoast Energy", "s-lab", "pre_company", day(23)),
        cand("k6", "Invented Zephyr Drones", ticker, "pre_company", day(30)),
        cand("k7", "Invented Beacon Automation", ticker, "pre_company", day(30)),
        cand("k8", "Invented Ticker Only", ticker, "announcement", day(5)),
    ]
    proposals = {"k1": {"status": "proposed", "proposal": "KEEP", "capital_stage": "PRE_COMPANY", "themes": ["Robotics"]},
                 "k6": {"status": "needs_human", "proposal": "RESEARCH", "capital_stage": "ROUND_FORMING", "themes": ["robotics", "AI"]},
                 "k7": {"status": "proposed", "proposal": "REJECT", "capital_stage": None, "themes": ["robotics"]}}
    decisions = jl([{"candidate_id": "k1", "machine": "KEEP", "verdict": "KEEP", "agreed": True, "ts": "2026-10-02T09:00:00"},
                    {"candidate_id": "k6", "machine": "RESEARCH", "verdict": "REJECT", "agreed": False, "ts": "2026-10-14T09:00:00"}])
    outcomes = jl([
        {"id": "oc-1", "company": "Invented Bench Co 3", "entity_key": key("Invented Bench Co 3"), "kind": "institutional_round", "event_date": day(32)},
        {"id": "oc-2", "company": "Invented Bench Co 12", "entity_key": key("Invented Bench Co 12"), "kind": "institutional_round", "event_date": day(110)},
        {"id": "oc-3", "company": "Invented Kestrel Robotics", "entity_key": key("Invented Kestrel Robotics"), "kind": "institutional_round", "event_date": day(2)},
        {"id": "rx-1", "retracts": "oc-3", "reason": "duplicate"},
        {"id": "oc-4", "company": "Invented No Key", "kind": "accelerator", "event_date": day(5)},
    ])
    return {
        "sources.json": {"sources": [{"id": "s-lab", "name": "Invented Lab Transfer"}, {"id": ticker, "name": "startupticker.ch"},
                                     {"id": "s-wire", "name": "Invented City Wire"}]},
        "inbox.json": {"candidates": inbox},
        "triage_proposals.json": {"proposals": proposals},
        "triage_decisions.jsonl": decisions,
        "news/events.json": main_events(),
        "news/actions.jsonl": actions(),
        "news/runs.jsonl": runs(),
        "news/disagreements.jsonl": jl([{"at": "2026-11-01T10:00:00", "event_id": "nw-early", "field": "amount_m", "status": "OPEN", "values": {"Sifted": 4.0, "Tech.eu": 5.0}}]),
        "news/source_log.jsonl": jl([{"at": "2026-11-01T10:00:00", "event": "degraded", "source": "Silicon Canals", "why": ["editorial drift"]}]),
        "news/source_metrics.json": {"at": "2026-11-11T16:05:00", "today": day(1),
                                     "windows": {"30": metrics_window(6), "90": metrics_window(14), "180": metrics_window(20), "all": metrics_window(22)}},
        "news/source_state.json": {"Silicon Canals": {"state": "DEGRADED", "since": "2026-11-01T10:00:00", "reasons": ["editorial drift: relevance fell from 40% to 10% of articles"], "history": []},
                                   "Sifted": {"state": "ACTIVE", "since": "2026-09-20T10:00:00", "reasons": [], "history": []},
                                   "UKTN": {"state": "DEGRADED", "since": "2026-11-02T10:00:00", "history": []}},
        "news/feeds_extra.json": {"feeds": [
            {"name": "Invented Ledger", "feed_url": "https://ledger.invented.example/feed", "site_url": "https://ledger.invented.example/", "geo": "DE", "state": "PROBATION", "enabled": True},
            {"name": "Invented Quill", "feed_url": "https://quill.invented.example/rss", "state": "TRUSTED", "enabled": False}]},
        "scan_history.json": {"scans": [{"run_id": "2026-10-01T08-00-00"}, {"run_id": "2026-09-20T08-00-00"}, {"sources": []}]},
        "sources/network.json": {"candidates": {
            "src-ledger": {"id": "src-ledger", "name": "Invented Ledger", "url": "https://ledger.invented.example/", "state": "PROBATION", "family": "news_publication"},
            "src-lab": {"id": "src-lab", "name": "Invented Lab", "url": "https://lab.invented.example/", "state": "REJECTED", "family": "university_lab"}}},
        "validation/outcomes.jsonl": outcomes,
        CASES_KEY: {"case-b.json": case_text(case_b()), "case-a.json": case_text(case_a(updated=True))},
    }


def guard_docs() -> dict[str, Any]:
    c = case_b()
    return {
        "news/events.json": {"events": {"nw-g": ev("nw-g", "Invented Garnet Robotics", "Invented Garnet Robotics raises €2M", "funding", day(3), "MEDIUM", amount=2.0)},
                             "seeded": ["nw-case-gone"]},  # the case file of this id is no longer shipped
        CASES_KEY: {"case-b.json": case_text(c)},
    }


def noop_docs() -> dict[str, Any]:
    c = case_b()
    stored = {**c, "ingested_at": "2026-10-01T09:00:00", "card": None, "entity_key": key(BASIN), "materiality": "HIGH",
              "materiality_why": ["large round (60M)"]}
    return {"news/events.json": {"events": {c["event_id"]: stored}, "seeded": []}, CASES_KEY: {"case-b.json": case_text(c)},
            "news/runs.jsonl": jl([{"run_id": "news-1", "at": f"{day(2)}T07:00:00"}])}


def nocases_docs() -> dict[str, Any]:
    return {"news/events.json": {"events": {"nw-n": ev("nw-n", "Invented Nickel Labs", "Invented Nickel Labs raises €2M", "funding", day(3), "MEDIUM", amount=2.0)}},
            "news/runs.jsonl": jl([{"run_id": "news-1", "at": f"{day(2)}T07:00:00", "status": "partial"}, {"run_id": "news-2", "at": f"{day(1)}T07:00:00", "status": "interrupted"}]),
            CASES_KEY: None}


def badcase_docs() -> dict[str, Any]:
    return {"news/events.json": {"events": {}, "seeded": []}, CASES_KEY: {"case-x.json": "{not json\n"}}


def broken_docs() -> dict[str, Any]:
    return {
        "news/events.json": {"events": {"nw-k": ev("nw-k", "Invented Kiln Co", "Invented Kiln Co raises €2M", "funding", day(3), "MEDIUM", amount=2.0)}, "seeded": []},
        "news/source_metrics.json": ["not", "a", "cache"],
        "news/runs.jsonl": "junk\n" + jl([[1, 2], {"run_id": "news-1", "at": f"{day(2)}T07:00:00", "status": "ok"}]),
        "news/actions.jsonl": "\n{\n" + jl([{"kind": "miss_audit", "event_id": "nw-k"}]),
        "news/feeds_extra.json": {"feeds": None},
        CASES_KEY: {},
    }


def torn_docs() -> dict[str, Any]:
    return {"news/events.json": [1], "news/runs.jsonl": jl([{"run_id": "news-1"}]), CASES_KEY: {}}


SETS: dict[str, Any] = {"main": main_docs, "guard": guard_docs, "noop": noop_docs, "nocases": nocases_docs,
                        "badcase": badcase_docs, "broken": broken_docs, "torn": torn_docs, "empty": lambda: {CASES_KEY: {}}}
# fmt: on


# ------------------------------------------------------------------ the oracle (shared with the Validation parity)
def split_cases(docs: dict[str, Any]) -> tuple[dict[str, bytes], Any]:
    """The data-folder files of ``docs`` and the curated case folder (``{name: text}``, ``None`` missing, or the
    ``MISSING`` default: the old folder is left as is)."""
    files: dict[str, bytes] = {}
    for k, v in docs.items():
        if k == CASES_KEY:
            continue
        files[k] = (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=2)).encode("utf-8")
    return files, docs.get(CASES_KEY, ...)


def scratch_oracle(
    script: Path, inp: dict[str, Any], files: dict[str, bytes], cases: Any = ..., prefix: str = "pz-news-oracle-"
) -> dict[str, Any]:
    """Run an OLD-code oracle over a scratch data folder holding ``files``; ``cases``: the curated case folder the
    oracle installs as the old ``SEED_CASES`` (``inp["cases_dir"]``)."""
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        data = Path(tmp) / "data"
        data.mkdir(parents=True)
        for rel, raw in files.items():
            target = (data / rel).resolve()
            if data.resolve() not in target.parents:
                raise SystemExit(f"refusing a path outside the scratch folder: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        cases_dir = Path(tmp) / "cases"
        if cases is ...:
            inp = {**inp, "cases_dir": None}
        else:
            if cases is not None:
                cases_dir.mkdir()
                for name, text in cases.items():
                    (cases_dir / name).write_bytes(text.encode("utf-8"))
            inp = {**inp, "cases_dir": str(cases_dir)}
        srcf, dst = Path(tmp) / "io" / "in.json", Path(tmp) / "io" / "out.json"
        srcf.parent.mkdir(parents=True, exist_ok=True)
        srcf.write_text(json.dumps(inp, ensure_ascii=False), encoding="utf-8")
        env = {**os.environ, "PZ_DATA": str(data), "PZ_TESTING": "1", "PZ_CASE_PREP": "0",
               "PYTHONPATH": str(OLD_REPO / "backend" / "src")}  # fmt: skip
        for k in [k for k in env if k == "SUPABASE_DB_URL" or k.endswith("_API_KEY") or k.endswith("_TOKEN")]:
            env.pop(k)  # the oracle never needs, and never sees, the database or any key
        run = subprocess.run([str(python), str(script), str(srcf), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_text(encoding="utf-8"))
        return out


def run_oracle(docs: dict[str, Any]) -> dict[str, Any]:
    files, cases = split_cases(docs)
    return scratch_oracle(ORACLE, {"clock": CLOCK, "routes": ROUTES}, files, cases)


# ------------------------------------------------------------------ the new side and the declared normalisation
def _answer(fn: Any) -> dict[str, Any]:
    try:
        body = fn()
    except Exception as exc:  # the old route would have answered 500
        return {"raises": type(exc).__name__}
    return {"code": 200, "body": js(body)}


def _saved(inputs: Any, now: datetime) -> Any:
    """What the old GET's seeding saved (the old view's guard, then ``seed_cases``), or ``None``."""
    try:
        if inputs.cases is not None and len(load(inputs.events)["seeded"]) < len(inputs.cases):
            doc, added = seed_cases(inputs.events, inputs.cases, now)
            return js(doc) if added else None
    except Exception:
        return None
    return None


def new_side(docs: dict[str, Any], clock: str) -> tuple[dict[str, Any], list[str]]:
    now = datetime.fromisoformat(clock)
    today = now.date()
    docs_before = copy.deepcopy(docs)
    inputs = inputs_from_docs(docs, today)
    inputs_before = copy.deepcopy(inputs)
    calls: dict[str, Any] = {
        "view": lambda: view(inputs, today, now),
        "weekly": lambda: weekly_review(inputs, today, now),
        "refresh_status": lambda: refresh_status(inputs),
    }
    routes: dict[str, Any] = {}
    seeded = _saved(inputs, now)
    for route in ROUTES:
        if route.startswith("sources:"):
            window = route.split(":", 1)[1]
            ans = _answer(lambda w=window: sources_view(inputs, w, today))
        else:
            ans = _answer(calls[route])
        routes[route] = {**ans, "saved": seeded if route in ("view", "weekly") else None}
    problems: list[str] = []
    if inputs != inputs_before:
        problems.append("/inputs: News changed its inputs")
    if docs != docs_before:
        problems.append("/docs: inputs_from_docs changed the documents")
    return routes, problems


def normalise(routes: dict[str, Any], problems: list[str], side: str) -> dict[str, Any]:
    """Declared (e) on the new side and (s) on both: see the header."""
    out = copy.deepcopy(routes)
    for route, ans in out.items():
        body = ans.get("body")
        if not route.startswith("sources:") or not isinstance(body, dict):
            continue
        for row in body.get("sources") or []:
            tech = row.get("technical") or {}
            if side == "new" and row.get("kind") == "deal_flow_reuse":
                if tech.get("reason") != HEALTH_REASON:
                    problems.append(f"/{route}/{row.get('name')}: the Swiss technical row has no deferral reason")
                tech.pop("reason", None)
            unique = row.get("unique") or {}
            if isinstance(unique.get("by_scope"), dict):
                unique["by_scope"] = dict(sorted(unique["by_scope"].items()))
    return out


def _text(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def compare_set(name: str, s: dict[str, Any], clock: str) -> list[str]:
    expected = s["expected"]
    problems: list[str] = []
    if expected.get("changed"):
        problems.append(f"/{name}/changed: the OLD read changed {expected['changed']}")
    got, invariants = new_side(s["docs"], clock)
    problems += [f"/{name}{p}" for p in invariants]
    old = normalise(expected["routes"], problems, "old")
    new = normalise(got, problems, "new")
    for route in ROUTES:
        problems += [f"/{name}/{route}{p}" for p in diff(js(old[route]), js(new[route]))]
        if _text(old[route]) != _text(new[route]):
            problems.append(f"/{name}/{route}: the serialized answer differs (key order)")
    return problems


def compare_goldens(golden: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for name, s in golden["sets"].items():
        problems += compare_set(name, s, golden["clock"])
    return problems


def summary(golden: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, s in golden["sets"].items():
        r = s["expected"]["routes"]
        v = r["view"].get("body") or {}
        out[name] = {
            "view": v.get("counts", r["view"].get("raises")),
            "stories": len(v.get("stories") or []),
            "misses": len(v.get("misses") or []),
            "themes": len(v.get("themes") or []),
            "saved": r["view"]["saved"] is not None,
            "weekly": (r["weekly"].get("body") or {}).get("top", r["weekly"].get("raises")) and "ok",
            "sources": {
                w: (r[f"sources:{w}"].get("body") or {}).get("benchmark_events", r[f"sources:{w}"].get("raises"))
                for w in WINDOWS
            },
            "refresh_status": "ok" if "body" in r["refresh_status"] else r["refresh_status"].get("raises"),
            "changed": s["expected"]["changed"],
        }
    return out


def write_goldens() -> int:
    sets: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    for name, fn in SETS.items():
        docs = fn()
        oracle = run_oracle(docs)
        meta = oracle.pop("meta")
        sets[name] = {"docs": docs, "expected": oracle}
    golden = {"provenance": meta, "clock": CLOCK, "sets": sets}
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    # NOT sort_keys: the documents' insertion order is part of the input (and of what the oracle recorded)
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=None) + "\n", encoding="utf-8", newline="\n")
    return report(json.loads(GOLDEN.read_text(encoding="utf-8")), "NEWS GOLDENS")


def report(golden: dict[str, Any], label: str) -> int:
    problems = compare_goldens(golden)
    print(json.dumps({"golden": str(GOLDEN), "bytes": GOLDEN.stat().st_size, "old": golden["provenance"], "summary": summary(golden)},
                     indent=1, ensure_ascii=False))  # fmt: skip
    for p in problems[:60]:
        print("  DIFF", p)
    print(f"{label} MATCH" if not problems else f"{label} DIFFER ({len(problems)})")
    return 1 if problems else 0


# ------------------------------------------------------------------ the real snapshot, through the API routes
REAL_CLOCK = "2026-11-12T09:00:00"
_REAL_PATHS = {"view": ("/api/news", None), "weekly": ("/api/news/weekly", None),
               "refresh_status": ("/api/news/refresh_status", None),
               **{f"sources:{w}": ("/api/news/sources", {"window": w}) for w in WINDOWS}}  # fmt: skip


def real() -> int:  # pragma: no cover - needs the hosted database and the old repository
    """The real snapshot imported by the production importer into a throw-away schema, through the API routes, against
    the OLD routes over a byte-exact copy at the same clock (the old shipped curated cases; each old route on a fresh
    copy, its seeding save captured in memory). Declared (e) and (s) only, normalised as for the goldens; every table
    is checked unchanged by the reads. Aggregates only are printed."""
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
    old = scratch_oracle(ORACLE, {"clock": REAL_CLOCK, "routes": ROUTES}, files)  # the old shipped cases
    old.pop("meta", None)
    schema = f"pz_rehearse_{_secrets.token_hex(4)}"
    problems: list[str] = []
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
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            for route in ROUTES:
                path, params = _REAL_PATHS[route]
                r = client.get(path, params=params)
                got[route] = {"code": 200, "body": js(r.json())} if r.status_code == 200 else {"raises": r.status_code}
        with transaction(settings.db_url) as c:
            after = _fingerprint(c, schema)
        expected = {route: {k: v for k, v in ans.items() if k != "saved"} for route, ans in old["routes"].items()}
        o = normalise(expected, problems, "old")
        n = normalise(got, problems, "new")
        for route in ROUTES:
            problems += [f"/{route}{p}" for p in diff(js(o[route]), js(n[route]))]
            if _text(o[route]) != _text(n[route]):
                problems.append(f"/{route}: the serialized answer differs (key order)")
        saved = [route for route, ans in old["routes"].items() if ans.get("saved") is not None]
        changed = sorted(t for t in before if before[t] != after.get(t))
        if changed:
            problems.append(f"/stored: a News read changed {changed}")
        body = got["view"].get("body") or {}
        report_ = {"counts": body.get("counts"), "stories": len(body.get("stories") or []),
                   "sources": {w: (got[f"sources:{w}"].get("body") or {}).get("benchmark_events") for w in WINDOWS},
                   "old_seeding_saved_on": saved, "tables_checked": len(before), "old_changed": old.get("changed")}  # fmt: skip
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    report_["differences"] = len(problems)
    print(json.dumps(report_, indent=2, default=str, ensure_ascii=False))
    for line in problems[:60]:
        print("  DIFF", line)
    print("NEWS PARITY PASSED" if not problems else "NEWS PARITY FAILED")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else "check"
    if mode == "real":
        return real()
    if mode == "goldens":
        return write_goldens()
    if mode == "check":
        return report(json.loads(GOLDEN.read_text(encoding="utf-8")), "NEWS CHECK")
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
