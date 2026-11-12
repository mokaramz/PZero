"""The old ``domain/founder_radar/metrics.py`` ``record_metrics`` (rev 6c739b9), split in two pure halves (review 026a,
decision a): ``metrics_snapshot`` computes the day's ``latest`` from the STORED signals (decision d: not the freshly
assessed ones, as before), ``append_history`` returns the new ``radar_metrics.json`` body (today's entry replaced, the
last 60 kept). The old function did both and wrote the file on every call, the GET included; here a read only
computes ``latest`` and a write stores the new body."""

from __future__ import annotations

import copy
from datetime import date
from typing import Any

from projectzero.founder_radar.catalog import BUCKETS, NETWORK_STATES
from projectzero.founder_radar.scoring import bucket_of


def metrics_snapshot(people: list[Any], today: date) -> dict[str, Any]:
    """``people``: the stored records (the list as read; nothing here changes them)."""
    P = copy.deepcopy(people)  # bucket_of writes into the stored signal it is handed, as before: work on copies
    day = today.isoformat()
    bk: dict[str, int] = {}
    for p in P:
        if p.get("provenance") == "user_provided" and p.get("radar_state") in NETWORK_STATES:
            continue
        bkt = (p.get("signal") or {}).get("bucket") or bucket_of(p, p.get("signal") or {}, today=today)[0]
        bk[bkt] = bk.get(bkt, 0) + 1
    m: dict[str, Any] = {
        "date": day,
        "gold_now": bk.get(BUCKETS[0], 0),
        "strong_investigation": bk.get(BUCKETS[1], 0),
        "founder_claims_unresolved": bk.get(BUCKETS[2], 0),
        "research_talent": bk.get(BUCKETS[3], 0),
        "insufficient_evidence": bk.get(BUCKETS[4], 0),
        "unique_identities_resolved": sum(
            1 for p in P if p.get("identity_status") in ("resolved", "verified by operator")
        ),
        "watchlisted": sum(1 for p in P if p.get("radar_state") == "watchlisted" or p.get("watch")),
        "intro_paths_identified": sum(
            1 for p in P if p.get("intro_route") or p.get("introduced_by") or p.get("introduced_by_name")
        ),
        "introductions_requested": sum(
            1
            for p in P
            if p.get("radar_state") == "introduction requested"
            or (p.get("boardy") or {}).get("status") == "introduction requested"
        ),
        "contacted": sum(1 for p in P if p.get("radar_state") in NETWORK_STATES),
        "replies": sum(1 for p in P if p.get("radar_state") in NETWORK_STATES[3:]),
        "first_meetings": sum(1 for p in P if p.get("radar_state") in NETWORK_STATES[4:]),
        "active_relationships": sum(
            1
            for p in P
            if p.get("radar_state") in ("active relationship", "trusted relationship", "opportunity introduced")
        ),
        "trusted_relationships": sum(1 for p in P if p.get("radar_state") == "trusted relationship"),
        "pre_company_opportunities": sum(len(p.get("opportunities") or []) for p in P),
        "companies_discovered_founder_first": sum(
            1 for p in P for o in (p.get("opportunities") or []) if o.get("kind") == "company"
        ),
        "watchlist_to_network_conversion": None,
    }
    w = sum(1 for p in P if any(h.get("to") == "watchlisted" for h in (p.get("state_history") or [])))
    n = sum(
        1
        for p in P
        if any(h.get("to") == "watchlisted" for h in (p.get("state_history") or []))
        and p.get("radar_state") in NETWORK_STATES
    )
    m["watchlist_to_network_conversion"] = round(n / w, 2) if w else None
    return m


def history_of(doc: Any) -> list[Any]:
    """The old ``store.load_metrics_history``: tolerant (``[]`` when missing or malformed)."""
    h = doc.get("history", []) if isinstance(doc, dict) else []
    return h if isinstance(h, list) else []


def append_history(doc: Any, latest: dict[str, Any]) -> dict[str, Any]:
    """The new ``radar_metrics.json`` body: ``latest`` replaces today's entry (``latest["date"]``), the last 60 kept."""
    hist = [h for h in history_of(doc) if h.get("date") != latest["date"]] + [latest]
    return {"history": copy.deepcopy(hist[-60:]), "latest": copy.deepcopy(latest)}
