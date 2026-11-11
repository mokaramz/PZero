"""Where should I go, and the Sourcing Weekend: the old ``domain/ecosys.py`` ``where_should_i_go`` (:365-426),
``sourcing_weekend`` (:429-522) and ``_city_of`` (:349-354) (rev 6c739b9), ported VERBATIM. Read-only.

Inputs are the old ones, passed in: ``evs`` is ``engine.listing`` (the old ``events.listing()``), ``people`` the old
``people.listing()`` (``network.view.listing``), ``pins`` the persisted free-text dates (``engine.Pins``). The clock
is the one Berlin ``today`` of the request (review 015 (a)); the old functions read the machine's ``date.today()``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from projectzero.events import engine
from projectzero.events.place import normalize_city


def city_of(loc: Any) -> str:
    t = (loc or "").lower()
    for c in engine.GAZETTEER:
        if c.lower() in t:
            return normalize_city(c)[0]
    return ""


def where_should_i_go(
    evs: list[dict[str, Any]], people: list[dict[str, Any]], today: date, days: int = 14
) -> list[dict[str, Any]]:
    """Rank upcoming events by sourcing value per travel effort, with visible evidence.
    rank = EventScore * travel_factor + talent_bonus (+2 per open contact in that city, max 6)."""
    horizon = (today + timedelta(days=days)).isoformat()
    today_iso = today.isoformat()
    out = []
    for e in evs:
        w = e.get("when") or engine.event_when(e, today)
        st = w["start_date"]
        if not st or w["end_date"] < today_iso or st > horizon or e.get("status") == "skipped":
            continue  # span overlap with [today, horizon]: ongoing events count
        if (e.get("eligibility") or {}).get("tier") != "HIGH-SIGNAL":
            continue  # RC2: only high-signal (or operator-verified) events are recommendable
        if not (e.get("action") or {}).get("recommendable", True):
            continue  # RC2.1.3: sold out without an actionable waitlist is not recommendable
        hours = engine.city_hours(e.get("city", ""))
        travel = (
            1.0 if hours is None else (1.0 if hours <= 1 else 0.92 if hours <= 3.5 else 0.8 if hours <= 6 else 0.65)
        )
        contacts = [p for p in people if city_of(p.get("location", "")) == e.get("city") and p.get("next_action")]
        bonus = min(6, 2 * len(contacts))
        rank = round(e["sc"]["total"] * travel + bonus) if e["sc"]["total"] is not None else None  # unscorable: None
        reason = e["sc"]["why"]
        extra = []
        if hours is not None:
            extra.append(f"~{hours:g}h from Karlsruhe")
        if contacts:
            extra.append(f"{len(contacts)} open contact(s) there: " + ", ".join(p["name"] for p in contacts[:3]))
        out.append(
            {
                "id": e["id"],
                "name": e["name"],
                "city": e.get("city", ""),
                "start": st,
                "weekend": bool(w["weekend"]),
                "when": w,
                "type_label": engine.EVENT_TYPES.get(e.get("type", ""), ""),
                "event_score": e["sc"]["total"],
                "band": e["sc"]["band"],
                "rank": rank,
                "reason": reason,
                "extra": " · ".join(extra),
                "url": e.get("url", ""),
                "deadline": e.get("deadline", ""),
                "contacts": [p["name"] for p in contacts[:5]],
            }
        )
    out.sort(key=lambda x: (x["rank"] is None, -(x["rank"] or 0)))
    for i, o in enumerate(out):
        o["priority"] = (
            "NOT YET SCORABLE"
            if o["rank"] is None
            else "HIGH PRIORITY"
            if i == 0 and o["rank"] >= 70
            else ("WORTH THE TRIP" if o["rank"] >= 60 else "OPTIONAL")
        )
    return out


def _objective(e: Mapping[str, Any]) -> str:
    a = e.get("assessment") or {}
    if a.get("founder") in ("HIGH", "MEDIUM"):
        return "meet founders"
    return "validate a thesis" if a.get("project_a") in ("HIGH", "MEDIUM") else "meet the organizer"


def sourcing_weekend(
    evs: list[dict[str, Any]],
    people: list[dict[str, Any]],
    start_iso: str,
    end_iso: str,
    today: date,
    pins: Mapping[str, engine.Pins] | None = None,
) -> list[dict[str, Any]]:
    """Chain the best compatible events in ONE city inside the window + open Talent-Graph follow-ups there.
    Returns ranked city missions with a chronological plan. Network-density optimization, not tourism."""
    pinned = pins or {}
    window = [
        e
        for e in evs
        if engine.overlaps(e, start_iso, end_iso, today, pinned.get(e.get("id", "")))
        and e.get("status") != "skipped"
        and (e.get("eligibility") or {}).get("tier") == "HIGH-SIGNAL"
        and (e.get("action") or {}).get("recommendable", True)
    ]  # RC2: high-signal only; RC2.1.3: half-open overlap, no sold-out; empty -> honest empty state
    cities: dict[str, list[dict[str, Any]]] = {}
    for e in window:
        cities.setdefault(e.get("city") or "?", []).append(e)
    missions: list[dict[str, Any]] = []
    for city, ces in cities.items():
        ces.sort(key=lambda e: (e.get("start", ""), -(e["sc"]["total"] or 0)))
        contacts = [p for p in people if city_of(p.get("location", "")) == city]
        open_contacts = [p for p in contacts if p.get("next_action")]
        hours = engine.city_hours(city)
        plan: list[dict[str, Any]] = [
            {
                "when": e.get("start", ""),
                "what": e["name"],
                "why": e["sc"]["why"],
                "score": e["sc"]["total"],
                "url": e.get("url", ""),
                "time": (e.get("when") or {}).get("start_time") or "time unknown",
                "end_time": (e.get("when") or {}).get("end_time") or "",
                "venue": e.get("venue") or "venue unknown",
                "city": e.get("city", ""),
                "format": e.get("format", "UNKNOWN"),
                "price_state": e.get("price_state", "price unknown"),
                "price": e.get("price") or {},
                "registration_url": (e.get("action") or {}).get("url") or "",
                "action": e.get("action") or {},
                "organizer": e.get("organizer", "UNKNOWN"),
                "assessment": e.get("assessment"),
                "confidence": (e.get("assessment") or {}).get("confidence"),
                "unknowns": e.get("unknowns", []),
                "objective": _objective(e),
                "research_first": [e.get("organizer")] if e.get("organizer") not in (None, "", "UNKNOWN") else [],
            }
            for e in ces
        ]
        for p in open_contacts[:2]:
            plan.append(
                {
                    "when": end_iso,
                    "what": f"Coffee: {p['name']}",
                    "why": (p.get("next_action") or "").replace("SUGGESTED: ", ""),
                    "score": None,
                    "url": "",
                }
            )
        bands = [(e.get("assessment") or {}) for e in ces]
        strong = any(
            b.get("founder") == "HIGH" and b.get("confidence") in ("STRUCTURED, COMPLETE", "STRUCTURED") for b in bands
        )
        consider = any(
            b.get("founder") in ("HIGH", "MEDIUM") or b.get("project_a") in ("HIGH", "MEDIUM") for b in bands
        )
        strength = "Strong evidence" if strong else "Consider" if consider else "Weak evidence"
        reasons = [p["what"] + ": " + (p["why"] or "no source evidence") for p in plan]
        unknowns = sorted({u for p in plan for u in (p.get("unknowns") or [])})
        missions.append(
            {
                "city": city,
                "travel_hours": hours,
                "value": None,
                "strength": strength,
                "reasons": reasons,
                "unknowns": unknowns,
                "events": len(ces),
                "contacts": [p["name"] for p in open_contacts[:4]],
                "plan": plan,
                "expected": f"{len(ces)} scheduled event(s) · {len(open_contacts)} open contact(s) in {city} · travel "
                + (f"~{hours}h (city-table approximation)" if hours is not None else "time unknown")
                + " · objectives: "
                + ", ".join(sorted({p.get("objective", "") for p in plan if p.get("objective")}))
                + (" · missing: " + ", ".join(unknowns) if unknowns else ""),
            }
        )
    order = {"Strong evidence": 0, "Consider": 1, "Weak evidence": 2}
    missions.sort(key=lambda m: (order[m["strength"]], -(len(m["plan"]) + len(m["contacts"]))))
    return missions
