# ruff: noqa: E501
# (the old expressions are kept verbatim, long lines included)
"""The routing block of the Validation payload (review 027a): the old ``services/compressor.py::metrics`` at
revision 6c739b9, ported line for line as a pure function. The old one read ``compressor.load()``
(``queue_routing.json``: ``routes`` and ``left_queue``) and ``triage_review.decisions()`` itself; both are parameters
here (``ValidationInputs.queue_routing`` / ``decisions_log``). The Triage Queue Compressor itself (the routing run) is
not part of this port.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from projectzero.dealflow.ranking.names import norm_company
from projectzero.dealflow.triage.view import decisions as read_jsonl
from projectzero.validation.catalog import STATES


def load(doc: Any) -> dict[str, Any]:
    """The old ``compressor.load()`` over the stored document (``or {}`` applied by the reader): a COPY with the
    ``routes`` / ``runs`` defaults (raises as it did for a non-object)."""
    if not isinstance(doc, dict):
        raise TypeError(type(doc).__name__)
    d = dict(doc)
    d.setdefault("routes", {})
    d.setdefault("runs", [])
    return d


def metrics(ents: dict[str, dict[str, Any]] | None, queue_routing: Any, decisions_log: str) -> dict[str, Any]:
    """Validation: is the routing saving Mohamed's attention without making it blind? No accuracy vanity score —
    counts that later outcomes can be checked against. ``ents`` are Validation's entities (stages per company)."""
    d = load(queue_routing)
    every = {**d.get("left_queue", {}), **d["routes"]}
    decisions = {e["candidate_id"]: e for e in read_jsonl(decisions_log) if e.get("candidate_id")}
    reviewed = [(cid, every[cid], decisions[cid]) for cid in decisions if cid in every]

    def was(r: dict[str, Any]) -> str:
        return r.get("underlying") or r.get("state") or ""

    surfaced = [x for x in reviewed if x[1].get("state") in ("NEEDS_MOHAMED", "CALIBRATION_SAMPLE")]
    calib = [x for x in reviewed if x[1].get("state") == "CALIBRATION_SAMPLE"]
    found = [  # compressed by the machine, but Mohamed kept / researched it: a false negative caught
        x for x in reviewed
        if was(x[1]) in ("DEFERRED_LOW_PRIORITY", "MACHINE_WATCH") and x[2].get("verdict") in ("KEEP", "RESEARCH")
    ]  # fmt: skip
    keeps = [x for x in reviewed if x[2].get("verdict") == "KEEP"]
    conv = omar = 0
    for _cid, r, _dec in keeps:
        st = (ents or {}).get(norm_company(str(r.get("name") or "")), {}).get("stages") or set()
        conv += "conviction" in st
        omar += "omar" in st
    counts = Counter(r["state"] for r in d["routes"].values())
    return {
        "total_routed": len(d["routes"]),
        "states": {k: counts.get(k, 0) for k in STATES},
        "surfaced_now": counts.get("NEEDS_MOHAMED", 0) + counts.get("CALIBRATION_SAMPLE", 0),
        "researched_now": counts.get("BACKGROUND_RESEARCH", 0) + counts.get("CASE_PREPARING", 0),
        "deferred_now": counts.get("MACHINE_WATCH", 0) + counts.get("DEFERRED_LOW_PRIORITY", 0),
        "resurfaced": sum(1 for r in every.values() if r.get("resurfaced")),
        "human_reviews_of_routed": len(reviewed),
        "human_override_rate": round(sum(1 for x in reviewed if not x[2].get("agreed")) / len(reviewed), 3) if reviewed else None,
        "surfaced_reviewed": len(surfaced),
        "calibration_reviewed": len(calib),
        "calibration_disagreement": sum(1 for x in calib if x[2].get("verdict") in ("KEEP", "RESEARCH")),
        "false_negatives_found": [{"name": x[1].get("name"), "machine_route": was(x[1]), "your_verdict": x[2].get("verdict")} for x in found][:20],
        "kept": len(keeps),
        "kept_reached_conviction": conv,
        "kept_reached_omar": omar,
        "human_reviews_per_conviction_case": round(len(reviewed) / conv, 1) if conv else None,
        "note": "Routing quality over time: every decision you take on a routed company is compared with where the "
        "machine had put it. Small numbers are anecdotes, not rates.",
    }  # fmt: skip
