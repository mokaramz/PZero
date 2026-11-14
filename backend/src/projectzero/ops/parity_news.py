# ruff: noqa: E501
# (the synthetic corpus: one record per line)
"""News parity: the pure port against the OLD code as oracle, with a FIXED clock and no write (review 028a).

    python -m projectzero.ops.parity_news goldens   # (re)generates golden_v1/oracle_news.json
    python -m projectzero.ops.parity_news check     # the stored golden against the new code (no oracle)
    python -m projectzero.ops.parity_news writes-goldens  # (re)generates golden_v1/oracle_news_writes.json (028b)
    python -m projectzero.ops.parity_news writes-check    # the stored writes golden against the new code
    python -m projectzero.ops.parity_news refresh-goldens # (re)generates golden_v1/oracle_news_refresh.json (028c)
    python -m projectzero.ops.parity_news refresh-check   # the stored refresh golden against the new code
    python -m projectzero.ops.parity_news cards-goldens   # (re)generates golden_v1/oracle_news_cards.json (028d)
    python -m projectzero.ops.parity_news cards-check     # the stored cards golden against the new code

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

The writes (review 028b, ``writes-goldens`` / ``writes-check``, ``golden_v1/oracle_news_writes.json``): the oracle
(``scripts/oracle/news_writes_oracle.py``) runs the old ``decide_outcome`` / ``audit_miss`` / ``add_backcast_signal``
over the ``main`` world plus eight write events (``writes_docs``), sequence by sequence, each from the FRESH folder:
confirm; confirm then confirm / reject / not_enough (the prior confirmation, nothing appended); reject then confirm;
not_enough twice; an archived confirm; every outcome refusal in the old order (and the old 500 of an event without a
source), the source URL choice; miss audits with the defaults and explicit fields, a bad ``why_missed`` (refused after
the frozen context), no company, an unknown event; backcasts with year / month / day dates, a time cut to its day, a
trailing newline the old ``$`` accepted, kind / family fallbacks, a stripped URL, an event without ``backcast``, on a
curated and a non-curated event; every backcast refusal in the old order (and the old 500s of an unhashable family and
a ``null`` backcast); writes on the not-yet-seeded curated case (a backcast, a confirm, an audit and a refusal).
Before every write the oracle runs the old view's seeding (the store's ``ensure_seeded``). Clock frozen, the old
``_id`` timestamp answering the step's seam (the new ``new_hex``), every save and append in memory (the folder is
checked unchanged). Compared per step: the seeding (vs ``news.writes.ensure_seeded``), the answer (value and text),
the appended action and Validation bytes, the saved event record (key order) and the next old ``news.view()`` /
``validation.view()`` against the pure views over the updated inputs (``news.writes.applied``), kept in the golden as
sha-256 digests per section. No declared difference (the Validation view through 027b's normalisation (d)).

The refresh run (review 028c, ``refresh-goldens`` / ``refresh-check``, ``golden_v1/oracle_news_refresh.json``): the
oracle (``scripts/oracle/news_refresh_oracle.py``) drives the old ``start_refresh`` SYNCHRONOUSLY twice (10:00, then
10:25) over the ``refresh_docs`` world (028a's ``main`` without its two unreadable stories, plus stored events to
re-derive, collide with and syndicate, Swiss ticker candidates, known names, a cooldown, a third extra feed), its
``connectors._get`` answering the recorded ``refresh_feeds`` bytes (new items, merges by entity / type / date, a
syndicated copy, the same URL, an id collision, a future date, a 23:30 -07:00 time, junk after ``</rss>``,
undeclared entities, a bad item and an item without a link, 45 items, a stale feed, a 429, a feed in its cooldown,
a 500, a TLS failure, Atom with ``published`` / ``updated``, relative links and a permalink GUID, an unparseable
extra feed), the clock frozen, the model refused (deterministic cards), every write in memory. The new side is
``news.writes.ensure_seeded`` then per run ``refresh.plan`` -> ``fetch_all`` (``FixtureTransport``, a resolver
answering ``FIXTURE_IP``) -> ``apply`` over the documents re-read, its writes applied to the documents. Compared per
run: the answer, the events document (key order), every appended line byte for byte, the last saved body of every
document, the fetched URLs (each sent with the News User-Agent to the checked address) and the next News and sources
views (sha-256 digests per section). Declared differences, normalised in ``compare_refresh`` only
(``REFRESH_DECLARED``): (a) the TLS feed (the parity run serves it as the old fallback did; the strict run, the
production policy, fails it with its reason and changes nothing else, checked by ``check_strict``); (d) the
nominations (a ``nomination_deferred`` line per old ``nominate`` call); (e) no run-state start marker; 028a's (e) / (s)
inside the metric cache. The watch bridge is compared like any other write since review 037b lifted its deferral:
the new side passes ``apply`` the pure bridge (``pure_bridge``: ``watch.run.bridge_lines`` over the world's WATCH
candidates, targets, proposals and trigger log), whose ``watch/triggers.jsonl`` lines and ``watch_triggers`` count
must equal the old run's (its high-value case refresh is deferred, 037b decision f: nothing to compare).

The model cards (review 028d, ``cards-goldens`` / ``cards-check``, ``golden_v1/oracle_news_cards.json``): the oracle
(``scripts/oracle/news_cards_oracle.py``) runs the old ``_make_cards`` through the old gateway with the old
``FakeProvider`` (``paid=True``; ``PZ_AI_PAID=on`` on the old side only, no key anywhere, every real provider path
refused), a frozen clock, a scratch ledger per case and the events document in memory, over the 028c world (the
events after the refresh golden's last run: 68 candidates, so the cut at 12 is exercised). ``CARD_CASES``: valid
cards; failures (an invalid card, a malformed reply, a 503 retried then accepted, a 400); ``must_stop`` (a 401) after
the first card; the run cap reached; an event removed, an event carded by a concurrent writer and a headline changed
between the call and the write. The new side is ``news.cards.plan_cards`` -> ``run_cards`` with ``call_card`` (the
new gateway, an ``InMemoryBudgetStore``, the new ``FakeProvider``) and an in-memory writer applying ``still_fits`` /
``with_card``. Compared per case: the selection order, per call the Result, estimate, waits, provider calls and
ledger rows (029a's comparison), the model cards written by event, the changed events (value and key order), the
outcome (made, attempted, stale, stopped, usd). Declared: ``CARDS_DECLARED``.

Exit 1 on any difference.
"""

from __future__ import annotations

import copy
import email.utils
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from projectzero.core import net
from projectzero.core.inference import budget as inference_budget
from projectzero.core.inference import config as inference_config
from projectzero.core.inference.providers import FakeProvider, ProviderError
from projectzero.core.inference.store import InMemoryBudgetStore
from projectzero.core.paths import REPO_ROOT
from projectzero.dealflow.ranking.names import norm_company
from projectzero.news import cards as news_cards
from projectzero.news import catalog as news_catalog
from projectzero.news import core as news_core
from projectzero.news import (
    inputs_from_docs,
    refresh_status,
    seed_cases,
    sources_view,
    view,
    weekly_review,
    with_entities,
)
from projectzero.news import refresh as news_refresh
from projectzero.news import writes as news_writes
from projectzero.news.core import load
from projectzero.news.evaluate import NOMINATION_REASON
from projectzero.news.fetching import USER_AGENT as FEED_USER_AGENT
from projectzero.news.fetching import FeedFetch
from projectzero.news.inputs_model import CASES_KEY
from projectzero.news.sources import HEALTH_REASON
from projectzero.ops import parity_inference as inference_parity
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js

ORACLE = REPO_ROOT / "scripts" / "oracle" / "news_oracle.py"
EVENTS_PATH = "news/events.json"
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


# ------------------------------------------------------------------ review 028b: the writes
WRITES_ORACLE = REPO_ROOT / "scripts" / "oracle" / "news_writes_oracle.py"
WRITES_GOLDEN = GOLDEN_DIR / "oracle_news_writes.json"
SEAM_SIZE = 2  # id-seam values per step (a write makes at most one id)
LONG_HEADLINE = (
    "Invented Société Générale de Robotique — “Café Œuvre” lève 12 millions d'euros pour ses bras robotisés " * 3
)


# fmt: off
def writes_docs() -> dict[str, Any]:
    """The 028a ``main`` world plus the events the writes need (appended at the end of the archive order): an
    outcome kind without a company, a future date, a syndicated first source, only syndicated sources, no source, a
    non-ASCII id with a long non-ASCII headline, no ``backcast`` key, a ``null`` backcast."""
    docs = main_docs()
    events = docs["news/events.json"]["events"]
    extra = [
        ev("nw-w-nocomp", "", "An invented carmaker acquires an unnamed robotics team", "acquisition", day(5), "HIGH"),
        ev("nw-w-future", "Invented Future Robotics", "Invented Future Robotics raises €9M", "funding", day(-3), "MEDIUM", amount=9.0),
        ev("nw-w-synd", "Invented Syndic Robotics", "Invented Syndic Robotics raises €5M", "funding", day(6), "MEDIUM", amount=5.0,
           sources=[src("EU-Startups", "synd-e", day(6), "Invented Syndic Robotics raises €5M", ind="syndicated"),
                    src("Sifted", "synd-s", day(6), "Invented Syndic Robotics raises €5M")]),
        ev("nw-w-allsynd", "Invented Echo Logistics", "Invented Echo Logistics wins an invented retailer", "customer", day(8), "MEDIUM",
           sources=[src("EU-Startups", "allsynd-e", day(8), "Invented Echo Logistics wins", ind="syndicated"),
                    src("Tech.eu", "allsynd-t", day(8), "Invented Echo Logistics wins", ind="syndicated")]),
        ev("nw-w-nosrc", "Invented Sourceless Labs", "Invented Sourceless Labs raises €3M", "funding", day(9), "MEDIUM", amount=3.0, sources=[]),
        ev("nw-w-café", "Invented Société Générale de Robotique", LONG_HEADLINE, "funding", day(10), "HIGH", geo=["FR"], amount=12.0,
           sources=[src("Maddyness", "cafe", day(10), "Invented Société Générale de Robotique lève 12 M€")]),
        ev("nw-w-nobc", "Invented Bare Robotics", "Invented Bare Robotics raises €2M", "funding", day(11), "MEDIUM", amount=2.0),
        ev("nw-w-nullbc", "Invented Null Robotics", "Invented Null Robotics raises €2M", "funding", day(12), "MEDIUM", amount=2.0),
    ]
    del extra[6]["backcast"]
    extra[7]["backcast"] = None
    for e in extra:
        events[e["event_id"]] = e
    return docs


def _o(eid: Any, decision: Any) -> dict[str, Any]:
    return {"op": "outcome", "body": {"event_id": eid, "decision": decision}}


def _a(eid: Any, **kw: Any) -> dict[str, Any]:
    return {"op": "audit", "body": {"event_id": eid, **kw}}


def _b(eid: Any, when: Any, url: Any = "https://evidence.invented.example/signal", **kw: Any) -> dict[str, Any]:
    return {"op": "backcast", "body": {"event_id": eid, "date": when, "url": url, **kw}}


EXPLICIT = {"why_missed": "source_not_covered", "preventable": "yes", "earliest_signal": "Invented lab spinout page",
            "earliest_signal_date": "2026-08-01", "signal_source": "https://lab.invented.example/spinouts",
            "should_have_found": "s-lab", "improvement": "watch the invented lab page weekly"}

WRITE_SEQUENCES: dict[str, list[dict[str, Any]]] = {
    "confirm": [_o("nw-early", "confirm")],
    "confirm-confirm": [_o("nw-early", "confirm"), _o("nw-early", "confirm")],
    "confirm-reject": [_o("nw-early", "confirm"), _o("nw-early", "reject")],
    "confirm-not_enough": [_o("nw-early", "confirm"), _o("nw-early", "not_enough")],
    "reject-confirm": [_o("nw-tie-z", "reject"), _o("nw-tie-z", "confirm")],
    "not_enough-twice": [_o("nw-pre", "not_enough"), _o("nw-pre", "not_enough")],
    "archived-confirm": [_o("nw-acq", "reject"), _o("nw-acq", "confirm"), _o("nw-acq", "maybe")],
    "outcome-refusals": [
        _o("nw-nope", "maybe"), {"op": "outcome", "body": {"event_id": "nw-early"}}, _o("nw-early", ["confirm"]),
        _o("nw-nope", "confirm"), {"op": "outcome", "body": {"decision": "confirm"}}, _o(5, "reject"),
        _o("nw-launch", "confirm"), _o("nw-w-nocomp", "confirm"), _o("nw-w-future", "confirm"), _o("nw-w-nosrc", "confirm"),
        _o("nw-launch", "reject"), _o("nw-w-nosrc", "not_enough"), _o("nw-w-synd", "confirm"), _o("nw-w-allsynd", "confirm"),
        _o("nw-w-café", "confirm"), _o("nw-late", "confirm"), _o("nw-val", "confirm"), _o("nw-shut", "not_enough"),
    ],
    "audit-defaults": [_a("nw-miss"), _a("nw-miss"), _a("nw-unk"), _a("nw-case-a"), _a("nw-w-nobc", why_missed="", preventable="")],
    "audit-explicit": [
        _a("nw-miss", **EXPLICIT), _a("nw-miss", why_missed="forgot"), _a("nw-unk", why_missed="machine_reject", preventable="maybe"),
        _a("nw-w-café", why_missed="entity_extraction", earliest_signal="Une thèse « invented » — 2025"),
        _a("nw-unk2"), _a("nw-nope"), _a(""), _a("nw-w-nosrc"), _a("nw-w-nullbc", why_missed="other"),
    ],
    "backcast": [
        _b("nw-unk", "2025"), _b("nw-unk", "2025-06", kind="in_retrospect", family="grant", text="Invented grant listing"),
        _b("nw-case-a", "2025-06-15", family="accelerator", text="Invented demo day"),
        _b("nw-miss", "2026-10-01T10:00:00", kind="nonsense", family="nonsense", text="t" * 400),
        _b("nw-w-café", "2026-09-30", url="  https://presse.invented.example/société  ", text="Annonce « invented » — été 2026"),
        _b("nw-w-nobc", "2026-09", text=5), _b("nw-pre", "2026\n", family="customer"),
        _b("nw-unk", "2026-10-02", url="http://plain.invented.example/x", kind="known_early_signal", family="university_lab"),
    ],
    "backcast-refusals": [
        _b("nw-unk", "June 2025"), _b("nw-unk", None), _b("nw-unk", "2025-6"), _b("nw-unk", "2025", url=None),
        _b("nw-unk", "2025", url="ftp://files.invented.example/x"), _b("nw-unk", "2025", url="HTTPS://upper.invented.example/x"),
        _b("nw-nope", "2025"), _b("nw-nope", "bad", url=""), _b("nw-nope", "2025", url="nope"), _b("", "2025"),
        _b("nw-unk", "2025", family=["grant"]), _b("nw-w-nullbc", "2025"),
    ],
    "seed-then-backcast": [_b("nw-case-b", "2020-11", family="research_paper", text="Invented earlier preprint"),
                           _o("nw-case-b", "reject")],
    "seed-then-confirm": [_o("nw-case-b", "confirm"), _a("nw-case-b")],
    "seed-then-refusal": [_b("nw-case-b", "2020-11", url="")],
}
# fmt: on


def write_sequences() -> list[dict[str, Any]]:
    """The sequences with the id seam of every step: the old ``str(datetime.now().timestamp())``, the new
    ``new_hex()``."""
    return [
        {
            "name": name,
            "steps": [
                {**st, "seam": [f"{s:02x}{i:02x}{k:08x}" for k in range(SEAM_SIZE)]} for i, st in enumerate(steps)
            ],
        }
        for s, (name, steps) in enumerate(WRITE_SEQUENCES.items())
    ]


def _sha(v: Any) -> str:
    return hashlib.sha256(_text(js(v)).encode("utf-8")).hexdigest()


def digest(answer: dict[str, Any]) -> dict[str, Any]:
    """A view answer as the golden keeps it: its whole serialized text's sha and each top-level section's (in order,
    so a difference names the section); a refusal as it is."""
    body = answer.get("body")
    if not isinstance(body, dict):
        return answer
    return {"code": answer.get("code"), "sha": _sha(body), "sections": [[k, _sha(v)] for k, v in body.items()]}


def _rest(doc: Any) -> dict[str, Any]:
    return {k: v for k, v in load(doc).items() if k != "events"}


def new_write_steps(
    docs: dict[str, Any], clock: str, steps: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """The pure side of one sequence: per step ``news.writes.ensure_seeded`` (installed in both inputs), the pure write
    with ``new_hex`` = the step's seam, its lines and record applied (``news.writes.applied``), then the 028a News view
    and the 027a Validation view over the updated inputs (the latter through 027b's normalisation (d))."""
    from projectzero.ops.parity_validation import old_view
    from projectzero.validation import entities as validation_entities
    from projectzero.validation import inputs_from_docs as validation_inputs
    from projectzero.validation import view as validation_view

    now = datetime.fromisoformat(clock)
    today = now.date()
    v = validation_inputs(docs, today)
    n = v.news_inputs
    fns = {
        "outcome": news_writes.decide_outcome,
        "audit": news_writes.audit_miss,
        "backcast": news_writes.add_backcast_signal,
    }
    problems: list[str] = []
    out: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        events_before = copy.deepcopy(n.events)
        doc, changes = news_writes.ensure_seeded(n.events, n.cases, now)
        if n.events != events_before:
            problems.append(f"[{i}]: ensure_seeded changed its input")
        seed = {"changes": [[c.event_id, c.after] for c in changes], "rest": _rest(doc)} if changes else None
        n, v = news_writes.with_events(n, v, doc)
        hexes = list(step["seam"])
        before = (copy.deepcopy(n), copy.deepcopy(v))
        w: news_writes.NewsWritten | None = None
        try:
            w = fns[step["op"]](n, dict(step["body"]), today=today, now=now, new_hex=lambda: hexes.pop(0), validation=v)  # noqa: B023 - called now
            answer: dict[str, Any] = {"code": 200, "body": js(w.answer)}
        except ValueError as exc:  # NewsError / ValidationError: the route's 400
            answer = {"code": 400, "error": str(exc)}
        except Exception as exc:  # the route would answer 500
            answer = {"raises": type(exc).__name__}
        if (n, v) != before:
            problems.append(f"[{i}]: the write changed its inputs")
        appended: list[list[str]] = []
        saved = None
        if w is not None:
            appended = [[log, line.replace("\n", " ") + "\n"] for log, line in w.validation_appends]
            if w.action_line is not None:
                appended.append(["actions", w.action_line.replace("\n", " ") + "\n"])
            if w.event is not None:
                saved = {"changes": [list(w.event)], "rest": _rest(n.events)}
            n, v = news_writes.applied(n, v, w)
        if n != v.news_inputs:
            problems.append(f"[{i}]: the News and Validation inputs disagree after the write")
        ents = validation_entities(v, today)
        nv = _answer(lambda ents=ents, v=v: view(with_entities(v.news_inputs, ents, v), today, now))
        vv = _answer(lambda v=v: validation_view(v, today, now))
        if "body" in vv:
            vv["body"] = old_view(vv["body"], problems, f"[{i}]/validation_view")
        out.append({"seed": js(seed), "answer": answer, "appended": appended, "saved": js(saved),
                    "news_view": nv, "validation_view": vv})  # fmt: skip
    return out, problems


def compare_writes(golden: dict[str, Any]) -> list[str]:
    """Per step: the seeding (vs ``ensure_seeded``), the answer, the appended bytes, the saved event record (key
    order) and the digests of the next News and Validation views. No declared difference."""
    problems: list[str] = []
    if golden["expected"]["changed"]:
        problems.append(f"/changed: the OLD writes changed {golden['expected']['changed']}")
    for seq in golden["sequences"]:
        name = seq["name"]
        got, invariants = new_write_steps(golden["docs"], golden["clock"], seq["steps"])
        problems += [f"/{name}{p}" for p in invariants]
        for i, (step, old, new) in enumerate(
            zip(seq["steps"], golden["expected"]["sequences"][name], got, strict=True)
        ):
            at = f"/{name}[{i}]({step['op']})"
            new = {**new, "news_view": digest(new["news_view"]), "validation_view": digest(new["validation_view"])}
            for part in ("seed", "answer", "saved", "news_view", "validation_view"):
                o, g = old[part], new[part]
                if part == "seed" and isinstance(o, dict) and "added" in o:
                    o = {"changes": o["changes"], "rest": o["rest"]} if o["changes"] else None
                problems += [f"{at}/{part}{p}" for p in diff(js({"v": o}), js({"v": g}))]
                if _text(o) != _text(g):
                    problems.append(f"{at}/{part}: the serialized value differs (key order)")
            if old["appended"] != new["appended"]:  # byte for byte
                problems.append(f"{at}/appended: {old['appended']!r} != {new['appended']!r}")
    return problems


def writes_summary(golden: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, steps in golden["expected"]["sequences"].items():
        out[name] = {
            "answers": [s["answer"].get("code", s["answer"].get("raises")) for s in steps],
            "appended": [[a[0] for a in s["appended"]] for s in steps],
            "seeded": [len(s["seed"]["changes"]) if s["seed"] else 0 for s in steps],
            "saved": [s["saved"]["changes"][0][0] if s["saved"] else None for s in steps],
        }
    return out


def read_golden(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(path.read_bytes().decode("utf-8"))
    return out


def writes_report(golden: dict[str, Any]) -> int:
    problems = compare_writes(golden)
    print(json.dumps({"golden": str(WRITES_GOLDEN), "bytes": WRITES_GOLDEN.stat().st_size, "old": golden["provenance"],
                      "summary": writes_summary(golden)}, ensure_ascii=False))  # fmt: skip
    for p in problems[:60]:
        print("  DIFF", p)
    print("NEWS WRITES GOLDENS MATCH" if not problems else f"NEWS WRITES GOLDENS DIFFER ({len(problems)})")
    return 1 if problems else 0


def write_writes_goldens() -> int:
    docs = writes_docs()
    sequences = write_sequences()
    files, cases = split_cases(docs)
    oracle = scratch_oracle(WRITES_ORACLE, {"clock": CLOCK, "sequences": sequences}, files, cases,
                            prefix="pz-news-writes-oracle-")  # fmt: skip
    meta = oracle.pop("meta")
    for steps in oracle["sequences"].values():
        for s in steps:  # the views as digests (each full view is ~0.3 MB)
            s["news_view"], s["validation_view"] = digest(s["news_view"]), digest(s["validation_view"])
    golden = {"provenance": meta, "clock": CLOCK, "docs": docs, "sequences": sequences, "expected": oracle}
    # NOT sort_keys (the documents' insertion order is part of the input); bytes, so no newline translation
    WRITES_GOLDEN.write_bytes((json.dumps(golden, ensure_ascii=False, indent=None) + "\n").encode("utf-8"))
    return writes_report(read_golden(WRITES_GOLDEN))


# ------------------------------------------------------------------ review 028c: the refresh run
REFRESH_ORACLE = REPO_ROOT / "scripts" / "oracle" / "news_refresh_oracle.py"
REFRESH_GOLDEN = GOLDEN_DIR / "oracle_news_refresh.json"
REFRESH_CLOCKS = ("2026-11-12T10:00:00", "2026-11-12T10:25:00")  # run 2: the 10:20 cooldown is over, the 429's is not
FIXTURE_IP = "93.184.216.34"  # every fixture host resolves here (a public address; nothing is ever sent to it)
WATCH_LOG = "watch/triggers.jsonl"  # the watch bridge's log (review 037b: compared)
TLS_FEED = "Maddyness"  # decision (a): the old insecure fallback fetched it; the new fetch fails it
TLS_ERROR = "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate (_ssl.c:1032)"
LOG_PATHS = {"runs": "news/runs.jsonl", "disagreements": "news/disagreements.jsonl",
             "source_log": "news/source_log.jsonl", "source_history": "news/source_history.jsonl"}  # fmt: skip
FEED_URLS = {f["name"]: f["url"] for f in news_catalog.FEEDS}
GAZETTE = "https://gazette.invented.example/rss"
LEDGER = "https://ledger.invented.example/feed"


# fmt: off
def rss(items: list[str], tail: str = "") -> str:
    return "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<rss version=\"2.0\"><channel><title>Invented</title>" + "".join(items) + "</channel></rss>" + tail


def item(title: str, link: str | None, pub: str, desc: str = "", guid: str | None = None) -> str:
    return ("<item><title>" + title + "</title>" + (f"<link>{link}</link>" if link is not None else "") + (f"<guid>{guid}</guid>" if guid else "")
            + (f"<pubDate>{pub}</pubDate>" if pub else "") + (f"<description>{desc}</description>" if desc else "") + "</item>")


def atom(entries: list[str]) -> str:
    return "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<feed xmlns=\"http://www.w3.org/2005/Atom\"><title>Invented</title>" + "".join(entries) + "</feed>"


def entry(title: str, href: str, published: str, updated: str = "", summary: str = "") -> str:
    return (f"<entry><title>{title}</title><link rel=\"alternate\" href=\"{href}\"/><link rel=\"self\" href=\"{href}.xml\"/>"
            + (f"<published>{published}</published>" if published else "") + (f"<updated>{updated}</updated>" if updated else "")
            + (f"<summary>{summary}</summary>" if summary else "") + "</entry>")


def rfc(n: int, hm: str = "08:00", zone: str = "+0100") -> str:
    """An RFC 2822 time ``n`` days before the clock's day."""
    return email.utils.format_datetime(datetime.fromisoformat(f"{day(n)}T{hm}:00")).replace("-0000", zone)


COLLIDE = "Invented Hazel Robotics raises €3M to automate greenhouses"
SYND = "Europe's robot makers meet at an invented fair in Lyon"


def collision_id() -> str:
    """The id the old ingest gives ``COLLIDE`` (published on the clock's day): a stored event takes it first."""
    company, _how = news_refresh._company(COLLIDE, "", [])
    cls = news_core.classify(COLLIDE, "")
    return "nw-" + news_refresh._sha(key(company) or COLLIDE, cls["event_type"], TODAY.isoformat()[:7])


def refresh_feeds() -> dict[str, Any]:
    sifted = rss([
        item("Invented Alder Robotics raises €5M seed round", "https://sifted.eu/articles/alder", rfc(1), "<p>The Berlin team builds robot grippers &amp; arms.</p>"),
        item("Invented Kestrel Robotics closes its €4M seed round", "https://sifted.eu/articles/kestrel-close", rfc(1, "07:00"), "Second report of the Munich round."),
        item("Invented Kestrel Robotics raises €4M seed round", "https://news.invented.example/early-s", rfc(2)),  # the very same URL: skipped
        item("Invented Birch Analytics raises €2M for AI audits", "https://sifted.eu/articles/birch", "Fri, 20 Nov 2026 09:00:00 +0100"),  # future: today
        item("Orphan headline without a link", None, rfc(1)),
        item("Invented Broken Link Co raises €1M", "http://[bad/x", rfc(1)),  # urljoin raises: the item is skipped
        item("Invented Cobalt Sensors secures €3M for industrial AI", "/articles/cobalt", "Tue, 10 Nov 2026 23:30:00 -0700"),  # Berlin: 11 Nov
        item("Invented Lumen Grid opens a second robotics plant", "https://sifted.eu/articles/lumen", rfc(3)),
        item("Invented Spruce Quantum unveils its first deeptech chip", "https://sifted.eu/articles/spruce", rfc(2)),
        item(COLLIDE, "https://sifted.eu/articles/hazel", rfc(0, "09:15")),
        item("Top 10 robotics startups to watch this winter", "https://sifted.eu/articles/top10", rfc(1)),
    ])
    techeu = rss([
        item("Invented Dune&nbsp;Robotics raises €8M Series A for caf&eacute; robots", "https://tech.eu/2026/11/dune", rfc(1), "Les fondateurs &laquo;Dune&raquo; &bogus; build robots."),
        item(SYND, "https://tech.eu/2026/11/lyon", rfc(1)),
        item("Invented Ember Defence raises €40M Series B", "https://tech.eu/2026/11/ember", rfc(2), "A dual-use defence drone maker in Germany."),
    ], tail="<script>track('ad')</script><div>junk after the feed</div>")
    bulk = rss([item(f"Invented Bulk Co {i} raises €{1 + i % 5}M" + (" for robotics" if i % 3 == 0 else ""), f"https://www.eu-startups.com/2026/11/bulk-{i}", rfc(i % 9)) for i in range(45)])
    stale = rss([item("Invented Old Harbor raises €2M", "https://www.siliconcanals.com/old-harbor", rfc(20)),
                 item("Invented Older Pier raises €1M", "https://www.siliconcanals.com/older-pier", rfc(25))])
    deutsche = rss([item("Invented Rhein Robotics erhält 3 Millionen Euro", "https://www.deutsche-startups.de/rhein", rfc(0, "06:00"))])
    madd = atom([entry("Invented Lavande Robotique lève 6 millions d'euros", "https://www.maddyness.com/2026/11/lavande", f"{day(1)}T08:00:00+01:00", summary="Une start-up lyonnaise de robotique.")])
    uktn = rss([
        item("Invented Thames Logistics raises £4M", "/2026/11/thames", rfc(2), "A London AI logistics team."),
        item("Invented Mersey Robotics lands £2M", None, rfc(1), guid="https://www.uktech.news/p/mersey"),
        item("Invented Tyne Labs signs a defence customer", None, rfc(1), guid="not-a-permalink"),
    ])
    arctic = atom([
        entry("Invented Fjell Robotics raises €7M Series A", "https://arcticstartup.com/fjell", f"{day(1)}T22:30:00Z", f"{day(0)}T09:00:00Z", "Nordic robotics."),
        entry("Invented Sami AI gets €2M", "https://arcticstartup.com/sami", "", f"{day(2)}T10:00:00+02:00"),
    ])
    ledger = rss([item("Invented Ledger Pick: Invented Moss Robotics raises €2M", "https://ledger.invented.example/moss", rfc(1))])
    return {
        FEED_URLS["Sifted"]: {"body": sifted},
        FEED_URLS["Tech.eu"]: {"body": techeu},
        FEED_URLS["EU-Startups"]: {"body": bulk},
        FEED_URLS["Silicon Canals"]: {"body": stale},
        FEED_URLS["Startbase"]: {"status": 429, "body": ""},
        FEED_URLS["deutsche-startups.de"]: {"body": deutsche},
        FEED_URLS["Munich Startup"]: {"status": 500, "body": ""},
        FEED_URLS["Maddyness"]: {"body": madd, "tls": True},
        FEED_URLS["UKTN"]: {"body": uktn},
        FEED_URLS["ArcticStartup"]: {"body": arctic},
        LEDGER: {"body": ledger},
        GAZETTE: {"body": "not xml at all & <"},
    }


def refresh_docs() -> dict[str, Any]:
    """The 028a ``main`` world (its two unreadable stories removed: the old run would crash on them) plus the stored
    events the run must re-derive, collide with and syndicate, the Swiss ticker candidates, the known names, a
    cooldown and one more extra feed."""
    docs = main_docs()
    events = docs["news/events.json"]["events"]
    for eid in ("nw-bad", "nw-nokey"):
        del events[eid]
    synd_src = src("Invented Wire", "lyon", day(2), SYND, host="wire.invented.example")
    synd_src["text_sha"] = news_refresh._sha(news_refresh._norm_text(SYND))
    extra = [
        ev("nw-r-other", "Invented Birchwood Labs", "Invented Birchwood Labs raises €2M seed round for robotics", "other", day(6), "LOW", amount=None),
        ev("nw-r-nocomp", "", "Invented Juniper Sensors launches a robotics pilot line", "launch", day(5), "LOW"),
        ev("nw-r-broken", "12.10.2026 17:08", "Invented sensor maker raises money", "funding", day(8), "MEDIUM", amount=2.0),
        ev("nw-r-noise", "Invented Poplar AI", "Top 10 robotics startups to watch this winter in Berlin", "other", day(9), "LOW"),
        ev("nw-r-mat", "Invented Aspen Robotics", "Invented Aspen Robotics raises €25M", "funding", day(7), "LOW", amount=25.0),
        ev("nw-r-synd", "", SYND, "other", day(2), "LOW", sources=[synd_src]),
        ev("nw-r-rules", "Invented Willow Robotics", "Invented Willow Robotics raises €9M seed", "funding", day(4), "MEDIUM", amount=9.0, rnd="seed",
           card={"what_happened": "an older rules card", "why_it_matters": "", "the_company": "", "vc_lesson": "", "watch_next": [], "generated_by": "rules"}),
        ev(collision_id(), "Invented Hazel Holdings", "Invented Hazel Holdings buys a greenhouse", "acquisition", TODAY.replace(day=1).isoformat(), "HIGH"),
    ]
    for e in extra:
        events[e["event_id"]] = e
    docs["inbox.json"]["candidates"] += [
        cand("t1", "Invented Alpine Robotics", "startupticker.ch", "announcement", day(2),
             raw_title="Invented Alpine Robotics sichert sich 4 Millionen Franken", source_url="https://www.startupticker.ch/en/news/alpine"),
        cand("t2", "Invented Glacier AI", "startupticker.ch", "announcement", day(3),
             raw_title="12.11.2026 Invented Glacier AI", description="Invented Glacier AI raises CHF 2M for robotics", source_url="https://www.startupticker.ch/en/news/glacier"),
        cand("t3", "01.11.2026 10:00", "startupticker.ch", "announcement", day(4), raw_title="01.11.2026 10:00"),
    ]
    docs["real_data.json"] = {"signals": [{"company": "Invented Larch Photonics", "stage": "Watch"}]}
    docs["scout_intake.json"] = {"items": [{"entity_name": "Invented Spruce Quantum"}, {"entity_name": "AI"}]}
    docs["news/feed_cooldown.json"] = {"Gone Feed": "2026-11-01T00:00:00", "deutsche-startups.de": "2026-11-12T10:20:00"}
    docs["news/feeds_extra.json"]["feeds"].append(
        {"name": "Invented Gazette", "feed_url": GAZETTE, "geo": "FR", "state": "TRUSTED", "enabled": True})
    return docs


def refresh_runs() -> list[dict[str, Any]]:
    return [{"clock": c, "seam": [f"{i:x}{'abc'[i]}d{i}" + "0" * 28]} for i, c in enumerate(REFRESH_CLOCKS)]
# fmt: on


class FixtureTransport:
    """Answers from the recorded feed bytes and records every request it was asked to send (URL, headers, address).
    ``strict``: a ``tls`` feed fails its certificate check (the production behaviour, decision a); otherwise it is
    served as the old insecure fallback served it (the parity run)."""

    def __init__(self, feeds: Mapping[str, Any], *, strict: bool = True) -> None:
        self.feeds = feeds
        self.strict = strict
        self.requests: list[dict[str, Any]] = []

    def send(self, target: net.Target, method: str, headers: Mapping[str, str], body: bytes | None, timeout: float,
             max_bytes: int, deadline: float | None = None, *, truncate: bool = False) -> net.Response:  # fmt: skip
        default = 443 if target.scheme == "https" else 80
        url = f"{target.scheme}://{target.host}{'' if target.port == default else f':{target.port}'}{target.path}"
        self.requests.append({"url": url, "headers": dict(headers), "ip": target.ip, "timeout": timeout,
                              "max_bytes": max_bytes, "deadline": deadline})  # fmt: skip
        spec = self.feeds.get(url) or {"status": 404, "body": ""}
        if spec.get("tls") and self.strict:
            raise ssl.SSLCertVerificationError(1, TLS_ERROR)
        if spec.get("error"):
            raise OSError(spec["error"])
        raw = spec.get("raw")
        data: bytes = raw if isinstance(raw, bytes) else str(spec.get("body", "")).encode("utf-8")
        if len(data) > max_bytes:
            raise net.ResponseTooLargeError(f"response exceeds the {max_bytes}-byte cap")
        return net.Response(
            url, int(spec.get("status", 200)), {k.lower(): v for k, v in (spec.get("headers") or {}).items()}, data
        )


def fixture_resolver(host: str) -> list[str]:
    return [FIXTURE_IP]


def applied_docs(docs: dict[str, Any], out: news_refresh.RunOutcome) -> dict[str, Any]:
    """The old-format documents after ``out`` was stored, as the old files would read back."""
    d = dict(docs)
    d[EVENTS_PATH] = out.events_doc
    for log, line in out.appends:
        path = LOG_PATHS[log]
        d[path] = text_of(d.get(path)) + line + "\n"
    for path, body in out.documents.items():
        d[path] = body
    return d


def text_of(raw: Any) -> str:
    if raw is None:
        return ""
    return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)


def _views(docs: dict[str, Any], today: date, now: datetime) -> dict[str, Any]:
    from projectzero.validation import entities as validation_entities
    from projectzero.validation import inputs_from_docs as validation_inputs

    v = validation_inputs(docs, today)
    ents = validation_entities(v, today)
    inputs = with_entities(v.news_inputs, ents, v)
    return {
        "news": _answer(lambda: view(inputs, today, now)),
        "sources:90": _answer(lambda: sources_view(inputs, "90", today)),
        "sources:all": _answer(lambda: sources_view(inputs, "all", today)),
    }


def new_refresh(golden_in: dict[str, Any], *, strict: bool) -> tuple[dict[str, Any], list[str]]:
    """The pure side: ``ensure_seeded`` (the store, before the first write transaction), then per run ``plan`` ->
    ``fetch_all`` (the fixture transport, a resolver that answers every host with ``FIXTURE_IP``, the clock at 0) ->
    ``apply`` over the documents re-read, its writes applied to the documents, and the next views."""
    from projectzero.validation import inputs_from_docs as validation_inputs

    docs = copy.deepcopy(golden_in["docs"])
    problems: list[str] = []
    first = datetime.fromisoformat(golden_in["runs"][0]["clock"])
    v = validation_inputs(docs, first.date())
    doc, changes = news_writes.ensure_seeded(v.news_inputs.events, v.news_inputs.cases, first)
    seed = {"added": len(changes), "events": js(doc)} if changes else None
    docs[EVENTS_PATH] = doc
    runs: list[dict[str, Any]] = []
    transport = FixtureTransport(golden_in["feeds"], strict=strict)
    for r in golden_in["runs"]:
        now = datetime.fromisoformat(r["clock"])
        today = now.date()
        seam = list(r["seam"])
        run_id = news_refresh.new_run_id(now, lambda: seam.pop(0))  # noqa: B023 - called now
        v = validation_inputs(docs, today)
        before = copy.deepcopy(v)
        p = news_refresh.plan(v.news_inputs, today, now, run_id=run_id, clock=lambda: 0.0)
        transport.requests.clear()
        results = news_refresh.fetch_all(
            p, FeedFetch(transport=transport, resolver=fixture_resolver, clock=lambda: 0.0)
        )
        current = validation_inputs(docs, today)  # phase 3 re-reads the CURRENT inputs
        bridged: list[str] = []
        out = news_refresh.apply(news_refresh.RunInputs(current.news_inputs, current), results, today=today, now=now,
                                 run_id=run_id, clock=lambda: 0.0, watch=pure_bridge(docs, now, bridged))  # fmt: skip
        if v != before or current != before:
            problems.append(f"/run {run_id}: the run changed its inputs")
        stored = load(current.news_inputs.events)["events"]
        for c in out.new_events:
            if c.event_id in stored or ("ingest" not in c.passes and "seed" not in c.passes):
                problems.append(f"/run {run_id}/new_events/{c.event_id}: not a new event of the ingest")
        for c in out.changed_events:
            if c.event_id not in stored or _text(stored[c.event_id]) == _text(c.record) or not c.passes:
                problems.append(f"/run {run_id}/changed_events/{c.event_id}: not a changed stored event")
        docs = applied_docs(docs, out)
        if bridged:  # the store appends them in the run's transaction
            docs[WATCH_LOG] = text_of(docs.get(WATCH_LOG)) + "".join(x + "\n" for x in bridged)
        runs.append(
            {
                "answer": {"code": 200, "body": js(out.answer)},
                "events": js(out.events_doc),
                "appended": [[WATCH_LOG, x + "\n"] for x in bridged]
                + [[LOG_PATHS[log], line + "\n"] for log, line in out.appends],
                "documents": js(out.documents),
                "deferred_nominations": js(list(out.evaluation.deferred_nominations)) if out.evaluation else [],
                "requests": [dict(q) for q in transport.requests],
                "outcome": out,
                "views": _views(docs, today, now),
            }
        )
    return {"seed": seed, "runs": runs}, problems


def pure_bridge(docs: dict[str, Any], now: datetime, out: list[str]) -> Any:
    """The news bridge over the world's old-format documents (review 037b): the WATCH candidates of ``inbox.json``,
    ``watch/targets.json``, the current proposals and the ``watch/triggers.jsonl`` dedupe keys; its lines go to
    ``out`` (the store would append them in the run's transaction)."""
    from projectzero.watch import log as watch_log
    from projectzero.watch import run as watch_run
    from projectzero.watch import targets as watch_targets
    from projectzero.watch import writes as watch_writes

    def bridge(events: dict[str, Any]) -> int:
        inbox = docs.get("inbox.json") or {}
        targets = watch_targets.targets_of(docs.get("watch/targets.json"))
        watched = watch_targets.watched(copy.deepcopy(inbox.get("candidates") or []), targets)
        proposals = (docs.get("triage_proposals.json") or {}).get("proposals") or {}
        fired = watch_writes.keys_of(watch_log.parse_text(text_of(docs.get(WATCH_LOG))))
        n, lines = watch_run.bridge_lines(events, watched, fired=fired, proposals=proposals, ts=watch_run.ts_of(now),
                                          today=now.date())  # fmt: skip
        out.extend(lines)
        return n

    return bridge


def _norm_metrics(doc: Any, problems: list[str], side: str, at: str) -> Any:
    """Declared (e) and (s) of 028a inside the metric cache: the Swiss technical row's ``reason`` (new side, checked
    then dropped) and the hash-ordered ``unique.by_scope`` keys (sorted on both sides)."""
    out = copy.deepcopy(doc)
    for w, m in ((out or {}).get("windows") or {}).items():
        for row in (m.get("sources") or {}).values():
            tech = row.get("technical") or {}
            if side == "new" and row.get("kind") == "deal_flow_reuse":
                if tech.get("reason") != HEALTH_REASON:
                    problems.append(f"{at}/windows/{w}: the Swiss technical row has no deferral reason")
                tech.pop("reason", None)
            unique = row.get("unique") or {}
            if isinstance(unique.get("by_scope"), dict):
                unique["by_scope"] = dict(sorted(unique["by_scope"].items()))
    return out


def _denominate(rec: Any) -> Any:
    """Declared (d) in a run record: the old ``source_eval.nominated`` held the source-network candidate ids."""
    if isinstance(rec, dict):
        rec = copy.deepcopy(rec)
        if isinstance(rec.get("source_eval"), dict):
            rec["source_eval"]["nominated"] = []
    return rec


def _old_appended(
    lines: list[list[str]], nominated: list[dict[str, Any]], problems: list[str], at: str
) -> list[list[str]]:
    """Declared (d) on the old side: the ``nominated`` source-log line dropped (after checking it lists one candidate
    per ``nominate`` call), the ``evaluated`` line's ``nominated`` count and the run line's ``source_eval.nominated``
    read as the deferral leaves them (0, ``[]``)."""
    out: list[list[str]] = []
    watched = 0
    for path, text in lines:
        row = json.loads(text) if text.strip().startswith("{") else None
        if path == WATCH_LOG:  # compared (review 037b): counted against the run line's watch_triggers
            watched += 1
        if path == LOG_PATHS["runs"] and isinstance(row, dict) and row.get("watch_triggers") != watched:
            problems.append(
                f"{at}: the old run counted {row.get('watch_triggers')} watch triggers, {watched} were written"
            )
        if path == LOG_PATHS["source_log"] and isinstance(row, dict) and row.get("event") == "nominated":
            if row.get("candidates") != [f"cand-{i + 1}" for i in range(len(nominated))]:
                problems.append(f"{at}: the old nominated line does not match its nominate calls")
            continue
        if path == LOG_PATHS["source_log"] and isinstance(row, dict) and row.get("event") == "evaluated":
            row["nominated"] = 0
            text = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        if path == LOG_PATHS["runs"] and isinstance(row, dict):
            text = json.dumps(_denominate(row), ensure_ascii=False, sort_keys=True) + "\n"
        out.append([path, text])
    return out


def _new_appended(lines: list[list[str]], deferred: list[dict[str, Any]], nominated: list[dict[str, Any]],
                  problems: list[str], at: str) -> list[list[str]]:  # fmt: skip
    """Declared (d) on the new side: one ``nomination_deferred`` line per old ``nominate`` call, in the same order
    (name, URL, family, the old ``why``), dropped after the check."""
    out: list[list[str]] = []
    rows = []
    for path, text in lines:
        row = json.loads(text)
        if path == LOG_PATHS["source_log"] and row.get("event") == "nomination_deferred":
            rows.append(row)
            continue
        out.append([path, text])
    want = [
        {"source": n["name"], "url": n["url"], "family": n["family"], "why": n["why"], "reason": NOMINATION_REASON}
        for n in nominated
    ]
    got = [{k: r.get(k) for k in ("source", "url", "family", "why", "reason")} for r in rows]
    if got != want or len(deferred) != len(nominated):
        problems.append(f"{at}: the deferred nominations {got} are not the old nominate calls {want}")
    return out


def _old_answer(ans: dict[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(ans.get("body"))
    if isinstance(body, dict):
        body["last"], body["last_ok"] = _denominate(body.get("last")), _denominate(body.get("last_ok"))
    return {**ans, "body": body}


def _compare(at: str, old: Any, new: Any, problems: list[str]) -> None:
    problems += [f"{at}{p}" for p in diff(js({"v": old}), js({"v": new}))]
    if _text(old) != _text(new):
        problems.append(f"{at}: the serialized value differs (key order)")


def compare_refresh(golden: dict[str, Any]) -> list[str]:
    """Per run: the answer, the events after the run (key order), every appended line byte for byte, the last saved
    body of every document and the next views (sha-256 digests per section), against the parity run (the TLS feed
    served as the old fallback served it); then the strict run (the production policy) checked for the declared TLS
    difference only. Declared differences, normalised here and nowhere else: see ``REFRESH_DECLARED``."""
    exp = golden["expected"]
    problems: list[str] = []
    if exp["changed"]:
        problems.append(f"/changed: the OLD run changed {exp['changed']}")
    got, invariants = new_refresh(golden, strict=False)
    problems += invariants
    _compare("/seed", exp["seed"], got["seed"], problems)
    for i, (old, new) in enumerate(zip(exp["runs"], got["runs"], strict=True)):
        at = f"/run[{i}]"
        _compare(f"{at}/answer", _old_answer(old["answer"]), new["answer"], problems)
        _compare(f"{at}/events", old["events"], new["events"], problems)
        oa = _old_appended(old["appended"], old["nominated"], problems, at)
        na = _new_appended(new["appended"], new["deferred_nominations"], old["nominated"], problems, at)
        if oa != na:
            problems.append(f"{at}/appended: {len(oa)} old lines != {len(na)} new lines")
            problems += [
                f"{at}/appended[{k}]: {a!r} != {b!r}" for k, (a, b) in enumerate(zip(oa, na, strict=False)) if a != b
            ][:6]
        saved = {path: body for path, body in old["saved"]}
        start = old["saved"][0] if old["saved"] else None  # declared (e): the old run-state START marker
        if not (start and start[0] == "news/run_state.json" and start[1].get("running") is True):
            problems.append(f"{at}/saved: the old run did not start with its run-state marker")
        if list(saved) != [*dict.fromkeys(p for p, _b in old["saved"])] or set(saved) != set(new["documents"]):
            problems.append(f"{at}/documents: {sorted(saved)} != {sorted(new['documents'])}")
        for path in saved:
            o, n = saved[path], new["documents"].get(path)
            if path == "news/source_metrics.json":
                o, n = _norm_metrics(o, problems, "old", at), _norm_metrics(n, problems, "new", at)
            _compare(f"{at}/documents/{path}", o, n, problems)
        if [q["url"] for q in new["requests"]] != old["fetched"]:
            problems.append(f"{at}/requests: {[q['url'] for q in new['requests']]} != {old['fetched']}")
        for q in new["requests"]:
            if q["headers"].get("User-Agent") != FEED_USER_AGENT or q["ip"] != FIXTURE_IP:
                problems.append(
                    f"{at}/requests: {q['url']} was not sent with the News User-Agent to the checked address"
                )
        nv = view_digests(normalise(new["views"], problems, "new"))
        ov = copy.deepcopy(old["views"])
        ov["last_run"] = _denominate(ov["last_run"])
        _compare(f"{at}/views", ov, nv, problems)
    problems += check_strict(golden, got)
    return problems


def check_strict(golden: dict[str, Any], parity: dict[str, Any]) -> list[str]:
    """Declared (a): with the production policy the TLS feed fails with its certificate reason and ONLY that changes:
    every other feed outcome is the parity run's, and the new events are the parity run's minus the TLS feed's."""
    problems: list[str] = []
    strict, invariants = new_refresh({**golden, "runs": golden["runs"][:1]}, strict=True)
    problems += [f"/strict{p}" for p in invariants]
    s, o = strict["runs"][0]["outcome"], parity["runs"][0]["outcome"]
    pf = s.record["per_feed"].get(TLS_FEED) or {}
    if not (pf.get("ok") is False and str(pf.get("error", "")).startswith("SSLCertVerificationError: ") and pf.get("http") is None
            and pf.get("rate_limited") is False):  # fmt: skip
        problems.append(f"/strict/per_feed/{TLS_FEED}: {pf}")
    if f"{TLS_FEED}: {pf.get('error')}" not in s.record["sources_failed"] or s.record["status"] != "partial":
        problems.append("/strict: the TLS failure is not recorded as a failed source of a partial run")
    others = {k: v for k, v in s.record["per_feed"].items() if k != TLS_FEED}
    if others != {k: v for k, v in o.record["per_feed"].items() if k != TLS_FEED}:
        problems.append("/strict: another feed's outcome changed")
    keep = [c.event_id for c in o.new_events if any(src_["publisher"] != TLS_FEED for src_ in c.record["sources"])]
    if [c.event_id for c in s.new_events] != keep or not len(keep) < len(o.new_events):
        problems.append("/strict: the new events are not the parity run's minus the TLS feed's")
    return problems


REFRESH_DECLARED = (
    "(a) the TLS feed: the old insecure fallback fetched it; the parity run serves it the same way and the strict run "
    "(the production policy) fails it with its certificate reason, nothing else changing",
    "(d) the nominations: one nomination_deferred source-log line per old nominate call instead of the old nominated "
    "line; nominated is [] / 0 in the run record, the evaluated line and the answer",
    "(e) the run completes inside the request: no run-state START marker is written (only the final {running: false})",
    "028a (e) / (s) inside the metric cache: the Swiss technical row's reason, the unique.by_scope key order",
)


def view_digests(views: dict[str, Any]) -> dict[str, Any]:
    """The next views as the golden keeps them: per view the sha-256 digest per section; the News view's
    ``last_run`` (the run record, where declared (d) applies) kept whole and left out of its digest."""
    out: dict[str, Any] = {}
    for k, a in views.items():
        body = a.get("body")
        if k == "news" and isinstance(body, dict):
            out["last_run"] = body.get("last_run")
            a = {**a, "body": {s: v for s, v in body.items() if s != "last_run"}}
        out[k] = digest(a)
    return out


def refresh_summary(golden: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"seeded": (golden["expected"]["seed"] or {}).get("added"), "runs": []}
    for r in golden["expected"]["runs"]:
        last = (r["answer"].get("body") or {}).get("last") or {}
        out["runs"].append({
            **{k: last.get(k) for k in ("status", "new", "merged", "duplicates_skipped", "reclassified", "cards", "seeded",
                                       "items", "sources_ok", "cooldown", "stale_feeds", "source_eval")},
            "sources_failed": [x.split(":")[0] for x in last.get("sources_failed") or []],
            "appended": dict(Counter(p.rsplit("/", 1)[-1] for p, _t in r["appended"])),
            "saved": [p for p, _b in r["saved"]],
            "nominated": len(r["nominated"]),
            "events": len((r["events"] or {}).get("events") or {}),
        })  # fmt: skip
    return out


def refresh_report(golden: dict[str, Any]) -> int:
    problems = compare_refresh(golden)
    print(json.dumps({"golden": str(REFRESH_GOLDEN), "bytes": REFRESH_GOLDEN.stat().st_size, "old": golden["provenance"],
                      "summary": refresh_summary(golden), "declared": REFRESH_DECLARED}, ensure_ascii=False, indent=1))  # fmt: skip
    for p in problems[:80]:
        print("  DIFF", p)
    print("NEWS REFRESH GOLDENS MATCH" if not problems else f"NEWS REFRESH GOLDENS DIFFER ({len(problems)})")
    return 1 if problems else 0


def refresh_input() -> dict[str, Any]:
    return {"docs": refresh_docs(), "feeds": refresh_feeds(), "runs": refresh_runs()}


def write_refresh_goldens() -> int:
    inp = refresh_input()
    files, cases = split_cases(inp["docs"])
    oracle = scratch_oracle(REFRESH_ORACLE, {"feeds": inp["feeds"], "runs": inp["runs"]}, files, cases,
                            prefix="pz-news-refresh-oracle-")  # fmt: skip
    meta = oracle.pop("meta")
    sink: list[str] = []
    for r in oracle["runs"]:  # the views as digests of the normalised old answers (each full view is ~0.3 MB)
        r["views"] = view_digests(normalise(r["views"], sink, "old"))
    golden = {"provenance": meta, **inp, "expected": oracle}
    REFRESH_GOLDEN.write_bytes((json.dumps(golden, ensure_ascii=False, indent=None) + "\n").encode("utf-8"))
    return refresh_report(read_golden(REFRESH_GOLDEN))


# ------------------------------------------------------------------ review 028d: the model cards (phase 4)
CARDS_ORACLE = REPO_ROOT / "scripts" / "oracle" / "news_cards_oracle.py"
CARDS_GOLDEN = GOLDEN_DIR / "oracle_news_cards.json"
CARDS_CLOCK = "2026-11-12T10:30:00"  # after the refresh golden's second run (10:25)
CARD_USAGE = {"prompt_tokens": 1000, "completion_tokens": 200}
CARD_TEMPLATE = {
    "what_happened": "Invented summary of: {headline}",
    "why_it_matters": "An invented signal about the market it names.",
    "the_company": "An invented company.",
    "vc_lesson": "Invented lesson: check the evidence before the story.",
    "watch_next": ["the next invented round", "an invented first customer", "a third signal the validator drops"],
}
CONCURRENT_CARD = {  # the oracle's own constant (scripts/oracle/news_cards_oracle.py)
    "what_happened": "Invented concurrent card.",
    "why_it_matters": "Written by another invented writer.",
    "the_company": "",
    "vc_lesson": "",
    "watch_next": [],
    "generated_by": "invented-concurrent-model",
}
HEADLINE_SUFFIX = " (invented correction)"
CARD = {"card": True}
CARD_CASES: list[dict[str, Any]] = [
    {"name": "valid", "usage": CARD_USAGE, "script": [CARD] * 12, "after": {}},
    {"name": "failures", "usage": CARD_USAGE, "after": {}, "script": [
        CARD,
        {"text": '{"what_happened": "Only one invented field."}'},  # invalid: the old validator refuses it
        {"text": "No JSON in this invented reply."},  # malformed
        {"raise": "server", "status": 503, "message": "HTTP 503: invented upstream unavailable"},  # retried ...
        CARD,  # ... and accepted on the second attempt
        {"raise": "bad_request", "status": 400, "message": "HTTP 400: invented bad request"},  # not retried, no stop
    ]},
    {"name": "must_stop", "usage": CARD_USAGE, "after": {},
     "script": [CARD, {"raise": "auth", "status": 401, "message": "HTTP 401: invented key refused"}]},
    {"name": "run_cap", "usage": {**CARD_USAGE, "estimated_cost": 0.02}, "script": [], "after": {}},
    {"name": "concurrent", "usage": CARD_USAGE, "script": [], "after": {"1": "remove", "2": "carded", "4": "headline"}},
]  # fmt: skip
CARDS_DECLARED = (
    "(b) the prompt: the SYSTEM message gains the untrusted-data sentence (news.cards.UNTRUSTED) after 'no hype, "
    "short.'; the old prompt_sha and cache key (request_sha) differ from the new ones. The oracle sends the NEW system "
    "message through the old code, so every request, sha and estimate is compared as is, and the old text is checked "
    "to equal news.cards.OLD_SYSTEM",
    "(a) where the spend is recorded: the old run line counted the cards' usd; the new run line is phase 3's (rules "
    "cards, usd 0) and the model pass is the run_notes line {run_id, cards: {...}} (card_note)",
    "029a: one ledger row per attempt and a failure after dispatch charged its estimate (parity_inference's "
    "_attempt_rows applied to each old call)",
    "the stale rule (Codex H-274): an accepted card is not written over a story that was carded meanwhile or whose "
    "prompt inputs changed (the old loop wrote it over); it counts as stale, its charge kept",
    "a failure keeps the rules card without rewriting it (phase 3 wrote it; the old loop rewrote the same value)",
)


def cards_world() -> dict[str, Any]:
    """The 028c world: the events after the refresh golden's last run (the old output)."""
    world: dict[str, Any] = read_golden(REFRESH_GOLDEN)["expected"]["runs"][-1]["events"]
    return world


def cards_input() -> dict[str, Any]:
    return {"clock": CARDS_CLOCK, "system": news_cards.SYSTEM, "card": CARD_TEMPLATE, "cases": CARD_CASES}


def _card_responder(script: list[dict[str, Any]]) -> Any:
    """The oracle's responder, line for line, over the new ``Reply`` / ``ProviderError``."""
    queue = list(script)

    def fill(v: Any, headline: str) -> Any:
        if isinstance(v, str):
            return v.replace("{headline}", headline)
        if isinstance(v, list):
            return [fill(x, headline) for x in v]
        return v

    def responder(messages: Any, model: str) -> str:
        item: dict[str, Any] = queue.pop(0) if queue else {"card": True}
        if "raise" in item:
            raise ProviderError(item["raise"], item.get("message", ""), item.get("status"))
        if "card" in item:
            headline = messages[-1]["content"].split("\n", 1)[0][len("HEADLINE: ") :]
            return json.dumps({k: fill(v, headline) for k, v in CARD_TEMPLATE.items()}, ensure_ascii=False)
        return str(item["text"])

    return responder


def _mutate(events: dict[str, Any], eid: str, what: str | None) -> None:
    if what == "remove":
        events.pop(eid, None)
    elif what == "carded":
        events[eid]["card"] = dict(CONCURRENT_CARD)
    elif what == "headline":
        events[eid]["headline"] += HEADLINE_SUFFIX


def new_cards(world: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """Phase 4 over the case: ``plan_cards`` -> ``run_cards`` with the new gateway (``call_card``), an
    ``InMemoryBudgetStore``, the new ``FakeProvider`` and an in-memory writer applying ``still_fits`` /
    ``with_card``; the concurrent changes applied right after the call, as in the oracle."""
    doc = copy.deepcopy(world)
    now = datetime.fromisoformat(CARDS_CLOCK).replace(tzinfo=inference_budget.BERLIN)
    cfg = inference_config.load()
    store = InMemoryBudgetStore()
    fake = FakeProvider(_card_responder(case["script"]), paid=True, usage=case["usage"])
    counter = [0]

    def new_id() -> str:
        counter[0] += 1
        return f"ic-{counter[0]:012d}"

    run_id = news_cards.card_run_id(now)
    calls: list[dict[str, Any]] = []
    writes: list[list[Any]] = []

    def call(job: news_cards.CardJob, deadline: float | None) -> Any:
        before_rows, before_calls = len(store.rows), len(fake.calls)
        waits: list[float] = []
        res = news_cards.call_card(job, deadline, run_id=run_id, store=store, clock=lambda: now, env={"PZ_AI_PAID": "on"},
                                   providers={"deepinfra": fake}, config=cfg, sleep=waits.append, new_id=new_id)  # fmt: skip
        result = dict(res.__dict__)
        result["must_stop"] = res.must_stop
        sent = [{"model": c["model"], "json_mode": c["json_mode"], "max_output_tokens": c["max_output_tokens"],
                 "extra_body": c["extra_body"]} for c in fake.calls[before_calls:]]  # fmt: skip
        calls.append({"entity_id": job.entity_id, "run_id": run_id, "purpose": news_cards.PURPOSE,
                      "run_cap_usd": news_cards.CARD_RUN_CAP_USD, "result": result,
                      "est": inference_parity._estimate(cfg, news_cards.ROLE, job.messages,
                                                        {"max_output_tokens": news_cards.MAX_OUTPUT_TOKENS}),
                      "waits": waits, "calls": sent, "rows": [inference_parity.row_dict(r) for r in store.rows[before_rows:]]})  # fmt: skip
        _mutate(doc["events"], job.event_id, case["after"].get(str(len(calls) - 1)))
        return res

    def write(job: news_cards.CardJob, card: dict[str, Any]) -> news_cards.WriteVerdict:
        current = doc["events"].get(job.event_id)
        if not news_cards.still_fits(current, job):
            return "stale"
        doc["events"][job.event_id] = news_cards.with_card(current, card)
        writes.append([job.event_id, card])
        return "written"

    jobs = news_cards.plan_cards(world)
    out = news_cards.run_cards(jobs, call=call, write=write, deadline=None)
    end = doc["events"]
    changed = {k: end.get(k) for k in {**world["events"], **end} if end.get(k) != world["events"].get(k)}
    return {"jobs": [j.entity_id for j in jobs], "calls": js(calls), "writes": js(writes), "outcome": out,
            "changed": js(dict(sorted(changed.items()))), "store": store}  # fmt: skip


def expected_cards(world: dict[str, Any], case: dict[str, Any], old: dict[str, Any]) -> dict[str, Any]:
    """The old case with every declared difference applied (the new side must equal it)."""
    calls, pos, stale, usd, stopped = [], 0, 0, 0.0, None
    declared: dict[str, str] = {}  # event -> the concurrent change that makes its accepted card stale (not removed)
    for i, c in enumerate(old["calls"]):
        n = len(c["calls"])
        script = [*case["script"], *[{"card": True}] * 20][pos : pos + n]
        pos += n
        exp = inference_parity._norm(inference_parity._attempt_rows({"paid": True, "script": script}, c))
        calls.append(exp)
        res = exp["result"]
        usd += res["usd"]
        what = case["after"].get(str(i))
        if res["ok"] and what in ("remove", "carded", "headline"):
            stale += 1
            if what != "remove":
                declared[c["entity_id"][len("news:") :]] = what
        if res["must_stop"]:
            stopped = "run_cap" if res["error"].startswith(news_cards.RUN_CAP_REASON) else "must_stop"
    writes = [[eid, card] for s in old["saves"] for eid, card in s.items()
              if (card or {}).get("generated_by") != "rules" and eid not in declared]  # fmt: skip
    changed = copy.deepcopy(old["changed"])
    for eid, what in declared.items():  # the stale rule: the story keeps what the concurrent writer left
        mutated = copy.deepcopy(world["events"])
        _mutate(mutated, eid, what)
        changed[eid]["card"] = mutated[eid]["card"]
        if changed[eid] == world["events"][eid]:
            changed.pop(eid)
    return {"calls": calls, "writes": writes, "changed": changed, "stale": stale, "usd": round(usd, 6),
            "stopped": stopped, "attempted": len(old["calls"])}  # fmt: skip


def compare_cards(golden: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if golden["input"] != js(cards_input()):
        return ["the cards golden was generated from another input: regenerate it (cards-goldens)"]
    world = cards_world()
    if golden["world_sha"] != _sha(world):
        return ["the 028c world (oracle_news_refresh.json) changed: regenerate the cards golden (cards-goldens)"]
    exp_old = golden["expected"]
    if exp_old["old_system"] != news_cards.OLD_SYSTEM:
        problems.append("/system: the old SYSTEM is not news.cards.OLD_SYSTEM")
    if exp_old["old_system"].replace("short.\nReturn", f"short.\n{news_cards.UNTRUSTED}\nReturn") != news_cards.SYSTEM:
        problems.append("/system: SYSTEM is not the old prompt plus the declared (b) sentence")
    consts = exp_old["meta"]["constants"]
    if (consts["CARD_RUN_CAP_USD"], consts["MAX_CARDS_PER_RUN"]) != (
        news_cards.CARD_RUN_CAP_USD,
        news_refresh.MAX_CARDS_PER_RUN,
    ):
        problems.append(f"/constants: old {consts}")
    candidates = [e for e in world["events"].values() if e["materiality"] in ("HIGH", "MEDIUM") and news_core._relevant(e)
                  and (not e.get("card") or (e["card"] or {}).get("generated_by") == "rules")]  # fmt: skip
    if len(candidates) <= news_refresh.MAX_CARDS_PER_RUN:
        problems.append(f"/world: only {len(candidates)} candidates (the cut at 12 is not exercised)")
    for case, old in zip(CARD_CASES, exp_old["cases"], strict=True):
        at = f"/{case['name']}"
        new = new_cards(world, case)
        exp = expected_cards(world, case, old)
        if old["made"] != len(new["jobs"]):  # the run line's count (phase 3's rules cards) is unchanged
            problems.append(f"{at}/made: old {old['made']}, new selection {len(new['jobs'])}")
        old_order = [c["entity_id"] for c in old["calls"]]
        if old_order != new["jobs"][: len(old_order)]:
            problems.append(f"{at}/selection: old {old_order}, new {new['jobs']}")
        new_calls = [inference_parity._norm(c) for c in new["calls"]]
        for i, (e, n) in enumerate(zip(exp["calls"], new_calls, strict=False)):
            problems.extend(f"{at}/calls[{i}]{d}" for d in inference_parity._diff(e, n))
        if len(exp["calls"]) != len(new_calls):
            problems.append(f"{at}/calls: {len(exp['calls'])} expected, {len(new_calls)} new")
        for k in ("writes", "changed"):
            problems.extend(f"{at}/{k}{d}" for d in inference_parity._diff(exp[k], new[k]))
            if not inference_parity._diff(exp[k], new[k]) and _text(exp[k]) != _text(new[k]):
                problems.append(f"{at}/{k}: equal values, different key order")
        o = new["outcome"]
        got = {"stale": o.stale, "usd": o.usd, "stopped": o.stopped, "attempted": o.attempted, "made": o.made}
        want = {k: exp[k] for k in ("stale", "usd", "stopped", "attempted")} | {"made": len(exp["writes"])}
        if got != want:
            problems.append(f"{at}/outcome: expected {want}, new {got}")
        if round(sum(c["result"]["usd"] for c in old["calls"]), 6) != old["usd"]:
            problems.append(f"{at}/usd: the old run's usd is not the sum of its calls")
        if o.late or new["store"].reservations:
            problems.append(f"{at}: late {o.late}, reservations left {len(new['store'].reservations)}")
    return problems


def cards_summary(golden: dict[str, Any]) -> dict[str, Any]:
    world = cards_world()
    out: dict[str, Any] = {}
    for case, old in zip(CARD_CASES, golden["expected"]["cases"], strict=True):
        o = new_cards(world, case)["outcome"]
        out[case["name"]] = {"old": {"made": old["made"], "usd": old["usd"], "calls": len(old["calls"]),
                                     "model_writes": sum(1 for s in old["saves"] for c in s.values()
                                                         if (c or {}).get("generated_by") != "rules")},
                             "note": json.loads(news_cards.card_note("news-run", o))["cards"]}  # fmt: skip
    old_sha = hashlib.sha256(
        json.dumps([news_cards.OLD_SYSTEM], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    out["prompt_sha"] = {"old": old_sha[:16], "new": news_cards.PROMPT_SHA}
    return out


def cards_report(golden: dict[str, Any]) -> int:
    problems = compare_cards(golden)
    print(json.dumps({"golden": str(CARDS_GOLDEN), "bytes": CARDS_GOLDEN.stat().st_size, "old": golden["provenance"],
                      "summary": cards_summary(golden), "declared": CARDS_DECLARED}, ensure_ascii=False, indent=1))  # fmt: skip
    for p in problems[:80]:
        print("  DIFF", p)
    print("NEWS CARDS GOLDENS MATCH" if not problems else f"NEWS CARDS GOLDENS DIFFER ({len(problems)})")
    return 1 if problems else 0


def write_cards_goldens() -> int:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    inp = cards_input()
    world = cards_world()
    with tempfile.TemporaryDirectory(prefix="pz-news-cards-oracle-") as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        srcf, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
        srcf.write_bytes(json.dumps({**inp, "events": world}, ensure_ascii=False).encode("utf-8"))
        env = {k: v for k, v in os.environ.items()
               if k not in inference_config.KEY_ENVS and k != "SUPABASE_DB_URL" and not k.endswith(("_API_KEY", "_TOKEN"))}  # fmt: skip
        env.update({"PZ_DATA": str(data), "PZ_TESTING": "1", "PYTHONPATH": str(OLD_REPO / "backend" / "src"),
                    "PZ_AI_PAID": "on"})  # fmt: skip
        env.pop("PZ_SCOUT00_PAID", None)
        run = subprocess.run([str(python), str(CARDS_ORACLE), str(srcf), str(dst)], env=env, capture_output=True,
                             text=True)  # fmt: skip
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        oracle: dict[str, Any] = json.loads(dst.read_bytes().decode("utf-8"))
    golden = {"provenance": oracle["meta"], "input": js(inp), "world_sha": _sha(world), "expected": oracle}
    CARDS_GOLDEN.write_bytes((json.dumps(golden, ensure_ascii=False, indent=None) + "\n").encode("utf-8"))
    return cards_report(read_golden(CARDS_GOLDEN))


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
    from projectzero.news import store as news_store
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
            stored_events, stored_actions = news_store.events_doc(c, schema), news_store.actions_text(c, schema)
            stored_logs, stored_docs = news_store.log_texts(c, schema), news_store.documents(c, schema)

        def archived_lines(path: str) -> str:
            lines = re.split(r"\r\n|\r|\n", files.get(path, b"").decode("utf-8-sig"))
            if lines and lines[-1] == "":
                lines.pop()
            return "".join(f"{line}\n" for line in lines)

        # reviews 028b / 028c: the importer's backfills hold the archived events (key order, each record's own key
        # order), every archived action and run-log line byte for byte, and every run document in its key order
        if "news/events.json" in files:
            archived = json.loads(files["news/events.json"].decode("utf-8-sig"))
            if json.dumps(stored_events, ensure_ascii=False) != json.dumps(archived, ensure_ascii=False):
                problems.append("/news/events.json: the backfilled events differ from the archive")
        if stored_actions != archived_lines("news/actions.jsonl"):
            problems.append("/news/actions.jsonl: the backfilled lines differ from the archive")
        for path in news_store.LOGS.values():
            if stored_logs.get(path, "") != archived_lines(path):
                problems.append(f"/{path}: the backfilled lines differ from the archive")
        for path in news_store.DOCUMENTS:
            if path in files:
                want = json.dumps(json.loads(files[path].decode("utf-8-sig")), ensure_ascii=False)
                if json.dumps(stored_docs.get(path), ensure_ascii=False) != want:
                    problems.append(f"/{path}: the backfilled document differs from the archive")
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
    if mode == "writes-goldens":
        return write_writes_goldens()
    if mode == "writes-check":  # the stored writes golden against the new code (no oracle)
        return writes_report(read_golden(WRITES_GOLDEN))
    if mode == "refresh-goldens":
        return write_refresh_goldens()
    if mode == "refresh-check":  # the stored refresh golden against the new code (no oracle)
        return refresh_report(read_golden(REFRESH_GOLDEN))
    if mode == "cards-goldens":
        return write_cards_goldens()
    if mode == "cards-check":  # the stored cards golden against the new code (no oracle)
        return cards_report(read_golden(CARDS_GOLDEN))
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
