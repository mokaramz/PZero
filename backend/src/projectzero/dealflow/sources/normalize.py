"""The registry as the old ``connectors.load_registry()`` returned it, and the old ``coverage_matrix()`` (review 021).

Ported line for line from ``domain/connectors.py`` at revision 6c739b9 (``_apply_repairs``, the post-load defaults of
``load_registry`` and ``coverage_matrix``); the only changes are the inputs (a registry dict instead of a file read)
and the ``sources_v2`` import (the catalog holds those entries). The old normalization ran on EVERY read and was
persisted by the next save; here it is applied to a copy on read (decision b), and a toggle stores the normalized
record. ``tests/dealflow/test_sources_catalog.py`` checks the literals against the old module. Pure: no I/O.
"""

from __future__ import annotations

import copy
from typing import Any

from projectzero.dealflow.sources import catalog

QUALITY_KEYS = (
    "candidates_found",
    "attention_queue",
    "researched",
    "kept",
    "radar",
    "sent_to_omar",
    "omar_positive",
    "omar_negative",
)

# fmt: off
_ETH_DINFK = {
    "id": "ch-eth-dinfk",
    "name": "ETH D-INFK spin-offs (static departmental list)",
    "url": "https://inf.ethz.ch/department/spin-offs/spin-offs-list.html",
    "kind": "watcher",
    "parser": "page_diff",
    "geo": ["CH"],
    "sectors": ["ai_sw", "deeptech", "robotics"],
    "stage": "pre_company",
    "reliability": "medium",
    "freshness": "monthly",
    "enabled": True,
    "last_scan": None,
    "last_ok": None,
    "last_result_count": None,
    "failures_in_row": 0,
    "yield": {"kept": 0, "research": 0, "rejected": 0},
    "location": "Zurich, Switzerland",
    "country": "Switzerland",
    "geo_scope": "country",
    "_repair_v": 2,
    "notes": "Server-rendered partial supplement for the JS-only official ETH list (computer-science spin-offs only).",
}


def _apply_repairs(reg: dict[str, Any]) -> dict[str, Any]:
    for s in reg.get("sources", []):
        for cond, upd in catalog._REPAIRS:
            try:
                if cond(s) and s.get("_repair_v") != 2:  # type: ignore[no-untyped-call]  # the old lambdas
                    s.update(upd)
            except Exception:
                pass
        s["_repair_v"] = 2
    if not any(s["id"] == "ch-eth-dinfk" for s in reg.get("sources", [])):
        reg["sources"].append(copy.deepcopy(_ETH_DINFK))
    try:
        _sv2r = catalog  # the old ``from projectzero.domain import sources_v2 as _sv2r``

        have = {s["id"] for s in reg.get("sources", [])}
        for e in _sv2r.registry_entries():
            if e["id"] not in have:
                reg["sources"].append(e)
        for s in reg.get("sources", []):  # repair URLs/notes from previous Phase 2 builds
            rep = _sv2r.URL_REPAIRS.get(s["id"])
            if rep and s.get("url") == rep[0]:
                s["url"] = rep[1]
                s["name"] = rep[2]
                s["hwm"] = {"seen": []}
            multi = _sv2r.URL_REPAIRS_MULTI.get(s["id"])
            if multi and s.get("url") in multi[0]:
                s["url"] = multi[1]
                s["name"] = multi[2]
                s["hwm"] = {"seen": []}
            note = _sv2r.NOTE_REPAIRS.get(s["id"])
            if note and note not in (s.get("notes") or ""):
                s["notes"] = note + " " + (s.get("notes") or "")
    except Exception:
        pass
    return reg


def load_registry(stored: dict[str, Any]) -> dict[str, Any]:
    """The old ``load_registry()`` for an existing registry, on a COPY of ``stored`` (``{"sources": [...]}``)."""
    reg = copy.deepcopy(stored)
    _apply_repairs(reg)
    for s in reg.get("sources", []):
        q = s.setdefault("quality", {})
        for k in QUALITY_KEYS:
            q.setdefault(k, 0)
        if "geo_scope" not in s:
            if s["id"] in ("us-yc-launches", "ca-cdl"):
                s["geo_scope"] = "global"
                s["country"] = ""
                s["location"] = ""
            elif s.get("country") not in ("", "EU", "Europe", None):
                s["geo_scope"] = "country"
            else:
                s["geo_scope"] = "region-eu"
    return reg


def coverage_matrix(reg: dict[str, Any]) -> dict[str, Any]:
    """Adjustment: POTENTIAL = configured/enabled sources; VERIFIED = sources that have actually returned
    usable candidates (total_results > 0) and are currently healthy. Untested never looks proven."""
    GEOS, SECTORS, KIND_WEIGHT = catalog.GEOS, catalog.SECTORS, catalog.KIND_WEIGHT
    pot = {g: {s: 0.0 for s in SECTORS} for g in GEOS}
    ver = {g: {s: 0.0 for s in SECTORS} for g in GEOS}
    for src in reg["sources"]:
        if not src.get("enabled"):
            continue
        w = KIND_WEIGHT.get(src["kind"], 0.5) * {"high": 1.0, "medium": 0.75, "low": 0.5}[src.get("reliability", "low")]
        healthy = int(src.get("failures_in_row") or 0) < 3
        proven = bool(src.get("total_results")) and src.get("last_ok")
        for g in src.get("geo", []):
            for s in src.get("sectors", []):
                if g in pot and s in pot[g]:
                    pot[g][s] += w
                    if healthy and proven:
                        ver[g][s] += w
    return {
        "geos": GEOS,
        "geo_label": catalog.GEO_LABEL,
        "sectors": SECTORS,
        "sector_label": catalog.SECTOR_LABEL,
        "potential": pot,
        "verified": ver,
        "cells": ver,
        "sources": reg["sources"],
    }
# fmt: on
