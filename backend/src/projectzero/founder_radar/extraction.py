"""The old ``domain/founder_radar/extraction.py`` (rev 6c739b9), the part review 026a needs, ported line for line:
``evidence_kind``, ``group_proposals``, ``recommended_ids``, ``research_summary`` and ``_norm_val``.
``extract_proposals`` (one fetched page -> proposals) is review 026b, with the crawl. The patterns and tables are the
catalog's (cut by script).

Only change: ``group_proposals`` works on COPIES of the proposals (the old one ``setdefault``-ed ``evidence_kind`` on
the records it was given, which the ``radar_proposals`` answer then showed: the copies carry it too, so the answer is
the same, and the stored research document is never touched)."""

from __future__ import annotations

import copy
import re
from typing import Any

from projectzero.founder_radar.catalog import DECISION_FIELDS, MACHINE_INFERENCE_FIELDS


def evidence_kind(field: Any) -> str:
    """quoted_fact = the page states the fact; machine_inference = derived by matching / heuristics (never
    bulk-confirmed)."""
    return "machine_inference" if field in MACHINE_INFERENCE_FIELDS else "quoted_fact"


def with_evidence_kind(props: list[Any]) -> list[Any]:
    """Copies of ``props`` with the old ``setdefault("evidence_kind", ...)`` applied (what ``group_proposals`` left on
    the records the ``radar_proposals`` answer lists)."""
    out = copy.deepcopy(props)
    for p in out:
        p.setdefault("evidence_kind", evidence_kind(p["field"]))
    return out


def group_proposals(props: list[Any]) -> list[dict[str, Any]]:
    """One row per normalized field + value: best source first, alternatives collapsed. ``props`` are not changed."""
    props = with_evidence_kind(props)
    conf_rank = {"high": 0, "medium": 1, "low": 2}
    groups: dict[str, list[Any]] = {}
    for p in props:
        gk = p["field"] + "|" + _norm_val(p["person"]["name"] if p.get("person") else p["value"])
        groups.setdefault(gk, []).append(p)
    out = []
    for gk, ps in groups.items():
        ps.sort(
            key=lambda p: (
                0 if p.get("status") == "confirmed" else 1,
                bool(p.get("template_text")),
                p.get("source_rank", 5),
                conf_rank.get(p.get("confidence"), 2),
            )
        )
        best = ps[0]
        field = best["field"]
        disputed = (
            field in DECISION_FIELDS
            and len({_norm_val(q["value"]) for q in props if q["field"] == field and q.get("status") != "rejected"}) > 1
        )
        out.append(
            {
                "key": gk,
                "field": field,
                "value": best["value"],
                "best": best,
                "alternatives": ps[1:],
                "hidden": len(ps) - 1,
                "disputed": disputed,
                "status": best.get("status"),
                "all_ids": [q["id"] for q in ps],
            }
        )
    out.sort(
        key=lambda g: (
            0
            if g["field"] in DECISION_FIELDS
            else 1
            if g["field"] == "access_route"
            else 2
            if g["field"] == "founder"
            else 3,
            g["best"].get("source_rank", 5),
        )
    )
    return out


def recommended_ids(groups: list[dict[str, Any]]) -> list[Any]:
    """Safe bulk set: pending, clean extraction, official-domain source, decision/access fields only (never identity),
    not template text, not disputed."""
    return [
        g["best"]["id"]
        for g in groups
        if g["status"] == "pending"
        and g["field"] in (*DECISION_FIELDS, "access_route")
        and g["best"].get("evidence_kind", evidence_kind(g["field"]))
        == "quoted_fact"  # every machine inference excluded
        and g["best"].get("source_type") == "official domain"
        and not g["best"].get("template_text")
        and not g["disputed"]
        and g["best"].get("confidence") in ("high", "medium")
    ]


def research_summary(dom: dict[str, Any], groups: list[dict[str, Any]], company: dict[str, Any]) -> dict[str, Any]:
    pages = dom.get("pages") or {}
    return {
        "pages_retrieved": sum(1 for r in pages.values() if r.get("status") == 200),
        "pages_blocked": sum(
            1
            for r in pages.values()
            if str(r.get("status")) in ("blocked", "skipped") or str(r.get("reason", "")).startswith("blocked")
        ),
        "facts_proposed": sum(1 for g in groups if g["field"] in DECISION_FIELDS),
        "founder_candidates": sum(1 for g in groups if g["field"] == "founder"),
        "hidden_duplicates": sum(g["hidden"] for g in groups),
        "recommended": len(recommended_ids(groups)),
        "missing_gate": company.get("next_missing", []),
        "confirmed": sum(1 for g in groups if g["status"] == "confirmed"),
    }


def _norm_val(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip().lower()
