"""The old ``domain/founder_radar/records.py`` (rev 6c739b9), ported line for line (review 026a): the additive radar
fields, the state machine, the upgrade migrations and the Watchlist -> Network promotion.

Changes:
* ``migrate_all`` is PURE (decision a: a read never writes). It takes the people list and returns a
  ``Migration``: the migrated people (a new list of new records; the input is never changed), the ids of the records
  it changed or dropped, and the migration log entries the old code appended to ``radar_migration.json`` (without
  their ``on`` stamp; nothing here writes them).
* ``promote_to_network`` takes the people list and returns the new list and the promoted record (the old one loaded
  and saved ``people.json``).
* ``migrate_person``, ``migrate_mvp_records``, ``normalize_login_names`` and ``set_state`` change the record they are
  given, as before: callers hand them copies.
* The clock (``ck``, decision g): ``set_state`` stamps ``ck.minute()`` / ``ck.day()``; ``assess`` reads ``ck.today``.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from projectzero.founder_radar.catalog import _HUMAN_KEYS, NETWORK_STATES, STATES
from projectzero.founder_radar.clock import Clock
from projectzero.founder_radar.identity import promotion_guard
from projectzero.founder_radar.names import _fold, is_navigation_heading, is_organization_name, is_person_name
from projectzero.founder_radar.scoring import assess
from projectzero.network.view import records as _records


def migrate_person(p: dict[str, Any]) -> bool:
    """Additive: existing Network/Watchlist people gain radar fields without losing anything."""
    changed = False
    defaults = {
        "aliases": [],
        "identity_status": "verified by operator"
        if p.get("provenance") == "user_provided"
        else "needs identity resolution",
        "identity_evidence": [],
        "former_roles": [],
        "founder_status": "UNKNOWN",
        "country": "",
        "institutions": [],
        "profile_urls": [],
        "github_id": "",
        "openalex_id": "",
        "orcid": "",
        "patent_inventor_id": "",
        "companies": [],
        "events": [],
        "ecosystems": [],
        "sources": [],
        "evidence": [],
        "signal_categories": {},
        "evidence_confidence": "UNRESOLVED",
        "last_signal": "",
        "state_history": [],
        "intro_route": "",
        "relationship_owner": "Mohamed",
        "contact_channel": "",
        "machine_research": "",
        "human_judgment": "",
        "boardy": {"status": "", "history": []},
        "opportunities": [],
        "updated": p.get("created", ""),
        "why_surfaced": p.get("why_interesting", ""),
        "signal": None,
        "dismissed_reason": "",
    }
    for k, v in defaults.items():
        if k not in p:
            p[k] = v
            changed = True
    if "radar_state" not in p:
        p["radar_state"] = (
            "watchlisted"
            if p.get("watch")
            else (
                "active relationship"
                if p.get("relationship_strength") in ("strong", "close")
                else "contacted"
                if p.get("last_interaction")
                else "researching"
            )
        )
        changed = True
    if p.get("company") and p["company"] not in p["companies"]:
        p["companies"].append(p["company"])
        changed = True
    return changed


def _human_touched(p: dict[str, Any]) -> bool:
    if p.get("watch") or p.get("identity_verified_by") == "operator" or p.get("provenance") == "user_provided":
        return True
    if any(p.get(k) for k in _HUMAN_KEYS) or p.get("opportunities") or (p.get("boardy") or {}).get("status"):
        return True
    return any(h.get("by") != "radar" for h in (p.get("state_history") or []))


def _is_pipeline_generated(p: dict[str, Any]) -> bool:
    return p.get("provenance") == "radar_detected" and any(
        (s.get("route") == "pz-data" or s.get("source") in ("Project Zero pipeline", "Project Zero pipeline (claim)"))
        for s in (p.get("sources") or [])
    )


def migrate_mvp_records(d: dict[str, Any], ck: Clock) -> dict[str, Any]:
    """Idempotent repair of records created by the original Founder Radar MVP (pipeline names stamped as verified).
    Returns a migration report. Human work (watch state, history, notes, judgments, links) is never touched."""
    rep: dict[str, Any] = {"repaired": [], "quarantined": [], "invalidated": [], "checked": 0}
    keep = []
    for p in d.get("people", []):
        if not isinstance(p, dict) or not _is_pipeline_generated(p):
            keep.append(p)  # an unreadable entry is kept exactly as stored, never dropped
            continue
        rep["checked"] += 1
        migrate_person(p)
        if not is_person_name(p.get("name")):
            if _human_touched(p):
                p["invalid_record"] = "placeholder / aggregate value — not a person (original MVP ingestion)"
                p["identity_verified_by"] = ""
                p["identity_status"] = "needs identity resolution"
                p["founder_status"] = "invalid — placeholder value"
                if p.get("radar_state") != "dismissed":
                    set_state(
                        p,
                        "dismissed",
                        "migration: placeholder record marked invalid (human history preserved)",
                        "migration",
                        ck=ck,
                    )
                p["signal"] = assess(p, today=ck.today)
                rep["invalidated"].append(p.get("name"))
                keep.append(p)
            else:
                rep["quarantined"].append(
                    {"id": p.get("id"), "name": p.get("name"), "reason": "generated-only placeholder / aggregate value"}
                )
            continue
        touched = False
        if p.get("identity_verified_by") != "operator" and p.get("provenance") != "user_provided":
            if p.get("identity_status") == "verified by operator":
                p["identity_status"] = "needs identity resolution"
                touched = True
            if str(p.get("founder_status", "")).startswith("verified"):
                p["founder_status"] = "claimed (named in pipeline entry) — unverified"
                touched = True
            if p.get("radar_state") == "detected":
                p["radar_state"] = "needs identity resolution"
                touched = True
            for e in p.get("evidence") or []:
                if e.get("category") == "entrepreneurial" and e.get("claim", "").startswith("named founder of"):
                    e["claim"] = (
                        e["claim"].replace("named founder of", "claimed founder of", 1)
                        + " — pipeline entry, unverified"
                    )
                    e["source"] = "Project Zero pipeline (claim)"
                    touched = True
                if (
                    e.get("category") == "project_a"
                    and e.get("claim", "").startswith("company archetype")
                    and "(company-level" not in e["claim"]
                ):
                    e["claim"] += " (company-level, not person-level)"
                    e["source"] = "Project Zero pipeline (claim)"
                    touched = True
            for src in p.get("sources") or []:
                if src.get("route") == "pz-data" and not src.get("claim"):
                    src["claim"] = True
                    touched = True
            p["identity_evidence"] = [
                x
                for x in (p.get("identity_evidence") or [])
                if "named in Mohamed's own data" not in x and "typed by Mohamed" not in x
            ]
            if p.get("why_surfaced", "").startswith("founder of pipeline company"):
                p["why_surfaced"] = (
                    p["why_surfaced"].replace("founder of pipeline company", "named in pipeline entry for", 1)
                    + " (claim — identity not yet verified)"
                )
                touched = True
            p["signal"] = assess(p, today=ck.today)
            p["signal_categories"] = p["signal"]["bands"]
            p["evidence_confidence"] = p["signal"]["evidence_confidence"]
            if touched:
                rep["repaired"].append(p.get("name"))
        keep.append(p)
    d["people"] = keep
    return rep


def normalize_login_names(d: dict[str, Any], ck: Clock) -> list[Any]:
    """Idempotent: radar-generated GitHub records whose name is not a plausible human name (login / alias) and without
    an operator-provided identity get name_attributed=false."""
    fixed = []
    for p in _records(d.get("people")):
        if (
            p.get("provenance") != "radar_detected"
            or p.get("name_attributed") is not None
            or p.get("identity_verified_by") == "operator"
            or p.get("name_by_operator")
        ):
            continue
        is_gh = bool(p.get("github_id")) or any((s.get("route") == "github-api") for s in (p.get("sources") or []))
        if is_gh and (
            not is_person_name(p.get("name")) or _fold(p.get("name")) in {_fold(a) for a in (p.get("aliases") or [])}
        ):
            p["name_attributed"] = False
            if p.get("name") and p["name"] not in p.setdefault("aliases", []):
                p["aliases"].append(p["name"])
            p["identity_status"] = "needs identity resolution"
            p["signal"] = assess(p, today=ck.today)
            p["signal_categories"] = p["signal"]["bands"]
            fixed.append(p.get("name"))
    return fixed


@dataclass(frozen=True)
class Migration:
    """``people``: the migrated list (new records); ``changed``: the ids of the records changed or dropped
    (quarantined), in the input order; ``log``: the old ``radar_migration.json`` entries ``{kind, ...}``."""

    people: list[Any]
    changed: list[Any] = field(default_factory=list)
    log: list[dict[str, Any]] = field(default_factory=list)


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, ensure_ascii=False, default=str) == json.dumps(b, ensure_ascii=False, default=str)


def migrate_all(people: Any, ck: Clock) -> Migration:
    """The old ``migrate_all`` without its two writes: idempotent (a second run over its output changes nothing)."""
    d: dict[str, Any] = {"people": copy.deepcopy(people) if isinstance(people, list) else []}
    log: list[dict[str, Any]] = []
    for p in _records(d.get("people")):
        migrate_person(p)
    fixed = normalize_login_names(d, ck)
    if fixed:
        log.append({"kind": "login_only_names", "normalized": fixed})
    orgs = []
    for p in _records(d.get("people")):
        if (
            p.get("provenance") == "radar_detected"
            and is_organization_name(p.get("name"))
            and not p.get("invalid_record")
            and p.get("provenance") != "user_provided"
            and not p.get("name_by_operator")
        ):
            p["invalid_record"] = "organization / institution / company account — not a person"
            p["identity_status"] = "needs identity resolution"
            p["signal"] = assess(p, today=ck.today)
            if p.get("radar_state") != "dismissed":
                set_state(p, "dismissed", "migration: organization record is not a person", "migration", ck=ck)
            orgs.append(p.get("name"))
    if orgs:
        log.append({"kind": "organization_records", "invalidated": orgs})
    heads = []
    for p in _records(d.get("people")):  # machine-detected navigation headings are quarantined, never operator names
        if (
            p.get("provenance") == "radar_detected"
            and is_navigation_heading(p.get("name"))
            and not p.get("invalid_record")
            and not p.get("name_by_operator")
            and p.get("name_attributed", True) is not False
        ):
            p["invalid_record"] = "navigation heading / page text — not a person"
            p["identity_status"] = "needs identity resolution"
            p["signal"] = assess(p, today=ck.today)
            if p.get("radar_state") != "dismissed":
                set_state(p, "dismissed", "migration: navigation heading is not a person", "migration", ck=ck)
            heads.append(p.get("name"))
    if heads:
        log.append({"kind": "navigation_heading_records", "invalidated": heads})
    rep = migrate_mvp_records(d, ck)
    for p in _records(d.get("people")):  # invariant: no operator-verified record without real provenance
        if p.get("identity_status") == "verified by operator" and not (
            p.get("provenance") == "user_provided" or p.get("identity_verified_by") == "operator"
        ):
            p["identity_status"] = "needs identity resolution"
            p["signal"] = assess(p, today=ck.today)
            rep["repaired"].append(p.get("name"))
    if rep["repaired"] or rep["quarantined"] or rep["invalidated"]:
        log.append({"kind": "people_mvp_to_mvp1", **rep})
    out: dict[Any, Any] = {}
    for p in _records(d["people"]):
        out.setdefault(_same_key(p.get("id")), p)
    changed = []
    for old in _records(people):
        new = out.get(_same_key(old.get("id")))
        if new is None or not _same(old, new):
            changed.append(old.get("id"))
    return Migration(d["people"], changed, log)


def _same_key(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def set_state(p: dict[str, Any], new_state: Any, note: Any = "", actor: str = "operator", *, ck: Clock) -> None:
    if new_state not in STATES:
        raise ValueError(new_state)
    old = p.get("radar_state", "")
    p.setdefault("state_history", []).append(
        {"from": old, "to": new_state, "on": ck.minute(), "note": note, "by": actor}
    )
    p["radar_state"] = new_state
    p["updated"] = ck.day()
    if new_state == "watchlisted":
        p["watch"] = True
    if new_state in NETWORK_STATES:
        p["watch"] = p.get("watch", False)


def promote_to_network(
    people: list[dict[str, Any]],
    pid: Any,
    how: Any = "",
    introduced_by: Any = "",
    stage: Any = "contacted",
    last_interaction: Any = "",
    next_action: Any = "",
    next_action_date: Any = "",
    channel: Any = "",
    notes: Any = "",
    *,
    ck: Clock,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Watchlist -> Network is a STATE TRANSITION on the same record: nothing copied, nothing lost. (the new people
    list — the input when refused —, the promoted record or None: unknown id or unresolved identity)."""
    i = next((i for i, x in enumerate(people) if isinstance(x, dict) and x.get("id") == pid), None)
    if i is None:
        return people, None
    p = copy.deepcopy(people[i])
    migrate_person(p)
    if promotion_guard(p):
        return people, None
    if how:
        p["discovery"] = how
    if introduced_by:
        p["introduced_by_name"] = introduced_by  # canonical free-text introducer (whitelisted, survives listing)
        match = next(
            (x for x in _records(people) if x["id"] != p["id"] and _fold(x.get("name")) == _fold(introduced_by)), None
        )
        if match:
            p["introduced_by"] = match["id"]  # internal id when the introducer is a known person
    if last_interaction:
        p["last_interaction"] = last_interaction
    if next_action:
        p["next_action"] = next_action
    if next_action_date:
        p["next_action_date"] = next_action_date
    if channel:
        p["contact_channel"] = channel
    if notes:
        p["notes"] = ((p.get("notes") or "") + "\n" + notes).strip()
    set_state(p, stage if stage in NETWORK_STATES else "contacted", "promoted Watchlist → Network", "operator", ck=ck)
    out = list(people)
    out[i] = p
    return out, p
