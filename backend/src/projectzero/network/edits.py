"""The Network write rules (review 013), pure: what a save, the "3 most talented" ritual and a signal log do to records.

Old source (rev 6c739b9): ``domain/people.py`` ``upsert`` (:122) / ``add_talented`` (:143-179) / ``FIELDS``,
``domain/founder_radar/ingestion.py`` ``operator_save`` (:169-219), ``api/routers/network.py`` (``person_save``,
``talented``, ``watch_log``). The store (``network.store``) runs these inside ONE transaction under its locks.

Changed on purpose (review 013, approved by Codex):

* (a) **No silent overwrite on add.** The old ``upsert`` used ``id = body.id or slug(name)``, so adding a person whose
  generated id existed overwrote that person. An add (no ``id``) whose generated id is taken is refused (409, the
  existing id); an edit (an ``id``) of an unknown person is refused (404) instead of creating it.
* (b) **The ritual never re-parents.** ``add_talented`` reuses a person by slug, but an existing non-empty
  ``introduced_by`` (the original introduction) is never overwritten. A recommendation by another introducer only
  lands in that introducer's ``recommended``; the person's introduction (``introduced_by``, ``discovery``) stays,
  and a ``why_interesting`` that is already written is kept (the note is recorded in the event). A person is never
  made their own introducer.

Not ported (waits for the Founder Radar review), refused or skipped explicitly:

* (review 026a) the radar part of ``operator_save``, renaming a Founder Radar person and the identity / signal
  recompute after any edit of one, is ``founder_radar.operator.after_operator_save``, applied by the store.

Input types the old code crashed on (500) or stored and later crashed on are refused as 400 here: a non-text
``id`` / ``name``, a ``recommended`` that is not a list of ids, a non-text ``introduced_by``, a ``persons`` that is
not a list of ``{name, note}`` objects, a non-text ``note``.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

FIELDS = [
    "name",
    "location",
    "company",
    "university",
    "role",
    "expertise",
    "why_interesting",
    "discovery",
    "introduced_by",
    "recommended",
    "startups",
    "founder_potential",
    "linkedin",
    "x",
    "email",
    "relationship_strength",
    "last_interaction",
    "next_action",
    "next_action_date",
    "notes",
    "created",
    "provenance",
    "watch",
    "last_checked",
    "github",
    # Founder Radar MVP (additive; canonical person record)
    "aliases",
    "identity_status",
    "identity_evidence",
    "former_roles",
    "founder_status",
    "country",
    "institutions",
    "profile_urls",
    "github_id",
    "openalex_id",
    "orcid",
    "patent_inventor_id",
    "companies",
    "events",
    "ecosystems",
    "sources",
    "evidence",
    "signal_categories",
    "evidence_confidence",
    "last_signal",
    "radar_state",
    "state_history",
    "intro_route",
    "relationship_owner",
    "contact_channel",
    "machine_research",
    "human_judgment",
    "boardy",
    "opportunities",
    "updated",
    "why_surfaced",
    "signal",
    "dismissed_reason",
    "introduced_by_name",
    "identity_verified_by",
    "region",
    "invalid_record",
    "identity_verified_on",
]

NAME_REQUIRED = "name required"
DUPLICATE = "a person with this name already exists — open the existing person to edit them; nothing was saved"
UNKNOWN = "unknown person — nothing was saved"
IDENTIFIER_TAKEN = "{kind} {value} already belongs to another person ({owner}) — nothing was saved"
NOT_TEXT_NOTES = "the stored notes are not text — nothing was changed"
NOT_A_LIST = "{who}'s recommended list is not a list — nothing was changed"


class NetworkError(ValueError):
    def __init__(self, status: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.extra = extra


def _is_text(v: Any) -> bool:
    return v is None or isinstance(v, str)


# ── person_save ─────────────────────────────────────────────────────────────────────────────────────────────────
def validate_save(body: Mapping[str, Any]) -> None:
    """The old route's ``name required`` plus the types the old code crashed on, or stored and crashed on later."""
    if "id" in body and not _is_text(body["id"]):
        raise NetworkError(400, "id must be text")
    if not _is_text(body.get("name")):
        raise NetworkError(400, "name must be text")
    if not body.get("id") and not str(body.get("name") or "").strip():  # no nameless people (old audit 2026-11-08)
        raise NetworkError(400, NAME_REQUIRED)
    if "recommended" in body and not (
        isinstance(body["recommended"], list) and all(isinstance(r, str) for r in body["recommended"])
    ):
        raise NetworkError(400, "recommended must be a list of person ids")
    if "introduced_by" in body and not _is_text(body["introduced_by"]):
        raise NetworkError(400, "introduced_by must be a person id")


def new_record(pid: str, today: date) -> dict[str, Any]:
    """The record the old ``upsert`` started a new person from."""
    return {"id": pid, "recommended": [], "startups": [], "created": today.isoformat(), "provenance": "user_provided"}


def apply_save(p: dict[str, Any], body: Mapping[str, Any]) -> None:
    """The old ``upsert`` write: the ``FIELDS`` the body carries, a comma-separated ``startups``, a default name."""
    for k in FIELDS:
        if k in body:
            p[k] = copy.deepcopy(body[k])
    if isinstance(p.get("startups"), str):
        p["startups"] = [s.strip() for s in p["startups"].split(",") if s.strip()]
    p.setdefault("name", "?")


def radar_fold(s: Any) -> str:
    """The old ``founder_radar.names._fold`` (the comparison ``operator_save`` used to detect a rename)."""
    return re.sub(
        r"[^a-z0-9 ]", "", unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    ).strip()


# ── the "3 most talented" ritual ────────────────────────────────────────────────────────────────────────────────
def validate_talented(body: Mapping[str, Any]) -> list[dict[str, Any]]:
    persons = body.get("persons", [])
    if persons is None or not isinstance(persons, list):
        raise NetworkError(400, "persons must be a list of {name, note}")
    for item in persons:
        if not isinstance(item, dict) or not _is_text(item.get("name")) or not _is_text(item.get("note")):
            raise NetworkError(400, "persons must be a list of {name, note}")
    if "id" in body and not _is_text(body["id"]):
        raise NetworkError(400, "id must be text")
    return persons


def ritual_ids(host_id: str, persons: list[dict[str, Any]]) -> list[str]:
    """Every person id the ritual may touch: the introducer and the slug of each named person."""
    from projectzero.network.people import slug

    return [host_id, *(slug(n) for item in persons if (n := (item.get("name") or "").strip()))]


def discovery_text(host: Mapping[str, Any]) -> str:
    return f"Recommended by {host.get('name', '?')} ('3 most talented' ask)"


def apply_talented(
    host_id: str,
    persons: list[dict[str, Any]],
    get: Callable[[str], dict[str, Any] | None],
    today: date,
) -> tuple[list[str], dict[str, dict[str, Any]], dict[str, Any]]:
    """The old ``add_talented`` with decision (b). ``get(pid)`` gives the WORKING COPY of an existing record (the same
    object for the same id) or None; the host must exist.

    Returns (created ids in the old order, the working records by id incl. new ones, per-id notes for the events)."""
    from projectzero.network.people import slug

    host = get(host_id)
    assert host is not None
    work: dict[str, dict[str, Any]] = {host_id: host}
    detail: dict[str, Any] = {}
    created: list[str] = []
    for item in persons:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        pid = slug(name)
        p = work.get(pid) or get(pid)
        if p is None:
            p = {
                "id": pid,
                "name": name,
                "recommended": [],
                "startups": [],
                "created": today.isoformat(),
                "relationship_strength": "met_once",
                "founder_potential": "maybe",
                "last_interaction": "",
            }
            detail.setdefault(pid, {})["new"] = True
        work[pid] = p
        parent = p.get("introduced_by")
        if not parent and pid != host_id:  # an empty parent: THIS recommendation is the introduction
            p["introduced_by"] = host_id
            p["discovery"] = discovery_text(host)
            if item.get("note"):
                p["why_interesting"] = item["note"]
        elif parent == host_id:  # its own introduction again (a retry): the old write, unchanged
            p["discovery"] = discovery_text(host)
            if item.get("note"):
                p["why_interesting"] = item["note"]
        else:  # (b) another introducer's person: a recommendation only, the introduction stays
            if item.get("note") and not p.get("why_interesting"):
                p["why_interesting"] = item["note"]
            info = detail.setdefault(pid, {})
            info["introduction_kept"] = parent if parent else None
            if item.get("note"):
                info["note"] = item["note"]
        p.setdefault("next_action", "SUGGESTED: reach out with a warm reference to " + str(host.get("name", "?")))
        p["provenance"] = "user_provided"
        recommended = host.setdefault("recommended", [])  # the old code: only once someone is named
        if not isinstance(recommended, list):
            raise NetworkError(409, NOT_A_LIST.format(who=host.get("name", host_id)))
        if pid not in recommended:
            recommended.append(pid)
        created.append(pid)
    host["last_interaction"] = today.isoformat()
    return created, work, detail


# ── the Watchlist signal log ────────────────────────────────────────────────────────────────────────────────────
def validate_watch_log(body: Mapping[str, Any]) -> None:
    if not _is_text(body.get("note")):
        raise NetworkError(400, "note must be text")
    if "id" in body and not _is_text(body["id"]):
        raise NetworkError(400, "id must be text")


def apply_watch_log(p: dict[str, Any], note: Any, today: date) -> None:
    """The old ``/api/watch_log``: append ``[YYYY-MM-DD signal] note`` to the notes, mark the person checked today."""
    day = today.isoformat()
    if note:
        notes = p.get("notes") or ""
        if not isinstance(notes, str):
            raise NetworkError(409, NOT_TEXT_NOTES)
        p["notes"] = (notes + "\n[" + day + " signal] " + note).strip()
    p["last_checked"] = day
