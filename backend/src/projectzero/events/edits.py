"""The Events write rules (review 016), pure: what a save, a verify, a lead decision, a debrief and a Scout 00 action
do to records. The store (``events.writes``) runs them inside ONE transaction under its locks.

Old source (rev 6c739b9): ``domain/events.py`` ``_slug`` (:349), ``EVENT_FIELDS`` (:354), ``_add_provenance``
(:376-383), ``upsert`` (:386-427), ``decide_lead`` (:1132), ``debrief`` (:1140-1207); ``api/routers/events.py``
(``event_save`` / ``event_verify`` / ``event_lead`` / ``event_debrief``); ``domain/scout_intake.py`` ``event_action``
(:1524-1560).

Changed on purpose (review 016, approved by Codex H-107):

* (a) **A slug collision is not a silent overwrite.** The old ``upsert`` used ``id = body.id or slug(name, start)``; an
  add whose slug existed skipped the merge and overwrote the stored fields. Here it is a merge (fill gaps only, keep
  every source, ``id|merged:<name>``) when the evidence agrees, and a 409 with the existing id when it conflicts (a
  different city or country for the same name and date). The fuzzy merge never folds an event into one whose
  evidence conflicts either; it tries the next similar event, else creates a new one.
* (b) **An edit of an unknown id is a 404** and creates nothing (the old code created an event with that id).
* (c) **A debrief never overwrites a person** (``network.store`` links an existing person; see ``writes``).
* (d) **Debrief startup leads go through Deal Flow intake** (``lead_entities``): per-lead evidence URL, else the
  event's URL; a lead without a valid public URL refuses the WHOLE debrief before anything is written.
* (e) **Lead decisions** outside ``new | dismissed | converted`` are a 400; an unknown lead is a 404.
* (g) **One Berlin clock**: ``created``, ``sources[].added``, ``human_verified_on``, ``last_interaction`` and the Scout
  ``history[].on`` come from the request instant (the old code read the machine's clock).

Input types the old code crashed on (500) are refused as 400: a non-text ``id`` / ``name`` / ``start`` / ``city``,
``people_met`` / ``leads`` that are not lists of objects.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from projectzero.events.columns import LEAD_DECISIONS
from projectzero.events.dedup import close_dates, similar
from projectzero.events.engine import GAZETTEER
from projectzero.events.place import normalize_city

EVENT_FIELDS = [
    "name", "type", "organizer", "start", "end", "city", "venue", "url", "deadline", "price", "audience_estimate",
    "domains", "notes", "status", "score_parts", "lat", "lng", "source",
]  # fmt: skip

NAME_REQUIRED = "event name required"
UNKNOWN_EVENT = "unknown event — nothing was saved"
UNKNOWN_LEAD = "unknown event lead — nothing was changed"
COLLISION = (
    "an event with this name and date already exists with different details ({why}) — open the existing event to "
    "edit it; nothing was saved"
)
BAD_DECISION = "decision must be one of new, dismissed, converted"
UNKNOWN_SCOUT = "unknown scout event"
UNKNOWN_SCOUT_ACTION = "unknown event action"
SCOUT_LABEL = "Scout Intake"  # the old scout_intake.LABEL
UNKNOWN_VALUE = "UNKNOWN"  # the old scout_intake.UNKNOWN


class EventsError(ValueError):
    def __init__(self, status: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.extra = extra


def _is_text(v: Any) -> bool:
    return v is None or isinstance(v, str)


def slug_id(name: Any, start: Any) -> str:
    """The old ``_slug``: ``ev-<name slug, 36 chars>-<the first 10 chars of start>``."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "event").lower()).strip("-")[:36]
    return f"ev-{s}-{(start or '')[:10]}"


# ── event_save ──────────────────────────────────────────────────────────────────────────────────────────────────
def validate_save(body: Mapping[str, Any]) -> None:
    """The old route's ``event name required`` plus the types the old code crashed on."""
    for key in ("id", "name", "start", "city", "convert_lead"):
        if key in body and not _is_text(body[key]):
            raise EventsError(400, f"{key} must be text")
    if not body.get("id") and not str(body.get("name") or "").strip():  # no nameless events (old audit 2026-11-08)
        raise EventsError(400, NAME_REQUIRED)


def add_provenance(ev: dict[str, Any], body: Mapping[str, Any], today: date) -> None:
    """Every write records where the data came from; merges preserve ALL sources (the old ``_add_provenance``)."""
    src, url = body.get("source") or "", body.get("url") or ""
    if not (src or url):
        return
    ev.setdefault("sources", [])
    if not any(s.get("source") == src and s.get("url") == url for s in ev["sources"]):
        ev["sources"].append({"source": src or "manual", "url": url, "added": today.isoformat()})


def conflicts(stored: Mapping[str, Any], body: Mapping[str, Any]) -> list[str]:
    """Evidence that two records with the same name and date are NOT the same event: a different city or country
    (each compared only when both state one; city aliases and the stated countries are normalised)."""
    out = []
    a_city, a_cc, _ = normalize_city(stored.get("city") or "", stored.get("country") or "")
    b_city, b_cc, _ = normalize_city(body.get("city") or "", body.get("country") or "")
    if a_city and b_city and a_city.casefold() != b_city.casefold():
        out.append(f"city {a_city} vs {b_city}")
    if a_cc and b_cc and a_cc != b_cc:
        out.append(f"country {a_cc} vs {b_cc}")
    return out


def new_event(eid: str, today: date) -> dict[str, Any]:
    return {"id": eid, "status": "new", "created": today.isoformat(), "people_met": [], "outcomes": "", "sources": []}


def merge_into(target: dict[str, Any], body: Mapping[str, Any], today: date) -> None:
    """The old merge: keep every source; fill gaps only, never overwrite what is stored."""
    add_provenance(target, body, today)
    for k in EVENT_FIELDS:
        if body.get(k) and not target.get(k):
            target[k] = copy.deepcopy(body[k])


def apply_fields(ev: dict[str, Any], body: Mapping[str, Any], today: date) -> None:
    """The old write of a save: provenance, every ``EVENT_FIELDS`` key the body carries, the gazetteer coordinates."""
    add_provenance(ev, body, today)
    for k in EVENT_FIELDS:
        if k in body:
            ev[k] = copy.deepcopy(body[k])
    fill_coordinates(ev)


def fill_coordinates(ev: dict[str, Any]) -> None:
    city = ev.get("city")
    if isinstance(city, str) and city in GAZETTEER and not ev.get("lat"):
        ev["lat"], ev["lng"] = GAZETTEER[city][0], GAZETTEER[city][1]


def plan_save(body: Mapping[str, Any], by_id: Mapping[str, dict[str, Any]], order: list[str]) -> tuple[str, str, str]:
    """Which record a save writes: ``(kind, event id, merged-into name)``, kind one of ``edit`` | ``create`` |
    ``merge``. ``by_id`` / ``order``: the stored records and their stored order (the old file order). Raises 404 (b)
    and 409 (a)."""
    if body.get("id"):
        eid = str(body["id"])
        if eid not in by_id:
            raise EventsError(404, UNKNOWN_EVENT, id=eid)
        return "edit", eid, ""
    eid = slug_id(body.get("name", ""), body.get("start", ""))
    if eid in by_id:  # (a) the generated id is taken: a merge when the evidence agrees, else a refusal
        if why := conflicts(by_id[eid], body):
            raise EventsError(409, COLLISION.format(why="; ".join(why)), id=eid, collision=True)
        return "merge", eid, str(by_id[eid].get("name", ""))
    for xid in order:  # the old fuzzy dedup: the same event from several sources is ONE event
        x = by_id[xid]
        if similar(body.get("name", ""), x.get("name", "")) and close_dates(body.get("start", ""), x.get("start", "")):
            if conflicts(x, body):
                continue  # (a) similar wording, different place: not the same event
            return "merge", xid, str(x.get("name", ""))
    return "create", eid, ""


def answer_id(eid: str, merged_into: str) -> str:
    """The old answer: ``id``, or ``id|merged:<name>`` when the save folded into an existing event."""
    return f"{eid}|merged:{merged_into}" if merged_into else eid


# ── event_verify / event_lead ───────────────────────────────────────────────────────────────────────────────────
def apply_verify(ev: dict[str, Any], body: Mapping[str, Any], stamp: str) -> None:
    ev["human_verified"] = bool(body.get("verified", True))
    ev["human_verified_on"] = stamp  # "YYYY-MM-DD HH:MM", Berlin


def lead_decision(body: Mapping[str, Any]) -> str:
    decision = body.get("decision", "dismissed")
    if decision not in LEAD_DECISIONS:
        raise EventsError(400, BAD_DECISION)
    return str(decision)


# ── event_debrief ───────────────────────────────────────────────────────────────────────────────────────────────
def validate_debrief(body: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    people = body.get("people_met", [])
    leads = body.get("leads", [])
    for key, value in (("people_met", people), ("leads", leads)):
        if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
            raise EventsError(400, f"{key} must be a list of objects")
    for p in people:
        if not _is_text(p.get("name")) or not _is_text(p.get("note")):
            raise EventsError(400, "people_met must be a list of {name, note, founder_potential}")
    for ld in leads:
        if not _is_text(ld.get("name")) or not _is_text(ld.get("desc")) or not _is_text(ld.get("url")):
            raise EventsError(400, "leads must be a list of {name, desc, url}")
    if not _is_text(body.get("notes")):
        raise EventsError(400, "notes must be text")
    return people, leads


def person_body(ev: Mapping[str, Any], pm: Mapping[str, Any], today: date) -> dict[str, Any]:
    """The person the old debrief created for one person met (``people.upsert`` of these fields)."""
    return {
        "name": (pm.get("name") or "").strip(),
        "why_interesting": pm.get("note", ""),
        "discovery": f"Met at {ev['name']} ({ev.get('city', '')}, {str(ev.get('start', '') or '')[:10]})",
        "location": ev.get("city", ""),
        "relationship_strength": "met_once",
        "last_interaction": today.isoformat(),
        "founder_potential": pm.get("founder_potential", "maybe"),
        "next_action": "SUGGESTED: follow up within 48h while the conversation is warm",
    }


def _public_url(u: Any) -> str:
    return u.strip() if isinstance(u, str) and re.match(r"^https?://\S+$", u.strip()) else ""


def lead_entities(ev: Mapping[str, Any], leads: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """The intake entities of the debrief's startup leads (d). Evidence: the lead's own URL, else the event's URL;
    the event URL is evidence only, never ``website`` (the resolver treats a website as a company identity key, so
    two startups met at one event must stay distinct)."""
    out = []
    for ld in leads:
        name = (ld.get("name") or "").strip()
        if not name:
            continue
        url = _public_url(ld.get("url")) or _public_url(ev.get("url"))
        entity: dict[str, Any] = {
            "kind": "company",
            "name": name,
            "key_fact": (ld.get("desc") or "").strip() or f"Startup lead captured at {ev['name']}",
            "evidence": [{"url": url, "title": f"Met in person at {ev['name']}"}] if url else [],
            "signal_date": today.isoformat(),
        }
        if isinstance(ev.get("city"), str) and ev["city"].strip():
            entity["location"] = {"city": ev["city"].strip()}
        out.append(entity)
    return out


def apply_debrief(ev: dict[str, Any], person_ids: list[str], notes: Any) -> None:
    """``people_met`` gains each person once (a repeated debrief adds nothing twice), ``outcomes`` the notes, and the
    status becomes ``attended`` (the old tail of ``debrief``)."""
    met = ev.setdefault("people_met", [])
    if not isinstance(met, list):
        raise EventsError(409, "the stored people_met is not a list — nothing was changed")
    for pid in person_ids:
        if pid not in met:
            met.append(pid)
    if notes:
        ev["outcomes"] = ((ev.get("outcomes") or "") + "\n" + notes).strip()
    ev["status"] = "attended"


# ── Scout 00 event actions ──────────────────────────────────────────────────────────────────────────────────────
def scout_add_body(report: Mapping[str, Any]) -> dict[str, Any]:
    """The save the old ``event_action(id, "add")`` made (``events.upsert`` with its dedup and provenance)."""

    def v(key: str) -> str:
        value = report.get(key, "")
        return "" if value == UNKNOWN_VALUE else str(value or "")

    return {
        "name": report.get("event_name"),
        "start": v("date"),
        "city": v("city"),
        "url": v("official_url"),
        "source": SCOUT_LABEL + " cycle " + str(report.get("cycle_id", "")),
        "notes": "Scout Intake cycle {} · EV {} · AX {} · P {} · why: {} · action: {}".format(
            report.get("cycle_id", ""),
            report.get("ev_class", ""),
            report.get("ax_class", ""),
            report.get("p_class", ""),
            report.get("why_it_matters", ""),
            report.get("required_action", ""),
        ),
    }


SCOUT_STATUS = {"add": "ADDED TO EVENTS", "monitor": "MONITOR", "ignore": "IGNORED"}
