"""The Watchlist's WATCH panel (review 037a): the old ``watch.view()``, built from ONE read snapshot.

Per watched company (``watch.targets.watched``): ``key``, ``name``, ``candidate_id``, its pages (``urls``) and their
check records (``checks``) from the effective target, its 10 newest triggers (by ``first_observed``), the ``open``
count (status ``new``), ``triage_predates_evidence`` (decision d: the current proposal's ``proposed_at`` in the old
``%Y-%m-%dT%H:%M:%S`` form, compared as a string with the newest trigger's ``first_observed``) and
``machine_proposal`` (the current proposal's verdict). Sorted ``(-open, name.lower())``. Nothing here writes.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

import psycopg

from projectzero.watch import log as watch_log
from projectzero.watch import targets as watch_targets

LABEL: dict[str, str] = {
    "regulatory_approval": "Regulatory approval",
    "certification": "Certification",
    "procurement": "Procurement / tender",
    "accelerator": "Accelerator admission",
    "demo_day": "Demo day / pitch",
    "new_grant": "New grant",
    "funding": "Funding",
    "pilot": "Pilot",
    "customer": "Customer",
    "partnership": "Partnership",
    "launch": "Launch",
    "founder_change": "Founder change",
    "key_hire": "Key hire",
    "team_growth": "Team growth",
    "paper": "New paper",
    "patent": "New patent",
    "technical_milestone": "Technical milestone",
    "incorporation": "Incorporation",
    "first_institutional_round": "First institutional round",
    "material_page_change": "Material page change",
    "source_rehit": "New independent source mention",
}
NOTE = "Deterministic sensors only. Nothing here changes a decision or a score."
NEWEST = 10


def build(
    watched: Mapping[str, Mapping[str, Any]],
    targets: Mapping[str, Any],
    proposals: Mapping[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """The old ``view()`` over the watched set, the effective targets, the proposals by candidate id and the log's
    dict lines. Pure: nothing passed in is modified."""
    trig = watch_log.triggers(copy.deepcopy(events))
    rows = []
    for key, w in watched.items():
        t = targets.get(key) or {}
        mine = [x for x in trig if x["entity_key"] == key]
        p = proposals.get(w.get("candidate_id") or "") or {}
        newest = max((x["first_observed"] for x in mine), default="")
        rows.append(
            {
                "key": key,
                "name": w["name"],
                "candidate_id": w.get("candidate_id") or "",
                "urls": copy.deepcopy(t.get("urls") or []),
                "checks": copy.deepcopy(t.get("checks") or {}),
                "triggers": sorted(mine, key=lambda x: x["first_observed"], reverse=True)[:NEWEST],
                "open": sum(1 for x in mine if x["status"] == "new"),
                "triage_predates_evidence": bool(newest and p.get("proposed_at") and str(p["proposed_at"]) < newest),
                "machine_proposal": p.get("proposal"),
            }
        )
    rows.sort(key=lambda r: (-r["open"], r["name"].lower()))
    return {"companies": rows, "labels": dict(LABEL), "note": NOTE}


def watch_view(conn: psycopg.Connection[Any], schema: str) -> dict[str, Any]:
    """``GET /api/watch``: every input read on the caller's connection (one snapshot)."""
    candidates, proposals = watch_targets.watch_candidates(conn, schema)
    targets = watch_targets.effective_targets(conn, schema)
    events = watch_log.load_events(conn, schema)
    return build(watch_targets.watched(candidates, targets), targets, proposals, events)
