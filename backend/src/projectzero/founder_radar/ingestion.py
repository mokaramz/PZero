"""The old ``domain/founder_radar/ingestion.py`` (rev 6c739b9), ported line for line (review 026a): ``_merge_into`` and
``ingest`` (candidates onto the ONE canonical person record; merge only with identity evidence).

Changes:
* ``ingest`` takes the people list and returns an ``Ingest`` (the new list, the old answer counts, the ids of the
  new or changed records in document order). The input is never changed.
* Decision b, deterministic person ids: the old id ``p-<slug>-<abs(hash(key)) % 10000>`` used Python's per-process
  string hash and never checked collisions. ``allocate_id`` (the default, INJECTABLE allocator) keeps the shape with
  ``int(sha1(str(key))) % 10000`` as the suffix, and a taken id (a live person, an id created earlier in the same
  call, or any RESERVED id: the merge tombstones, revision 2/3) gets ``-2``, ``-3``, ... appended.
* The clock (``ck``, decision g).
* The old ``ingest.skipped_orgs`` / ``skipped_headings`` function attributes (process-global, never answered) are not
  kept.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from typing import Any

from projectzero.founder_radar.clock import Clock
from projectzero.founder_radar.evidence import dedupe_evidence, person_recent_activity
from projectzero.founder_radar.identity import can_merge, identity_resolution
from projectzero.founder_radar.names import _fold, is_navigation_heading, is_organization_name, is_person_name
from projectzero.founder_radar.records import migrate_person, set_state
from projectzero.founder_radar.scoring import assess
from projectzero.network.view import records as _records


def _merge_into(existing: dict[str, Any], cand: dict[str, Any], reason: str, *, ck: Clock) -> None:
    # login-only record receives an attributed human name through the same verified identity: recover the name
    if (
        cand.get("name_attributed")
        and is_person_name(cand.get("name"))
        and (existing.get("name_attributed") is False or not is_person_name(existing.get("name")))
        and existing.get("provenance") != "user_provided"
        and not existing.get("name_by_operator")
    ):
        old = existing.get("name", "")
        if old and old not in existing.setdefault("aliases", []):
            existing["aliases"].append(old)
        existing["name"] = cand["name"]
        existing["name_attributed"] = True
        existing.setdefault("identity_evidence", []).append(
            "human name attributed via same verified identity: {} -> {}".format(old, cand["name"])
        )
    for k in ("aliases", "profile_urls", "institutions", "companies", "events", "ecosystems"):
        for v in cand.get(k) or []:
            if v and v not in existing.setdefault(k, []):
                existing[k].append(v)
    for k in (
        "github_id",
        "openalex_id",
        "orcid",
        "location",
        "company",
        "country",
        "role",
        "linkedin",
        "email",
        "provenance_label",
        "linkedin_connection_degree",
        "connection_source",
        "linkedin_connected_on",
        "import_label",
        "import_date",
    ):
        if not existing.get(k) and cand.get(k):
            existing[k] = cand[k]
    existing["evidence"] = dedupe_evidence((existing.get("evidence") or []) + list(cand.get("evidence") or []))
    for s in cand.get("sources") or []:
        if s not in existing.setdefault("sources", []):
            existing["sources"].append(s)
    existing.setdefault("identity_evidence", []).append("merged: " + reason)
    existing["last_observed"] = ck.day()
    existing["updated"] = ck.day()
    pra = person_recent_activity(existing, ck.today)
    existing["last_signal"] = pra["date"] or existing.get(
        "last_signal", ""
    )  # meaningful activity date only (legacy value kept when none)


def id_suffix(key: Any) -> int:
    """Decision b: the deterministic stand-in for the old ``abs(hash(key))``."""
    return int(hashlib.sha1(str(key).encode("utf-8")).hexdigest(), 16)


def allocate_id(c: dict[str, Any], taken: Collection[str]) -> str:
    """``p-<slug>-<sha1(key) % 10000>`` (key: GitHub id, else OpenAlex id, else the name), then ``-2``, ``-3``, ...
    while the id is taken (live people, ids made earlier in the same call, reserved tombstone ids)."""
    base = (
        "p-"
        + re.sub(r"[^a-z0-9]+", "-", _fold(c["name"]))[:40]
        + "-"
        + str(abs(id_suffix(c.get("github_id") or c.get("openalex_id") or c["name"])) % 10000)
    )
    pid, n = base, 1
    while pid in taken:
        n += 1
        pid = f"{base}-{n}"
    return pid


@dataclass(frozen=True)
class Ingest:
    people: list[Any]  # the new list (the input object when nothing was ingested)
    result: dict[str, int]  # {new, merged, resolved, unresolved}
    changed: list[Any] = field(default_factory=list)  # the ids of the new or changed records, in document order


def _key(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def ingest(
    people: list[Any],
    candidates: list[dict[str, Any]],
    *,
    ck: Clock,
    reserved_ids: Collection[str] = (),
    allocate: Callable[[dict[str, Any], Collection[str]], str] = allocate_id,
) -> Ingest:
    d: dict[str, Any] = {"people": copy.deepcopy(people)}
    taken = {str(p.get("id")) for p in _records(d["people"])} | {str(x) for x in reserved_ids}
    merged = 0
    new = 0
    unresolved = 0
    resolved = 0
    for c in candidates:
        if is_organization_name(c.get("name")) and c.get("name_attributed", True) is not False:
            continue  # organizations / company accounts never become person records
        if c.get("github_id") and is_organization_name(c.get("name")):
            continue
        if is_navigation_heading(c.get("name")) and c.get("name_attributed", True) is not False:
            continue  # "About ...", "Team", "Contact" are page text, never a person
        target = None
        for p in _records(d["people"]):
            ok, why = can_merge(p, c)
            if ok:
                target = p
                break
        if target is not None:
            _merge_into(target, c, why, ck=ck)
            merged += 1
            p = target
        else:
            pid = allocate(c, taken)
            taken.add(pid)
            p = {
                "id": pid,
                "name": c["name"],
                "created": ck.day(),
                "provenance": "radar_detected",
                "recommended": [],
                "startups": [],
                "watch": False,
            }
            migrate_person(p)
            p["identity_status"] = "needs identity resolution"
            for k in (
                "aliases",
                "location",
                "country",
                "company",
                "institutions",
                "profile_urls",
                "github_id",
                "openalex_id",
                "orcid",
                "role",
                "evidence",
                "sources",
                "why_surfaced",
                "companies",
                "founder_status",
                "region",
                "linkedin",
                "email",
                "provenance_label",
                "linkedin_connection_degree",
                "connection_source",
                "linkedin_connected_on",
                "import_label",
                "import_date",
            ):
                if c.get(k):
                    p[k] = copy.deepcopy(c[k])
            if c.get("name_attributed") is False:
                p["name_attributed"] = False
            p["evidence"] = dedupe_evidence(p.get("evidence") or [])
            if p.get("company") and p["company"] not in p["companies"]:
                p["companies"].append(p["company"])
            p["last_observed"] = ck.day()
            p["last_signal"] = person_recent_activity(p, ck.today)["date"]
            set_state(p, "detected", "detected by founder scan", "radar", ck=ck)
            d["people"].append(p)
            new += 1
        status, idev = identity_resolution(p)
        prev_ev = [
            x
            for x in (p.get("identity_evidence") or [])
            if not (p.get("name_attributed") and "login / handle only" in x)
        ]
        p["identity_status"], p["identity_evidence"] = status, list(dict.fromkeys(prev_ev + idev))
        if status == "needs identity resolution":
            unresolved += 1
            if p.get("radar_state") == "detected":
                p["radar_state"] = "needs identity resolution"
        else:
            resolved += 1
        a = assess(p, today=ck.today)
        p["signal"] = a
        p["signal_categories"] = a["bands"]
        p["evidence_confidence"] = a["evidence_confidence"]
    before = {_key(p.get("id")): _key(p) for p in _records(people)}
    changed = [p.get("id") for p in _records(d["people"]) if before.get(_key(p.get("id"))) != _key(p)]
    result = {"new": new, "merged": merged, "resolved": resolved, "unresolved": unresolved}
    return Ingest(d["people"] if changed else people, result, changed)
