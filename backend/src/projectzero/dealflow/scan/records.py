"""The scan record of a candidate the Deal Flow scan created (review 034a): the old inbox record, kept as
``candidates.attrs.scan_record`` so the ranking reads it exactly like an imported one.

Pure ports of the old ``services/discovery.py`` steps that shaped it (rev 6c739b9):

* ``created`` — the old ``_ingest_scan_locked`` for an ADDED record (run stamps, ``first_seen``, the provenance
  stamps, ``finalize_provenance`` and the ``candidates_found`` milestone);
* ``absorb`` — the old ``absorb``: a re-reported record folded into an existing scan record (each source once,
  stamped with the run it first appeared in; ``last_observed`` and ``seen_runs`` move; ``first_seen`` / ``run_id``
  never do);
* ``found_milestone`` — the old ``milestone(c, "candidates_found")`` WITHOUT its registry write: the record keeps
  ``q_found`` (the sources it was credited to) and ``sources.counters`` derives the per-source counter from it.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, TypeGuard

from projectzero.dealflow.ranking.tagging import finalize_provenance


def found_milestone(c: dict[str, Any]) -> bool:
    """The old ``milestone(c, "candidates_found")``: credited to EVERY producing source, once each."""
    hit = False
    for sid in c.get("all_source_ids") or ([c["source_id"]] if c.get("source_id") else []):
        done = c.setdefault("q_found", [])
        if sid not in done:
            done.append(sid)
            hit = True
    return hit


def created(c: Mapping[str, Any], run_id: str, started_day: str) -> dict[str, Any]:
    """The record as the old ingest stored a NEW candidate (``started_day``: the ingest's date, ``%Y-%m-%d``)."""
    rec = copy.deepcopy(dict(c))
    rec["run_id"] = run_id
    rec["first_seen_run"] = run_id
    rec["last_observed"] = run_id
    rec["seen_runs"] = 1
    rec.setdefault("first_seen", started_day)
    for a in rec.get("also_seen") or []:
        a.setdefault("first_seen", run_id)
    finalize_provenance(rec)
    found_milestone(rec)
    return rec


def absorb(host: dict[str, Any], c: Mapping[str, Any], run_id: str) -> int:
    """The old ``absorb(host, c, run_id)``. Returns the number of new provenances added (``host`` is changed)."""
    host.setdefault("also_seen", [])
    have = {host.get("source")} | {a.get("source") for a in host["also_seen"]}
    prov = [
        {
            "source": c.get("source", ""),
            "url": c.get("source_url", ""),
            "source_id": c.get("source_id", ""),
            "discovery_tier": c.get("discovery_tier", ""),
            "source_date": c.get("source_date") or "",
        }
    ]
    prov += [dict(a) for a in (c.get("also_seen") or [])]
    added = 0
    for a in prov:
        if a.get("source") and a["source"] not in have:
            host["also_seen"].append({**a, "first_seen": run_id})
            have.add(a["source"])
            added += 1
            host["priority"] = (host.get("priority") or 5) + 2
            host["why"] = (host.get("why") or []) + [f"Cross-source signal: also seen on {a['source']}"]
    hi = host.setdefault("entity_ids", {})
    for k, v in (c.get("entity_ids") or {}).items():
        hi.setdefault(k, v)
    host["last_observed"] = run_id
    host["seen_runs"] = int(host.get("seen_runs") or 1) + 1
    if added:
        finalize_provenance(host)
        found_milestone(host)
    return added


def is_scan_record(value: Any) -> TypeGuard[dict[str, Any]]:
    return isinstance(value, dict) and all(k in value for k in ("decision", "discovery_tier", "source_id"))
