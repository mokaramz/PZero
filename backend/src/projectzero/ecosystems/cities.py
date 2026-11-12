# ruff: noqa: E501
"""The city registry and the city view (review 022): the old ``domain/ecosys.py`` ``_registry`` (:37-68),
``city_registry`` (:71-125), ``_city_of`` (:349-354), ``_load_signals`` (:357-361) and ``city_page`` (:562-633) at
revision 6c739b9, ported line for line.

The only changes: the inputs are parameters (the Conviction records, the Events LISTING as ``engine.listing`` gives
it, the people records, the ``ecosystems.json`` body or ``None``) and the clock is ``today`` (the Berlin day of the
request; the old code used the machine's ``date.today()``, decision c). The reused ports: ``conviction.taste``
(``score``, ``EARLINESS``), ``dealflow.ranking.names.slug`` (the old ``radar.slug``), ``events.engine``
(``GAZETTEER``, ``city_hours``, ``EVENT_TYPES``), ``events.place.normalize_city`` (the old ``geo_alias``) and
``network.view.listing`` (the old ``people.listing``). Kept quirk (decision b): an unknown ``earliness`` raises in
the city view, as before. Pure: no I/O.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from projectzero.conviction import taste
from projectzero.conviction.records import records
from projectzero.dealflow.ranking.names import slug as radar_slug
from projectzero.ecosystems import catalog
from projectzero.events import engine as evmod
from projectzero.events.place import normalize_city
from projectzero.network import view as ppl


def registry(eco_doc: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Curated ecosystem registry = built-in defaults + ecosystems.json (operator-extendable, no code changes)."""
    cities: list[dict[str, Any]] = [{"name": n, "country": ""} for n in catalog.CITIES]
    orgs = list(catalog.ORGS)
    try:
        d = {} if eco_doc is None else eco_doc  # the old storage.load_json(ECO_FILE_NAME, {})
        for x in d.get("cities", []):
            if x.get("name") and x["name"] not in [q["name"] for q in cities]:
                cities.append(
                    {
                        "name": x["name"],
                        "country": x.get("country", ""),
                        "note": x.get("note", ""),
                        "travel_hours": x.get("travel_hours"),
                    }
                )
        for o in d.get("institutions", []):
            if o.get("name") and o.get("city") and o.get("kind"):
                orgs.append(
                    {
                        "name": o["name"],
                        "kind": o["kind"],
                        "city": o["city"],
                        "lat": o.get("lat"),
                        "lng": o.get("lng"),
                        "why": o.get("why", ""),
                        "url": o.get("url", ""),
                    }
                )
    except Exception:
        pass
    return cities, orgs


def city_of(loc: str | None) -> str:
    t = (loc or "").lower()
    for c in evmod.GAZETTEER:
        if c.lower() in t:
            return normalize_city(c)[0]
    return ""


def load_signals(signals: Any) -> list[dict[str, Any]]:
    """The old ``_load_signals``: the Conviction records with a company (``real_data.json`` ``signals``)."""
    try:
        return records(signals, ("company",))
    except Exception:  # v1: a missing/unreadable pipeline simply shows no startups
        return []


def city_registry(signals: Any, events: list[dict[str, Any]], people: Any, eco_doc: Any, today: date) -> dict[str, Any]:
    """Two honest concepts: CURATED ecosystem intelligence (verified institutions, deeper pages) and DETECTED
    sourcing coverage (cities that actually appear in startup, event and people data). Coverage counts are real.

    ``events`` is the Events listing (``engine.listing``) at ``today``; ``people`` the person records."""
    cities, orgs = registry(eco_doc)
    curated = {x["name"]: dict(x, curated=True) for x in cities}
    sigs = load_signals(signals)
    evs = events
    plist = ppl.listing(ppl.records(people), today)
    cov: dict[str, dict[str, Any]] = {}

    def bump(city: Any, key: str, when: Any = "") -> None:
        if not city:
            return
        row = cov.setdefault(city, {"startups": 0, "events": 0, "people": 0, "institutions": 0, "last_refresh": ""})
        row[key] += 1
        if when and when > row["last_refresh"]:
            row["last_refresh"] = when[:10]

    for e in sigs:
        if e.get("status") != "dropped":
            bump(city_of(e.get("location", "")), "startups", e.get("discovery_date") or e.get("created") or "")
    for e in evs:
        if not e.get("past"):
            bump(e.get("city", ""), "events", (e.get("start") or "")[:10])
    for p in plist:
        bump(city_of(p.get("location", "")), "people", p.get("last_interaction") or p.get("created") or "")
    for o in orgs:
        bump(o.get("city", ""), "institutions")
    out = []
    for name in sorted(set(list(curated) + list(cov)), key=lambda n: (n not in curated, n)):
        row = cov.get(name, {"startups": 0, "events": 0, "people": 0, "institutions": 0, "last_refresh": ""})
        h = evmod.city_hours(name)
        out.append(
            {
                "name": name,
                "curated": name in curated,
                "country": curated.get(name, {}).get("country", ""),
                "travel_hours": h if h is not None else curated.get(name, {}).get("travel_hours"),
                "coverage": row,
                "status": {
                    "startups": "yes" if row["startups"] else "none",
                    "events": "yes" if row["events"] else "none",
                    "people": "yes" if row["people"] else "none",
                    "institutions": "verified" if row["institutions"] else "none",
                },
            }
        )
    return {
        "cities": out,
        "curated_count": len(curated),
        "detected_count": sum(1 for x in out if not x["curated"]),
        "note": "Curated cities have verified institutions and deeper pages. Detected cities appear in real startup, event or people data "
        "and get the same page with honest counts. The Ecosystems page never limits the sourcing engine: the 45-source startup "
        "registry, event sources and people data cover any geography their sources return.",
    }


def eco_view(
    city: Any, signals: Any, events: list[dict[str, Any]], people: Any, eco_doc: Any, today: date
) -> dict[str, Any]:
    """The old ``city_page(city)`` (``GET /api/eco?city=``; the route defaulted an empty city to Karlsruhe)."""
    sigs = load_signals(signals)
    evs = events
    plist = ppl.listing(ppl.records(people), today)
    today_iso = today.isoformat()
    st = []
    for e in sigs:
        if e.get("status") == "dropped" or city_of(e.get("location", "")) != city:
            continue
        sc = taste.score(e)
        st.append(
            {
                "slug": radar_slug(e["company"]),
                "company": e["company"],
                "one_liner": e.get("one_liner", ""),
                "score": sc["verified"] if sc["fully_verified"] else sc["provisional"],
                "verified": sc["fully_verified"],
                "stage": taste.EARLINESS.get(e.get("earliness", "unknown"))[0],  # type: ignore[index]  # raises, as before
                "sent": e.get("sent_to_omar", ""),
            }
        )
    ces = [
        {
            "id": e["id"],
            "name": e["name"],
            "start": e.get("start", ""),
            "score": e["sc"]["total"],
            "band": e["sc"]["band"],
            "past": e["past"],
            "type_label": evmod.EVENT_TYPES.get(e.get("type", ""), ""),
        }
        for e in evs
        if e.get("city") == city
    ]
    pl = [
        {
            "id": p["id"],
            "name": p["name"],
            "role": p.get("role", ""),
            "company": p.get("company", ""),
            "strength": p.get("relationship_strength", ""),
            "next_action": p.get("next_action", ""),
        }
        for p in plist
        if city_of(p.get("location", "")) == city
    ]
    _cities, _orgs = registry(eco_doc)
    orgs = [o for o in _orgs if o["city"] == city]
    h = evmod.city_hours(city)
    note = catalog.CITY_NOTES.get(city, "")
    upcoming = sorted([c for c in ces if (c["start"] or "")[:10] >= today_iso], key=lambda c: c["start"])
    return {
        "city": city,
        "travel_hours": h,
        "note": note,
        "startups": sorted(st, key=lambda x: -x["score"]),
        "events_upcoming": upcoming,
        "events_past": [c for c in ces if c not in upcoming][:6],
        "people": pl,
        "orgs": orgs,
    }
