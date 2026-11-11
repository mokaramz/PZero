"""The Events read payloads (review 015): the old ``api/routers/events.py`` ``list_events`` / ``event_health`` /
``event_suggest`` and ``api/routers/home.py`` ``wsig`` / ``weekend`` bodies (rev 6c739b9), from ``store.EventsData``
and ONE Berlin ``today`` per request. Pure.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from projectzero.events import catalog, engine, plans, scout
from projectzero.events.store import EventsData
from projectzero.events.when import BERLIN
from projectzero.network import view as people_view

SOURCE_KINDS = ("luma", "jsonld", "api", "ics", "watcher")


def berlin_today(now: datetime) -> date:
    """The Berlin calendar date of the request instant (a naive instant is read as Berlin wall time)."""
    return (now if now.tzinfo else now.replace(tzinfo=BERLIN)).astimezone(BERLIN).date()


def _listing(data: EventsData, today: date) -> list[dict[str, Any]]:
    return engine.listing(data.events, today, data.source_city(), data.pins)


def events_payload(data: EventsData, today: date) -> dict[str, Any]:
    """The old ``GET /api/events``."""
    evs = _listing(data, today)
    scout_events = scout.report_records(data.documents.get("scout_intake.json#rest"))
    by_event = scout.by_event(evs, scout_events)
    for e in evs:
        e["scout"] = by_event.get(e["id"])  # Scout 00's recommendation for this event, when it reported it
    sat, sun = engine.weekend_window(today)
    health_sources = data.health().get("sources", [])
    return {
        "events": evs,
        "leads": [lead for lead in data.leads if lead.get("decision") == "new"],
        "weekend_window": [sat.isoformat(), sun.isoformat()],
        "today": today.isoformat(),
        "types": engine.EVENT_TYPES,
        "dims": {k: {"label": v["label"], "max": v["max"], "ladder": v["ladder"]} for k, v in engine.DIMS.items()},
        "dim_order": engine.DIM_ORDER,
        "manual_sources": catalog.MANUAL_EVENT_SOURCES,
        "pages": [x["name"] for x in catalog.EVENT_PAGES],
        "scout_reports": scout.reports(scout_events, data.events, today),  # not yet decided (read-only)
        "source_count": {k: sum(1 for s in health_sources if s.get("kind") == k) for k in SOURCE_KINDS},
    }


def suggest_payload(params: Iterable[tuple[str, str]]) -> dict[str, Any]:
    """The old ``GET /api/event_suggest``: the draft's fields as query params, the first non-blank value of each."""
    body: dict[str, str] = {}
    for k, v in params:
        if v != "" and k not in body:
            body[k] = v
    return {"parts": engine.suggest(body)}


def wsig_payload(data: EventsData, today: date, days: int) -> dict[str, Any]:
    """The old ``GET /api/wsig``."""
    people = people_view.listing(data.people, today)
    return {"ranked": plans.where_should_i_go(_listing(data, today), people, today, days)}


def weekend_payload(data: EventsData, today: date, start: str, end: str) -> dict[str, Any]:
    """The old ``POST /api/weekend`` (it never wrote; a GET here)."""
    people = people_view.listing(data.people, today)
    return {"missions": plans.sourcing_weekend(_listing(data, today), people, start, end, today, data.pins)}
