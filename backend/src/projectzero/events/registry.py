"""The event-source registry (review 017): the old ``domain/event_sources.py`` ``DEFAULT_SOURCES`` (:33-306),
``_repair`` (:308-322), ``NEW_DEFAULTS`` / ``_offer_new`` (:325-338) and ``load_sources`` (:341-351) (rev 6c739b9).

The registry lives in ``documents['event_sources.json']`` (the imported document). The old ``load_sources`` repaired
it and offered new default sources ON READ (writing the file); here ``prepare`` is pure and runs at the start of a
scan, BEFORE fetching, so a newly offered source takes part in that scan, and the scan writes the repaired document
together with its results (Codex H-113). Nothing else ever writes it. ``DEFAULT_SOURCES`` is the old table, copied
mechanically (data, not logic).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from projectzero.events.when import BERLIN

DEFAULT_SOURCES: list[dict[str, Any]] = [
    {
        "id": "ev-devpost",
        "name": "Devpost hackathons (public API)",
        "kind": "api",
        "url": "https://devpost.com/api/hackathons?page=1",
        "city": "",
        "organizer": "Devpost (aggregator)",
    },
    {
        "id": "ev-cyberforum",
        "name": "CyberForum Karlsruhe — Veranstaltungen",
        "kind": "jsonld",
        "url": "https://www.cyberforum.de/veranstaltungen/",
        "city": "Karlsruhe",
        "organizer": "CyberForum e.V.",
    },
    {
        "id": "ev-kit",
        "name": "KIT — events",
        "kind": "jsonld",
        "url": "https://www.kit.edu/kit/english/events.php",
        "city": "Karlsruhe",
        "organizer": "KIT",
    },
    {
        "id": "ev-utum",
        "name": "UnternehmerTUM — events",
        "kind": "jsonld",
        "url": "https://www.unternehmertum.de/en/events",
        "city": "Munich",
        "organizer": "UnternehmerTUM",
    },
    {
        "id": "ev-startupautobahn",
        "name": "STARTUP AUTOBAHN (Stuttgart) — events",
        "kind": "jsonld",
        "url": "https://startup-autobahn.com/events/",
        "city": "Stuttgart",
        "organizer": "STARTUP AUTOBAHN powered by Plug and Play",
    },
    {
        "id": "ev-techquartier",
        "name": "TechQuartier Frankfurt — events",
        "kind": "jsonld",
        "url": "https://techquartier.com/events/",
        "city": "Frankfurt",
        "organizer": "TechQuartier",
    },
    {
        "id": "ev-highest-da",
        "name": "HIGHEST / TU Darmstadt — events",
        "kind": "jsonld",
        "url": "https://www.highest.tu-darmstadt.de/veranstaltungen/",
        "city": "Darmstadt",
        "organizer": "HIGHEST (TU Darmstadt)",
    },
    {
        "id": "ev-ethec",
        "name": "ETH Entrepreneur Club — events",
        "kind": "jsonld",
        "url": "https://www.entrepreneur-club.org/events",
        "city": "Zürich",
        "organizer": "ETH Entrepreneur Club",
    },
    {
        "id": "ev-epfl",
        "name": "EPFL — innovation events",
        "kind": "jsonld",
        "url": "https://www.epfl.ch/innovation/events/",
        "city": "Lausanne",
        "organizer": "EPFL",
    },
    {
        "id": "ev-basel",
        "name": "Basel Area — events",
        "kind": "jsonld",
        "url": "https://baselarea.swiss/events/",
        "city": "Basel",
        "organizer": "Basel Area Business & Innovation",
    },
    {
        "id": "ev-geneva",
        "name": "Fongit Geneva — events",
        "kind": "jsonld",
        "url": "https://www.fongit.ch/events/",
        "city": "Geneva",
        "organizer": "Fongit",
    },
    {
        # Paris / STATION F territory: the events page is plain HTML without schema.org Event JSON-LD (verified
        # 2026-10-05), so the jsonld parser could never extract an event — a page watcher produces review-required leads.
        "id": "ev-stationf",
        "name": "Station F — events (page watcher)",
        "kind": "watcher",
        "url": "https://stationf.co/events",
        "city": "Paris",
        "organizer": "Station F",
    },
    {
        "id": "ev-yes-delft",
        "name": "YES!Delft — events",
        "kind": "jsonld",
        "url": "https://www.yesdelft.com/events/",
        "city": "Delft",
        "organizer": "YES!Delft",
    },
    {
        "id": "ev-htc-eindhoven",
        "name": "High Tech Campus Eindhoven — events",
        "kind": "jsonld",
        "url": "https://www.hightechcampus.com/events",
        "city": "Eindhoven",
        "organizer": "High Tech Campus Eindhoven",
    },
    {
        "id": "ev-bitsandpretzels",
        "name": "Bits & Pretzels",
        "kind": "jsonld",
        "url": "https://www.bitsandpretzels.com/",
        "city": "Munich",
        "organizer": "Bits & Pretzels",
    },
    {
        "id": "ev-startglobal",
        "name": "START Global (St. Gallen)",
        "kind": "jsonld",
        "url": "https://www.startglobal.org/",
        "city": "St. Gallen",
        "organizer": "START Global",
    },
    {
        "id": "ev-mlh",
        "name": "MLH 2026 season",
        "kind": "jsonld",
        "url": "https://mlh.io/seasons/2026/events",
        "city": "",
        "organizer": "Major League Hacking",
    },
    {
        "id": "ev-luma-munich",
        "name": "Luma — Munich",
        "kind": "luma",
        "url": "https://lu.ma/munich",
        "city": "Munich",
        "organizer": "UNKNOWN",
    },
    {
        "id": "ev-luma-berlin",
        "name": "Luma — Berlin",
        "kind": "luma",
        "url": "https://lu.ma/berlin",
        "city": "Berlin",
        "organizer": "UNKNOWN",
    },
    {
        "id": "ev-luma-zurich",
        "name": "Luma — Zürich",
        "kind": "luma",
        "url": "https://lu.ma/zurich",
        "city": "Zürich",
        "organizer": "UNKNOWN",
    },
    {
        "id": "ev-luma-paris",
        "name": "Luma — Paris",
        "kind": "luma",
        "url": "https://lu.ma/paris",
        "city": "Paris",
        "organizer": "UNKNOWN",
    },
    {
        "id": "ev-luma-amsterdam",
        "name": "Luma — Amsterdam",
        "kind": "luma",
        "url": "https://lu.ma/amsterdam",
        "city": "Amsterdam",
        "organizer": "UNKNOWN",
    },
    {
        "id": "ev-luma-frankfurt",
        "name": "Luma — Frankfurt",
        "kind": "luma",
        "url": "https://lu.ma/frankfurt",
        "city": "Frankfurt",
        "organizer": "UNKNOWN",
    },
    # 2026-11-10 coverage audit: no Nordic / UK source existed, so Slush week (Helsinki) and the Nordic ecosystems were
    # invisible. Same Luma JSON-LD route as the city pages above; added to existing installs once (see _offer_new).
    {
        "id": "ev-luma-helsinki",
        "name": "Luma — Helsinki",
        "kind": "luma",
        "url": "https://lu.ma/helsinki",
        "city": "Helsinki",
        "organizer": "UNKNOWN",
    },
    {
        "id": "ev-luma-slush",
        "name": "Luma — Slush week (Helsinki side events)",
        "kind": "luma",
        "url": "https://lu.ma/slush",
        "city": "Helsinki",
        "organizer": "UNKNOWN",
    },
    {
        "id": "ev-luma-stockholm",
        "name": "Luma — Stockholm",
        "kind": "luma",
        "url": "https://lu.ma/stockholm",
        "city": "Stockholm",
        "organizer": "UNKNOWN",
    },
    {
        "id": "ev-luma-copenhagen",
        "name": "Luma — Copenhagen",
        "kind": "luma",
        "url": "https://lu.ma/copenhagen",
        "city": "Copenhagen",
        "organizer": "UNKNOWN",
    },
    {
        "id": "ev-luma-london",
        "name": "Luma — London",
        "kind": "luma",
        "url": "https://lu.ma/london",
        "city": "London",
        "organizer": "UNKNOWN",
    },
    {
        "id": "ev-pioniergarage",
        "name": "Pioniergarage Karlsruhe (page watcher)",
        "kind": "watcher",
        "url": "https://pioniergarage.de/",
        "city": "Karlsruhe",
        "organizer": "Pioniergarage",
    },
    {
        "id": "ev-google",
        "name": "Google for Startups events (page watcher)",
        "kind": "watcher",
        "url": "https://startup.google.com/events/",
        "city": "",
        "organizer": "Google for Startups",
    },
    {
        "id": "ev-luma-ics",
        "name": "Luma calendar ICS (your subscriptions)",
        "kind": "ics",
        "url": "",
        "city": "",
        "organizer": "UNKNOWN",
        "requires_config": "Paste an api.lu.ma/ics/get?… URL into event_sources.json (calendar → Subscribe).",
    },
    {
        "id": "ev-meetup",
        "name": "Meetup API",
        "kind": "optional",
        "url": "https://www.meetup.com/api/",
        "city": "",
        "organizer": "UNKNOWN",
        "requires_config": "Meetup Pro API key / OAuth — not configured. Manual search stays available.",
    },
    {
        "id": "ev-eventbrite",
        "name": "Eventbrite API",
        "kind": "optional",
        "url": "https://www.eventbrite.com/platform/api",
        "city": "",
        "organizer": "UNKNOWN",
        "requires_config": "Eventbrite private token — not configured. Manual search stays available.",
    },
]


# Default sources added after first release. Each is offered to an existing install ONCE (recorded in
# ``offered_defaults``): a source the operator later removes is never re-added.
NEW_DEFAULTS = ["ev-luma-helsinki", "ev-luma-slush", "ev-luma-stockholm", "ev-luma-copenhagen", "ev-luma-london"]


def _repair(sources: list[dict[str, Any]]) -> bool:
    """Idempotent fixes for existing installs. STATION F: stationf.co/events has no schema.org Event JSON-LD, so a
    ``jsonld`` source could never extract an event; switch exactly that source to the page ``watcher`` kind."""
    changed = False
    for s in sources:
        if s.get("id") == "ev-stationf" and s.get("kind") == "jsonld" and "stationf.co/events" in str(s.get("url", "")):
            s["kind"] = "watcher"
            s["name"] = "Station F — events (page watcher)"
            s["repair_note"] = "2026-10-05: switched jsonld → watcher (page has no JSON-LD Event data)"
            changed = True
    return changed


def _offer_new(d: dict[str, Any], now: datetime) -> bool:
    offered = d.setdefault("offered_defaults", [])
    have = {s.get("id") for s in d["sources"]}
    changed = False
    for src in DEFAULT_SOURCES:
        if src["id"] in NEW_DEFAULTS and src["id"] not in offered:
            if src["id"] not in have:
                added = now.astimezone(BERLIN).strftime("%Y-%m-%d")
                d["sources"].append(dict(src, added_note=added + ": new default source"))
            offered.append(src["id"])
            changed = True
    return changed


@dataclass
class Registry:
    sources: list[dict[str, Any]]
    document: dict[str, Any]  # what the scan writes back
    changed: bool  # the document must be written (repaired, offered, or created from the defaults)


def prepare(stored: Any, now: datetime) -> Registry:
    """The old ``load_sources`` without its write: a usable stored registry is repaired and offered the new defaults;
    a missing, empty or unreadable one is the defaults (the old app rewrote the file from them)."""
    if isinstance(stored, dict) and stored.get("sources"):
        d = copy.deepcopy(stored)
        changed = _repair(d["sources"]) | _offer_new(d, now)
        return Registry([s for s in d["sources"] if isinstance(s, dict)], d, changed)
    d = {"sources": copy.deepcopy(DEFAULT_SOURCES), "offered_defaults": list(NEW_DEFAULTS)}
    return Registry(copy.deepcopy(DEFAULT_SOURCES), d, True)
