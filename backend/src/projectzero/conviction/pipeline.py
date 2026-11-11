"""The enriched Conviction pipeline — the old ``services/pipeline.pipeline()`` (:79) as a PURE function (review 011).

    build(rest, stored_records, inputs, now) -> {**rest, "signals": [today's record + computed fields]}

Computed per record, exactly as the old read did: ``slug`` (old ``radar.slug``), ``sc`` (``taste.score``, read on a
neutral copy and flagged with ``data_warning`` when a stored value can't be read), ``days_old``, ``discovery_status``,
``archetype_name``, ``imq_eval`` (``imq.evaluate`` with the Founder Radar facts and Active Evaluator contradictions),
and ``op`` (``operator.operator_status``).

**Reads never write** (decision a): the old read persisted the IMQ snapshot (``imq.persist``) on every call. Here
``imq_eval.persisted`` is the STORED snapshot, unchanged; ``persist`` runs only on writes (``conviction.store``).
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from projectzero.conviction import imq, taste
from projectzero.conviction.operator import OperatorInputs, operator_status
from projectzero.conviction.records import (
    COMPUTED_FIELDS,
    DATA_WARNING_RECORD,
    discovery_status,
    readable,
    records,
    safe_score,
)
from projectzero.dealflow.ranking.names import slug as radar_slug

log = logging.getLogger(__name__)

# the old founder_radar.DECISION_FIELDS (constants.py), for ``verified_facts``
DECISION_FIELDS = (
    "founded", "status", "stage", "funding", "project_a_fit", "recent_activity", "early_stage_signal", "official_domain",
)  # fmt: skip


@dataclass(frozen=True)
class ImqInputs:
    """What ``imq.evaluate`` reads besides the record (the old pipeline loaded these per request)."""

    people: list[dict[str, Any]] = field(default_factory=list)  # people.json records, in file order
    radar_companies: Any = field(default_factory=dict)  # radar_companies.json "companies" ({} if unreadable)
    evaluations: Any = field(default_factory=lambda: {"sessions": {}})  # evaluations.json ({"sessions": {}} if not)


@dataclass(frozen=True)
class Inputs:
    imq: ImqInputs = field(default_factory=ImqInputs)
    operator: OperatorInputs = field(default_factory=OperatorInputs)


def verified_facts(stored: dict[str, Any]) -> dict[str, Any]:
    """Old ``founder_radar.verified_facts``: only structured, confirmed facts with a public source count."""
    out = {}
    for f in stored.get("facts") or []:
        if (
            f.get("field") in DECISION_FIELDS
            and f.get("confirmed")
            and str(f.get("source_url", "")).startswith("http")
            and f.get("claim")
        ):
            out[f["field"]] = f
    return out


def open_contradictions(slug: str, d: Any) -> list[dict[str, Any]]:
    """Old ``evaluator.open_contradictions``."""
    out = []
    for s in d["sessions"].values():
        if (s.get("subject") or {}).get("slug") == slug:
            out += [c for c in s["ledger"] if c["state"] == "CONTRADICTION" and not c.get("resolved")]
    return out


def evaluate_imq(e: dict[str, Any], inp: ImqInputs, now: datetime) -> dict[str, Any]:
    """``imq.evaluate`` for one enriched record (``slug`` and, if set, ``data_warning`` already on it)."""
    comps = inp.radar_companies
    st = next((v for v in comps.values() if isinstance(v, dict)
               and imq._fold(v.get("name")) == imq._fold(e["company"])), None)  # fmt: skip
    research = {"verified_facts": verified_facts(st)} if st else None
    try:
        contra = open_contradictions(e["slug"], inp.evaluations)
    except Exception:  # an unreadable Active Evaluator session never hides the company
        contra = []
    src = e if "data_warning" not in e else readable(e)
    return imq.evaluate(src, inp.people, research, contra, today=now.date())


def enrich(e: dict[str, Any], inp: ImqInputs, now: datetime) -> dict[str, Any]:
    """Adds the computed fields to ``e`` (in place, like the old read) and returns the IMQ evaluation."""
    e.setdefault("status", "new")
    e["slug"] = radar_slug(e["company"])
    e["sc"] = safe_score(e)
    # RC1.1: read-time tolerance for hand-edited founder rows
    if isinstance(e.get("founders"), list) and any(not isinstance(f, dict) for f in e["founders"]):
        e["founders"] = [f if isinstance(f, dict) else {"name": str(f)} for f in e["founders"] if f]
    e["days_old"] = taste.days_since(e.get("discovery_date", ""), now.date())
    e["discovery_status"] = discovery_status(e)
    arch = e.get("archetype")
    a = taste.ARCHETYPE_BY_ID.get(arch or 0) if isinstance(arch, (int, type(None))) else None
    e["archetype_name"] = f"#{a[0]} {a[1]}" if a else "—"
    ev = evaluate_imq(e, inp, now)
    ev["persisted"] = e.get("imq") or {}  # the stored snapshot (reads never write)
    e["imq_eval"] = ev
    return ev


def view_record(stored: dict[str, Any], inp: ImqInputs, now: datetime) -> dict[str, Any]:
    """One record as the old read showed it (before ``op``). Never changes ``stored``."""
    e = copy.deepcopy(stored)
    try:
        enrich(e, inp, now)
    except Exception as ex:
        log.warning("conviction: %s could not be fully interpreted (%s)", e.get("company"), type(ex).__name__)
        e["data_warning"] = DATA_WARNING_RECORD
        e.setdefault("slug", radar_slug(str(e["company"])))
        e.setdefault("sc", taste.score(readable({"company": e["company"]})))
        e.setdefault("imq_eval", {"state": "UNKNOWN", "blockers": ["record could not be interpreted"]})
    return readable(e) | {k: e[k] for k in COMPUTED_FIELDS if k in e} if "data_warning" in e else e


def build(rest: dict[str, Any], stored: list[Any], inputs: Inputs, now: datetime) -> dict[str, Any]:
    """The old ``GET /api/pipeline`` body: ``{**rest, "signals": [...]}``, in stored order."""
    view = [view_record(e, inputs.imq, now) for e in records(stored, ("company",))]
    for e in view:
        e["op"] = operator_status(e, inputs.operator.cases.get(str(e.get("slug"))), inputs.operator, now)
    return {**rest, "signals": view}
