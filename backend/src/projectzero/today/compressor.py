# ruff: noqa: E501
# (the old expressions are kept verbatim, long lines included)
"""The read side of the Triage Queue Compressor (review 030a): the old ``services/compressor.py`` ``settings``
(:100-105) and ``summary`` (:606-644) at revision 6c739b9, ported line for line as pure functions. The old ones read
``config.json``, ``queue_routing.json`` (through ``load``) and the inbox themselves; here they are parameters
(``TodayInputs.operator.config``, ``queue_routing``, ``live_ids``). The compressor RUN (the second-pass model and
case preparation) is not ported: the routes are the imported snapshot (decision f) and the job is always idle.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Set
from typing import Any

from projectzero.today.catalog import DEFAULTS, LABEL, STATES, _job
from projectzero.validation.routing import load


def settings(config: Any) -> dict[str, Any]:
    """Old ``settings()``; ``config``: the tolerant ``config.json`` (``or {}`` applied here, as before)."""
    cfg: Any = config or {}
    over: Any = (
        cfg.get("attention_budget") if isinstance(cfg, dict) and isinstance(cfg.get("attention_budget"), dict) else {}
    )
    return {**DEFAULTS, **{k: v for k, v in over.items() if k in DEFAULTS}}


def job() -> dict[str, Any]:
    """Old ``job()``: no compression run is ever started by the new system (decision f), so the state is idle."""
    return dict(_job)


def summary(queue_routing: Any, live_ids: Set[str], config: Any) -> dict[str, Any]:
    """What Today shows: derived counts, the attention budget, today's review list. Fast: reads the stored routes."""
    d = load(queue_routing)
    routes = d["routes"]
    s_cfg = settings(config)
    live = live_ids
    routes = {cid: r for cid, r in routes.items() if cid in live}  # Mohamed decided since the run → out of the queue
    counts = Counter(r["state"] for r in routes.values())
    review = sorted(
        (
            {"candidate_id": cid, **{k: r.get(k) for k in ("name", "state", "reason", "priority", "machine_proposal", "resurfaced")}}
            for cid, r in routes.items()
            if r["state"] in ("NEEDS_MOHAMED", "CALIBRATION_SAMPLE")
        ),
        key=lambda x: (x["state"] != "NEEDS_MOHAMED", -(x["priority"] or 0), x["candidate_id"]),  # deterministic
    )  # fmt: skip
    limit = int(s_cfg["human_review_daily_limit"])
    return {
        "at": d.get("at"),
        "total": len(routes),
        "counts": {k: counts.get(k, 0) for k in STATES},
        "needs_mohamed": counts.get("NEEDS_MOHAMED", 0),
        "calibration": counts.get("CALIBRATION_SAMPLE", 0),
        "today": review[:limit],
        "queued_beyond_budget": max(0, len(review) - limit),
        "limit": limit,
        "resurfaced": sum(1 for r in routes.values() if r.get("resurfaced")),
        "elsewhere": d.get("elsewhere", 0),
        "job": job(),
        "labels": LABEL,
        "note": "Routing priority orders your attention only — never a score or a decision. Every company stays in "
        "Deal Flow; you can keep, promote, watch or drop any of them.",
    }
