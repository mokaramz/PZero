"""The weekly sourcing update (review 019): the old ``domain/people.py::weekly_update``, ported mechanically at
revision 6c739b9. The clock and the three inputs are parameters instead of ``date.today()`` and file reads; the text,
its order and the 7-day window are unchanged. Pure logic, no I/O, nothing written.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from projectzero.conviction.records import records


def _get(d: dict[str, Any], pid: str | None) -> dict[str, Any] | None:
    """The old ``people.get``."""
    for p in records(d["people"], ("id",)):
        if isinstance(p, dict) and p.get("id") == pid:
            return p
    return None


def weekly_update(
    signals: list[dict[str, Any]],
    people: list[Any],
    events: list[dict[str, Any]],
    today: date,
    insight: str = "",
    question: str = "",
) -> str:
    """The old ``people.weekly_update``: ``signals`` are the stored Conviction records, ``people`` the people
    records, ``events`` the event records (all current, in archive order); ``today`` is the Berlin day of the
    request."""
    d = {"people": people}
    week_ago = today - timedelta(days=7)

    def recent(iso: Any) -> bool:
        try:
            return date.fromisoformat(str(iso)[:10]) >= week_ago
        except Exception:
            return False

    live = [e for e in signals if e.get("status") != "dropped"]
    found = [e for e in live if recent(e.get("discovery_date")) or recent(e.get("detected_on", ""))]
    sent = [e for e in live if recent(e.get("sent_to_omar", ""))]
    moved = [e for e in live if e.get("status") in ("contacted", "replied", "forwarded")]
    new_people = [p for p in records(d["people"], ("id",)) if recent(p.get("created")) and p["id"] != "p-omar-hedeya"]

    L = [f"Sourcing update — week of {today.isoformat()}", ""]
    if sent:
        L.append("Sent to you: " + "; ".join(f"{e['company']} ({e.get('location', '')})" for e in sent))
    if found:
        L.append("New this week: " + "; ".join(f"{e['company']} — {e.get('one_liner', '')[:70]}" for e in found[:5]))
    if moved:
        L.append("Pipeline: " + "; ".join(f"{e['company']} → {e['status']}" for e in moved))
    attended = [x for x in events if x.get("status") == "attended" and recent(x.get("start"))]
    if attended:
        L.append("Events attended: " + "; ".join(f"{x['name']} ({x.get('city', '')})" for x in attended))
    if new_people:

        def plabel(p: dict[str, Any]) -> str:
            base = p.get("company") or p.get("role") or ""
            if not base and p.get("introduced_by"):
                intro = _get(d, p["introduced_by"])
                base = "via " + intro.get("name", "?") if intro else ""
            return f"{p['name']}" + (f" ({base})" if base else "")

        L.append("People added: " + "; ".join(plabel(p) for p in new_people[:6]))
    if insight.strip():
        L.append("Observation: " + insight.strip())
    if question.strip():
        L.append("Question: " + question.strip())
    if len(L) == 2:
        L.append("Nothing that clears the bar this week — pipeline is in research, next update Friday.")
    L += ["", "Mohamed"]
    return "\n".join(L)
