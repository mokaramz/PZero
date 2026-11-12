"""The Map pins (review 025): the old ``GET /api/map`` (``api/routers/home.py`` :64-166) and the old
``events.geocode_location`` / ``enrich_signals_with_geo`` (``domain/events.py`` :1210-1229) at revision 6c739b9,
ported line for line as PURE functions over ``MapInputs``.

The only changes:

* **Reads never write** (decision a). The old route filled missing ``lat`` / ``lng`` on the stored Conviction records
  from their location and saved ``real_data.json``. Here ``enrich_signals_with_geo`` runs on shallow COPIES of the
  records (so does ``safe_score``'s ``data_warning``): the answer carries the geocoded coordinates exactly as the old
  answer did, and ``inputs.signals`` is never modified.
* **``new_signals``** (decision c): the answer gains the old ``ecosys.home()`` count, the inbox candidates (with an
  id) whose ``decision`` is ``"new"``.
* **One clock**: ``today`` (the Berlin day) for the ``event_when`` fallback (the old one read the machine clock).
* The skip counters (``compat.each`` / ``compat.records`` logging) are not ported.

Kept (decision e): the institutions are the 24 static ``ORGS`` only (no ``ecosystems.json`` ones); a person pin has no
``city``; the operator (``OPERATOR_ID``) is never a pin. Reused ports: ``events.engine`` (``GAZETTEER``,
``EVENT_TYPES``, ``event_when``), ``conviction.records.safe_score``, ``conviction.taste``,
``dealflow.ranking.names.slug`` (the old ``radar.slug``) and ``ecosystems.catalog.ORGS``. Pure: no I/O.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import date
from typing import Any

from projectzero.conviction import taste
from projectzero.conviction.records import list_, records, safe_score
from projectzero.dealflow.ranking.names import slug
from projectzero.ecosystems.catalog import ORGS
from projectzero.events import engine
from projectzero.map import catalog
from projectzero.map.inputs_model import MapInputs

DEFAULT_HOME_BASE = catalog.DEFAULT_HOME_BASE
OPERATOR_ID = catalog.OPERATOR_ID


def geocode_location(loc: Any) -> tuple[float, float] | None:
    """Match a free-text location against the gazetteer. Returns (lat, lng) or None."""
    t = (loc or "").lower()
    for city, (lat, lng, _h) in engine.GAZETTEER.items():
        if city.lower() in t:
            return lat, lng
    return None


def enrich_signals_with_geo(signals: Any) -> int:
    """Add lat/lng to pipeline entries from their location string. Returns count changed. (MUTATES ``signals``'
    records: ``map_view`` calls it on copies only.)"""
    n = 0
    for e in signals:
        if isinstance(e, dict) and e.get("lat") is None:  # a non-record entry is left as stored, never fatal
            g = geocode_location(e.get("location") if isinstance(e.get("location"), str) else "")
            if g:
                e["lat"], e["lng"] = g
                n += 1
    return n


def _each[T](seq: Any, fn: Callable[[Any], T]) -> list[T]:
    """The old ``compat.each``: ``[fn(r) for r in seq]`` where a record that makes ``fn`` raise is skipped."""
    out: list[T] = []
    for r in seq:
        try:
            out.append(fn(r))
        except Exception:
            continue
    return out


def _startup_pin(e: dict[str, Any]) -> dict[str, Any]:
    sc = safe_score(e)  # a legacy value is read as neutral on a copy, never stops the Map
    a = taste.ARCHETYPE_BY_ID.get(e.get("archetype") or 0)
    return {
        "slug": slug(e["company"]),
        "company": e["company"],
        "lat": e["lat"],
        "lng": e["lng"],
        "stage": e.get("earliness", "unknown"),
        "stage_label": (taste.EARLINESS.get(e.get("earliness", "unknown")) or taste.EARLINESS["unknown"])[0],
        "score": sc["verified"] if sc["fully_verified"] else sc["provisional"],
        "verified": sc["fully_verified"],
        "archetype": (f"#{a[0]} {a[1]}" if a else ""),
        "one_liner": e.get("one_liner", ""),
        "location": e.get("location", ""),
        "funding": e.get("funding_status", ""),
        "timing": sc["timing_label"],
        "sent_to_omar": e.get("sent_to_omar", ""),
        "conflict": e.get("conflict", "none"),
        "why": e.get("why_project_a", ""),
        "founders": ", ".join(
            str(f.get("name", "")) if isinstance(f, dict) else str(f) for f in list_(e.get("founders"))
        ),
    }


def _event_pin(x: dict[str, Any], today: date) -> dict[str, Any]:
    return {
        "id": x["id"],
        "name": x["name"],
        "lat": x.get("lat"),
        "lng": x.get("lng"),
        "city": x.get("city", ""),
        "start": x.get("start", ""),
        "type": x.get("type", ""),
        "type_label": engine.EVENT_TYPES.get(x.get("type", ""), ""),
        "when": x.get("when") or engine.event_when(x, today),
        "score": x["sc"]["total"] or 0,
        "band": x["sc"]["band"],
        "why": x["sc"]["why"],
        "url": x.get("url", ""),
        "deadline": x.get("deadline", ""),
        "organizer": x.get("organizer", ""),
        "audience": x.get("audience_estimate", ""),
        "status": x.get("status", "new"),
        "past": x["past"],
    }


def _person_pin(pp: dict[str, Any], g: tuple[float, float]) -> dict[str, Any]:
    return {
        "id": pp["id"],
        "name": pp["name"],
        "lat": g[0],
        "lng": g[1],
        "role": pp.get("role", ""),
        "company": pp.get("company", ""),
        "why": pp.get("why_interesting", ""),
        "strength": pp.get("relationship_strength", ""),
        "potential": pp.get("founder_potential", "none"),
        "next_action": pp.get("next_action", ""),
        "watch": bool(pp.get("watch")),
    }


def new_signals(inbox: Any) -> int:
    """The old ``ecosys.home()`` ``new_signals``: inbox candidates (with an id) whose decision is ``"new"``."""
    return len([c for c in records(inbox, ("id",)) if c.get("decision") == "new"])


def map_view(inputs: MapInputs, today: date) -> dict[str, Any]:
    """``GET /api/map/pins`` (the old ``GET /api/map``): startups, events, people and institutions with coordinates.
    Geocodes the Conviction records IN MEMORY (decision a); the stored records are never modified."""
    signals = inputs.signals
    if isinstance(signals, list):  # copies: the old code geocoded (and saved) the stored records themselves
        signals = [dict(e) if isinstance(e, dict) else e for e in signals]
        enrich_signals_with_geo(signals)
    live = [e for e in records(signals, ("company",)) if e.get("status") != "dropped"]
    startups = _each([e for e in live if e.get("lat") is not None], _startup_pin)
    evs = inputs.events
    evo = _each([x for x in evs if isinstance(x, dict) and x.get("lat") is not None], lambda x: _event_pin(x, today))

    def person(pp: dict[str, Any]) -> dict[str, Any] | None:
        g = geocode_location(pp.get("location", ""))
        return _person_pin(pp, g) if g and pp.get("id") != OPERATOR_ID else None

    plist = inputs.people
    pgeo = [x for x in _each(plist, person) if x]
    no_geo = [e["company"] for e in live if e.get("lat") is None]
    return {
        "startups": startups,
        "events": evo,
        "people": pgeo,
        "orgs": copy.deepcopy(ORGS),
        "home": inputs.home_base or DEFAULT_HOME_BASE,
        "no_geo": no_geo,
        "new_signals": new_signals(inputs.inbox),
    }
