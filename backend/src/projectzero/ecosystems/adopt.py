# ruff: noqa: E501
"""Adopting a candidate watcher (review 022): the old ``domain/coverage.py`` ``adopt_candidate`` (:541-627) at
revision 6c739b9, as a PURE decision. The route layer performs the write (one transaction: the Deal Flow source, its
``source_events`` row and the ``coverage_adoptions`` row); this module only computes it.

The old order is kept exactly (plan revision 3, Codex H-167):

1. no ``confirm``: ``{ok: false, error: "explicit confirmation required"}``;
2. not in the current catalog: ``{ok: false, error: "unknown candidate"}``;
3. already adopted (imported or a row): ``{ok: true, already: true, source_id: <its RECORDED source_id>}``, BEFORE the
   access and URL checks (a historical adoption is answered even when its entry is now restricted or has no URL);
4. an access limitation (captcha / login / paywall / credential / bypass) without ``structured`` access: refused;
5. no http URL: ``{ok: false, error: "candidate has no URL"}``;
6. the source ``"cov-" + id[5:]`` already in the normalized registry: ``{ok: true, already: true, source_id}``, nothing
   written (not even an adoption row);
7. otherwise the adoption: the exact watcher record the old code appended to ``sources.json``, the declaration it
   wrote to ``coverage_sources.json`` and the old answer. The old ``coverage_adopted.json`` entry is the row
   ``{candidate_id, source_id, by, adopted_at}`` (``by`` = ``"operator"``, as before).

``with_adoption`` applies a decision to a ``CoverageInputs`` in memory (as the stored state reads after the write); the
parity driver and the tests use it. Pure: no I/O.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from projectzero.dealflow.sources.normalize import load_registry
from projectzero.ecosystems.coverage import candidate_sources
from projectzero.ecosystems.inputs import CoverageInputs


@dataclass(frozen=True)
class AdoptDecision:
    """``response``: the old answer (HTTP 200). For a real adoption ``source`` (the new Deal Flow source record),
    ``declaration`` ``{families, countries, cities, note}``, ``candidate_id``, ``source_id`` and ``by`` are set;
    otherwise ``source`` is ``None`` and nothing may be written."""

    response: dict[str, Any]
    source: dict[str, Any] | None = None
    declaration: dict[str, Any] | None = None
    candidate_id: Any = None
    source_id: str | None = None
    by: str | None = None

    @property
    def writes(self) -> bool:
        return self.source is not None


def adopt_plan(inputs: CoverageInputs, cand_id: Any, confirm: Any = False) -> AdoptDecision:
    """Explicit, per-source operator action: the candidate becomes a configured discovery-registry watcher (existing page_diff kind, disabled → no:
    enabled but never scanned until the next operator-run scan). Access limitations and audit provenance are carried into the source notes.
    Never bulk, never automatic; a candidate with a login / CAPTCHA / paywall limitation is refused."""
    if not confirm:
        return AdoptDecision({"ok": False, "error": "explicit confirmation required"})
    c = next((x for x in candidate_sources(inputs) if x["id"] == cand_id), None)
    if c is None:
        return AdoptDecision({"ok": False, "error": "unknown candidate"})
    if c.get("adopted"):
        return AdoptDecision({"ok": True, "already": True, "source_id": c["adopted"].get("source_id")})
    lim = str(c.get("access_limitations") or "").lower()
    if re.search(r"captcha|login|paywall|credential|bypass", lim) and c.get("access_mode") != "structured":
        return AdoptDecision(
            {
                "ok": False,
                "error": "access limitation recorded by the audit ({}) — not adopted; keep as manual check".format(
                    c["access_limitations"][:120]
                ),
            }
        )
    if not str(c.get("url") or "").startswith("http"):
        return AdoptDecision({"ok": False, "error": "candidate has no URL"})
    reg_sources = inputs.sources  # the old connectors.load_registry()["sources"]
    sid = "cov-" + c["id"][5:]
    if any(x["id"] == sid for x in reg_sources):
        return AdoptDecision({"ok": True, "already": True, "source_id": sid})
    stage = {
        "pre-company": "pre_company",
        "pre-seed": "pre_seed_seed",
        "seed": "pre_seed_seed",
        "stealth_exit": "pre_company",
    }.get(str(c.get("stage")), "grant" if "grants" in c["families"] else "mixed")
    source = {
        "id": sid,
        "name": c["name"],
        "url": c["url"],
        "kind": "watcher",
        "parser": "page_diff",
        "geo": [c["country"]] if c["country"] else ["EU"],
        "sectors": ["deeptech"],
        "stage": stage,
        "reliability": c.get("reliability") or "medium",
        "freshness": c.get("freshness")
        if c.get("freshness") in ("daily", "weekly", "monthly", "quarterly")
        else "monthly",
        "enabled": True,
        "last_scan": None,
        "last_ok": None,
        "last_result_count": None,
        "failures_in_row": 0,
        "yield": {"kept": 0, "research": 0, "rejected": 0},
        "location": c.get("city") or c.get("country_name", ""),
        "country": c["country"],
        "geo_scope": "country" if c["country"] else "region-eu",
        "notes": "Adopted by Mohamed from the Grok coverage audit ({} {}) · access: {} · limitations: {} · reliability {} · freshness {}".format(
            c["origin"].get("registry_id", ""),
            c["origin"].get("version", ""),
            c.get("access_mode", ""),
            c.get("access_limitations", "") or "none recorded",
            c.get("reliability", ""),
            c.get("freshness", ""),
        ),
        "coverage_families": list(c["families"]),
        "audit_origin": dict(c["origin"]),
    }
    declaration = {
        "families": list(c["families"]),
        "countries": [c["country"]] if c["country"] else ["EU"],
        "cities": [c["city"]] if c["city"] else [],
        "note": "adopted from coverage audit",
    }
    return AdoptDecision(
        {
            "ok": True,
            "source_id": sid,
            "note": "configured — state stays UNKNOWN until a scan retrieves it; HEALTHY only after productive records",
        },
        source=source,
        declaration=declaration,
        candidate_id=cand_id,
        source_id=sid,
        by="operator",
    )


def with_adoption(inputs: CoverageInputs, decision: AdoptDecision, adopted_at: datetime) -> CoverageInputs:
    """``inputs`` as they read after ``decision`` was written at ``adopted_at`` (unchanged for a no-write answer): the
    source appended to the registry and normalized again (as every old read did), and the adoption row added."""
    if decision.source is None or decision.declaration is None:
        return inputs
    sources = load_registry({"sources": [*inputs.sources, decision.source]})["sources"]
    row = {
        "candidate_id": decision.candidate_id,
        "source_id": decision.source_id,
        **decision.declaration,
        "by": decision.by,
        "adopted_at": adopted_at,
    }
    return dataclasses.replace(inputs, sources=sources, adoptions=[*inputs.adoptions, row])
