"""Scout 00 event reports as the Events page shows them: the old ``domain/event_scout.py`` (rev 6c739b9), ported
VERBATIM with the clock as a parameter. Read-only.

``reports(scout_events, tracked, today)`` lists every Scout 00 event recommendation that is still open (NEW / MONITOR)
and not in the past, merges the same event reported by several cycles into one row (the Events dedup rule) and says
whether Events already tracks it. ``by_event(evs, scout_events)`` gives each tracked event its Scout 00 view.

The reports are the ``events`` of ``documents['scout_intake.json#rest']`` (review 014 kept them there, with
``event_id`` already stripped of the old ``|merged:`` suffix; ``by_event`` still splits it, as the old reader did).
Adding or dismissing a report (the old ``scout_event``) is a write: review 016.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from projectzero.events import engine
from projectzero.events import place as event_place
from projectzero.events.dedup import close_dates, paren_base, similar

UNKNOWN = "UNKNOWN"  # the old scout_intake.UNKNOWN
OPEN = ("NEW", "MONITOR")
_P_RANK = {"P1": 0, "P2": 1, "P3": 2}
_EV_RANK = {"EV-A": 0, "EV-B": 1, "EV-C": 2}


def report_records(rest: Any) -> list[dict[str, Any]]:
    """The Scout 00 event reports of the ``scout_intake.json#rest`` document (the old ``load().get("events") or []``;
    a record that is not an object is skipped where the old reader crashed)."""
    reports = rest.get("events") if isinstance(rest, dict) else None
    items = list(reports.values()) if isinstance(reports, dict) else reports if isinstance(reports, list) else []
    return [x for x in items if isinstance(x, dict)]


def _v(x: Any) -> str:
    s = str(x or "").strip()
    return "" if s == UNKNOWN else s


def same_event(a: str, day_a: str, b: str, day_b: str) -> bool:
    """The Events dedup rule: similar name (incl. a bracketed Scout annotation) and a date within a day."""
    return similar(a, b) and close_dates(day_a, day_b)


def _info(ev: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": ev["id"],
        "cycle_id": ev.get("cycle_id", ""),
        "status": ev.get("status", ""),
        "ev_class": _v(ev.get("ev_class")),
        "ax_class": _v(ev.get("ax_class")),
        "p_class": _v(ev.get("p_class")),
        "why": _v(ev.get("why_it_matters")),
        "action": _v(ev.get("required_action")),
        "url": _v(ev.get("official_url")),
    }


def _rank(x: dict[str, Any]) -> tuple[int, int]:
    return (_P_RANK.get(x["p_class"], 9), _EV_RANK.get(x["ev_class"], 9))


def _best(reps: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(reps, key=_rank)[0]


def by_event(evs: list[dict[str, Any]], scout_events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """event id -> the Scout 00 view of that event (every cycle that reported it, whatever its Scout Intake status).
    Linked by the id Scout Intake recorded when it was added, else by the Events dedup rule."""
    reps = [
        _info(x) | {"name": _v(x.get("event_name")), "date": _v(x.get("date"))[:10], "event_id": x.get("event_id", "")}
        for x in scout_events
        if _v(x.get("event_name"))
    ]
    out: dict[str, dict[str, Any]] = {}
    for e in evs:
        mine = [
            r
            for r in reps
            if (r["event_id"] and r["event_id"].split("|")[0] == e["id"])
            or same_event(r["name"], r["date"], e.get("name", ""), str(e.get("start") or "")[:10])
        ]
        if mine:
            b = _best(mine)
            out[e["id"]] = {
                "p_class": b["p_class"],
                "ev_class": b["ev_class"],
                "why": b["why"],
                "action": b["action"],
                "cycles": sorted({r["cycle_id"] for r in mine}),
            }
    return out


def reports(scout_events: list[dict[str, Any]], tracked: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """Open, not-past Scout 00 recommendations, one row per event. ``tracked``: the stored event records."""
    rows: list[dict[str, Any]] = []
    for ev in scout_events:
        if ev.get("status") not in OPEN:
            continue
        name, day = _v(ev.get("event_name")), _v(ev.get("date"))[:10]
        if not name:
            continue
        try:
            if day and date.fromisoformat(day) < today:
                continue
        except ValueError:
            day = ""
        report = _info(ev)
        row = next((r for r in rows if same_event(name, day, r["name"], r["date"])), None)
        if row is None:
            row = {"name": name, "date": day, "city": _v(ev.get("city")), "reports": []}
            rows.append(row)
        elif paren_base(name) == name and row["name"] != paren_base(row["name"]):
            row["name"] = name  # the plain event name, not Scout's annotated variant
        row["reports"].append(report)
    out = []
    for r in rows:
        reps = sorted(r["reports"], key=_rank)
        best = reps[0]
        match = next(
            (e for e in tracked if same_event(r["name"], r["date"], e.get("name", ""), str(e.get("start") or "")[:10])),
            None,
        )
        when = engine.event_when({"start": r["date"]}, today) if r["date"] else {"group": "undated", "days_until": None}
        pl = event_place.place({"city": r["city"]})
        hours = engine.city_hours(pl["city"])
        out.append(
            {
                "key": "scout-" + best["id"],
                "name": r["name"],
                "date": r["date"],
                "days_until": when.get("days_until"),
                "city": r["city"],
                "place": pl,
                "travel_hours": hours if hours is not None else engine.city_hours(pl["area"]),
                "ev_class": best["ev_class"],
                "p_class": best["p_class"],
                "why": best["why"],
                "action": best["action"],
                "url": next((x["url"] for x in reps if x["url"]), ""),
                "cycles": sorted({x["cycle_id"] for x in reps}),
                "report_ids": [x["id"] for x in reps],
                "statuses": sorted({x["status"] for x in reps}),
                "themes": event_place.themes({"name": r["name"], "description": " ".join(x["why"] for x in reps)}),
                "tracked_event_id": match["id"] if match else "",
            }
        )
    out.sort(key=lambda x: (_P_RANK.get(x["p_class"], 9), x["date"] or "9999", _EV_RANK.get(x["ev_class"], 9)))
    return out
