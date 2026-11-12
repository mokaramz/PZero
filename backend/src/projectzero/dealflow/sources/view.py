"""``GET /api/sources`` (review 021): the old ``services/discovery.sources_view()`` plus the four fields the old page
read from ``GET /api/inbox`` (decision c). Pure.

    {**coverage_matrix(the normalized registry, counters = stored baseline + deltas), per-source ``feedback``,
     feedback_label / _min_reviewed / _cap, ws_geos, geo_label (extended), report, manual_sources, pages, feeds}

The deltas are added to a COPY for the response only (Codex H-155): ``registry_of`` / the stored records never carry a
derived total, so a toggle cannot fold a delta into the baseline.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from projectzero.dealflow import workspaces
from projectzero.dealflow.ranking import feedback
from projectzero.dealflow.sources import catalog
from projectzero.dealflow.sources.counters import Deltas
from projectzero.dealflow.sources.normalize import QUALITY_KEYS, coverage_matrix, load_registry

YIELD_KEYS = ("kept", "research", "rejected")


def with_deltas(reg: dict[str, Any], deltas: Deltas) -> dict[str, Any]:
    """A copy of the normalized registry whose ``quality`` / ``yield`` are the stored baseline plus the deltas."""
    out = copy.deepcopy(reg)
    for s in out.get("sources", []):
        d = deltas.get(str(s.get("id"))) if isinstance(s, dict) else None
        if not d:
            continue
        q = s.setdefault("quality", {})
        for k, n in d.get("quality", {}).items():
            if k in QUALITY_KEYS:
                q[k] = max(0, (q.get(k) or 0) + n)
        if d.get("yield"):
            y = s.setdefault("yield", {"kept": 0, "research": 0, "rejected": 0})
            for k, n in d["yield"].items():
                if k in YIELD_KEYS:
                    y[k] = y.get(k, 0) + n
    return out


def sources_view(
    stored: list[dict[str, Any]],
    *,
    ledger: Any,
    deltas: Deltas,
    override: workspaces.Override,
    inbox_rest: Mapping[str, Any],
) -> dict[str, Any]:
    reg = with_deltas(load_registry({"sources": stored}), deltas)
    m = coverage_matrix(reg)
    fbt = feedback.table(ledger)
    empty = feedback.normalize(None)
    for s in m["sources"]:
        s["feedback"] = fbt.get(s["id"]) or feedback.adjustment(s["id"], empty)  # the old feedback.for_source
    m["feedback_label"] = feedback.LABEL
    m["feedback_min_reviewed"] = feedback.MIN_REVIEWED
    m["feedback_cap"] = feedback.CAP
    m["ws_geos"] = workspaces.ws_geos(m["sources"], m["geos"], override)
    m["geo_label"] = {**{t: workspaces.label(t) for ws in m["ws_geos"].values() for t in ws}, **m["geo_label"]}
    # what the page took from GET /api/inbox (the old inbox_view: rest of inbox.json, and the hardcoded lists)
    m["report"] = inbox_rest.get("report", [])
    m["manual_sources"] = catalog.MANUAL_SOURCES
    m["pages"] = catalog.PRE_COMPANY_PAGES
    m["feeds"] = catalog.FEEDS
    return m
