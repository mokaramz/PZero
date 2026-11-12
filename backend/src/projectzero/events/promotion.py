"""What a scan does to the Events records (review 017): the old ``domain/events.py`` ``promote_structured`` (:629-725)
and ``add_leads`` (:1091-1129) (rev 6c739b9), ported VERBATIM as pure functions over the CURRENT records (the scan
re-reads them under the events write lock, so a decision made while the sources were being fetched is never lost,
Codex H-113). They return what to write; ``events.scan`` writes it through the 016 write model.

Changed on purpose (review 017):

* (b) **Leads are never deleted.** The old ``add_leads`` kept only the newest 250 leads (``d["leads"][:250]``),
  deleting the older ones and their decisions; here every lead is kept.
* (c) **One Berlin clock**: the past-date filters compare with the scan's Berlin date, ``seen`` / ``detected_on``
  are that date (the old code mixed ``berlin_today()`` and the machine's ``date.today()``).
* A start the old ``parse_when`` crashed on (not text) is "rejected" for that item (the old scan failed).
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from projectzero.events.dedup import close_dates, similar
from projectzero.events.edits import slug_id
from projectzero.events.engine import classify
from projectzero.events.when import parse_when

_GENERIC_NAME = re.compile(r"^(events?|veranstaltungen|calendar|kalender|news|home|untitled|tba|tbd)$", re.I)


@dataclass
class Promotion:
    accepted: int = 0
    past: int = 0
    dups: int = 0
    rejected: int = 0
    tags: list[str] = field(default_factory=list)  # per item, in input order: accepted | past | dups | rejected
    created: list[dict[str, Any]] = field(default_factory=list)  # new event records, in the old append order
    merged: dict[str, dict[str, Any]] = field(default_factory=dict)  # event id -> the updated record


def _when(raw: Any, today: date) -> tuple[date | None, str]:
    if raw is not None and not isinstance(raw, str):
        return None, ""
    try:
        d0, hhmm, _ = parse_when(raw, today=today)
    except (ValueError, OverflowError):
        return None, ""
    return d0, hhmm


def promote_structured(items: list[dict[str, Any]], events: list[dict[str, Any]], today: date) -> Promotion:
    """Promote structured items ONLY when they carry a real name, a parseable FUTURE start date, a source URL and
    provenance. The same event across sources is merged (similar name + close date), keeping every source."""
    res = Promotion()
    current = [copy.deepcopy(e) for e in events]  # the old ``d["events"]``: new events join it as they are made
    for it in items:
        name = str(it.get("title") or it.get("name") or "").strip()
        url = str(it.get("url") or it.get("source_url") or "").strip()
        sd, st = _when(it.get("date") or it.get("start"), today)
        prov = it.get("provenance") or ""
        org = (it.get("organizer") or "").strip() or "UNKNOWN"
        if (
            not name
            or _GENERIC_NAME.match(name)
            or len(name) < 3
            or not url.startswith("http")
            or not prov
            or sd is None
        ):
            res.rejected += 1
            res.tags.append("rejected")
            continue
        if sd < today:
            res.past += 1
            res.tags.append("past")
            continue
        start_iso = sd.isoformat() + ("T" + st if st else "")
        provenance = {
            "source": it.get("source", ""),
            "source_id": it.get("source_id", ""),
            "url": url,
            "provenance": prov,
            "confidence": it.get("confidence", "medium"),
            "seen": today.isoformat(),
        }
        dup = next(
            (
                x
                for x in current
                if similar(name, x.get("name", "")) and close_dates(sd.isoformat(), x.get("start", ""))
            ),
            None,
        )
        if dup is not None:
            srcs = dup.setdefault("sources", [])
            if not any(p.get("url") == url and p.get("provenance") == prov for p in srcs):
                srcs.append(provenance)
            for k in ("venue", "organizer", "city", "end"):
                if not dup.get(k) and it.get(k) and it.get(k) != "UNKNOWN":
                    dup[k] = it[k]
            if not any(dup is c for c in res.created):
                res.merged[str(dup.get("id"))] = dup
            res.dups += 1
            res.tags.append("dups")
            continue
        ev: dict[str, Any] = {
            "id": slug_id(name, start_iso),
            "name": name,
            "type": "",
            "organizer": org,
            "description": str(it.get("description") or "")[:1200],
            "keywords": it.get("keywords") or "",
            "audience": it.get("audience") or "",
            "event_status": it.get("event_status") or "",
            "format": it.get("format") or "",
            "address": it.get("address") or "",
            "country": it.get("country") or "",
            "price": it.get("price") or {},
            "registration_url": it.get("registration_url") or "",
            "route": prov,
            "retrieved_at": it.get("retrieved_at") or "",
            "start": start_iso,
            "end": str(it.get("end") or "")[:16],
            "city": it.get("city") or "",
            "venue": it.get("venue") or "",
            "url": url,
            "deadline": "",
            "audience_estimate": "",
            "domains": it.get("domains", ""),
            "notes": ("Format: " + it["format"] + ". " if it.get("format") else "")
            + "Auto-promoted structured event ("
            + prov
            + "); details not yet verified by you.",
            "status": "new",
            "score_parts": None,
            "sources": [provenance],
            "confidence": it.get("confidence", "medium"),
            "auto_promoted": True,
        }
        ev["type"] = classify(ev)[0]
        current.append(ev)
        res.created.append(ev)
        res.accepted += 1
        res.tags.append("accepted")
    return res


@dataclass
class LeadIntake:
    added: int = 0
    dropped_past: int = 0
    dropped_dupe: int = 0
    new: list[dict[str, Any]] = field(default_factory=list)  # in the old order: the newest first


def add_leads(items: list[dict[str, Any]], leads: list[dict[str, Any]], events: list[dict[str, Any]],
              today: date) -> LeadIntake:  # fmt: skip
    """Discovered items -> leads, deduplicated against existing leads AND events. Past-dated items are dropped; a
    fuzzy match with an open lead gets a 'possible duplicate' note instead of being dropped. Nothing is deleted (b)."""
    out = LeadIntake()
    known = {lead.get("id") for lead in leads}
    current = list(leads)
    iso_today = today.isoformat()
    for it in items:
        if it["id"] in known:
            continue
        if it.get("date") and it["date"][:10] < iso_today:
            out.dropped_past += 1
            continue
        dupe = None
        for e in events:
            if similar(it.get("title", ""), e.get("name", "")) and close_dates(it.get("date", ""), e.get("start", "")):
                dupe = ("event", e.get("name"))
                break
        if not dupe:
            for lead in current:
                if (
                    lead.get("decision") == "new"
                    and similar(it.get("title", ""), lead.get("title", ""))
                    and close_dates(it.get("date", ""), lead.get("date", ""))
                ):
                    dupe = ("lead", lead.get("title"))
                    break
        if dupe and dupe[0] == "event":
            out.dropped_dupe += 1
            continue
        item = dict(it)
        if dupe and dupe[0] == "lead":
            item["note"] = "Possible duplicate of lead: " + (dupe[1] or "")[:80]
        current.insert(0, item)
        out.new.insert(0, item)
        known.add(item["id"])
        out.added += 1
    return out
