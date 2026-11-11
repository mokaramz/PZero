"""Feedback-adjusted sourcing priority — READ path (protected; old ``domain/feedback.py``).

Bounded, ORDERING-ONLY learning from reviewed decisions (Keep / Research / Watch / Reject) and the Manager's explicit
outcomes, kept in a small ledger. One integer per source, applied as an additive ordering term in Deal Flow:

* neutral below ``MIN_REVIEWED`` UNIQUE reviewed companies; capped to [-CAP, +CAP];
* ordering only: it never suppresses fetching, rejects, hides, deletes or disables anything;
* transparent: every candidate carries the adjustment AND the reason.

Unlike the old module this one does no file I/O and keeps no cache: the caller passes the ledger (for now the
imported ``feedback.json`` document, frozen at import; review 008 moves its updates to decision events).
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

from projectzero.dealflow.ranking.names import slug

LABEL = "Feedback-adjusted sourcing priority"
MIN_REVIEWED = 5  # UNIQUE reviewed companies before a source is adjusted
CAP = 3  # adjustment stays within [-CAP, +CAP]
WEIGHTS = {"kept": 2, "research": 1, "watch": 0, "rejected": -2}
OMAR_WEIGHTS = {"positive": 2, "negative": -2}  # the Manager's explicit outcome on a pipeline company
VERSION = 2
NOT_ML = (
    "ordering only — never suppresses fetching, never rejects, hides or deletes a candidate, never disables a source"
)


def empty_ledger() -> dict[str, Any]:
    return {"version": VERSION, "label": LABEL, "decisions": {}, "omar": {}, "history": []}


def normalize(ledger: Any) -> dict[str, Any]:
    """The ledger as the rules read it. Not a dict -> the empty ledger. First-version records stay valid: an outcome
    with one ``source_id`` becomes ``source_ids``; missing links resolve by name at read time. Never mutates input."""
    if not isinstance(ledger, dict):
        return empty_ledger()
    d = copy.deepcopy(ledger)
    for k, v in empty_ledger().items():
        d.setdefault(k, v)
    for e in d["omar"].values():
        if not e.get("source_ids"):
            e["source_ids"] = [e["source_id"]] if e.get("source_id") else []
        e.setdefault("candidate_id", "")
    for e in d["decisions"].values():
        e.setdefault("source_ids", [])
    d["version"] = VERSION
    return d


def source_ids_of(c: Mapping[str, Any]) -> list[str]:
    """Every source that produced this candidate (merged provenance), falling back to the primary source."""
    sids = list(c.get("all_source_ids") or [])
    if not sids and c.get("source_id"):
        sids = [c["source_id"]]
    for a in c.get("also_seen") or []:
        if a.get("source_id") and a["source_id"] not in sids:
            sids.append(a["source_id"])
    return sorted({s for s in sids if s})


def _company_key(company_slug: str, e: Mapping[str, Any], d: Mapping[str, Any]) -> str:
    """One key per company: the originating candidate id when known, else the decided candidate whose name slugs to
    this pipeline slug, else the slug itself."""
    if e.get("candidate_id"):
        return str(e["candidate_id"])
    for cid, dec in d["decisions"].items():
        try:
            if dec.get("name") and slug(dec["name"]) == company_slug:
                return str(cid)
        except Exception:
            continue
    return "slug:" + company_slug


def company_rows(sid: str, d: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """{company_key: {decision, omar, name}} for one source — the unit the threshold counts."""
    rows: dict[str, dict[str, Any]] = {}
    for cid, e in d["decisions"].items():
        if sid in (e.get("source_ids") or []) and e.get("decision") in WEIGHTS:
            rows.setdefault(cid, {"decision": None, "omar": None, "name": e.get("name", "")})["decision"] = e[
                "decision"
            ]
    for company_slug, e in d["omar"].items():
        if sid in (e.get("source_ids") or []) and e.get("outcome") in OMAR_WEIGHTS:
            key = _company_key(company_slug, e, d)
            rows.setdefault(key, {"decision": None, "omar": None, "name": e.get("company", "")})["omar"] = e["outcome"]
    return rows


def source_stats(sid: str, d: Mapping[str, Any]) -> dict[str, int]:
    st = {"kept": 0, "research": 0, "rejected": 0, "watch": 0, "omar_positive": 0, "omar_negative": 0,
          "reviewed": 0, "score": 0}  # fmt: skip
    for r in company_rows(sid, d).values():
        st["reviewed"] += 1
        if r["decision"]:
            st[r["decision"]] += 1
            st["score"] += WEIGHTS[r["decision"]]
        if r["omar"]:
            st["omar_" + r["omar"]] += 1
            st["score"] += OMAR_WEIGHTS[r["omar"]]
    return st


def round_away(x: float) -> int:
    """Round half away from zero (not Python's banker's rounding)."""
    return int(math.copysign(math.floor(abs(x) + 0.5), x))


def adjustment(sid: str, d: Mapping[str, Any]) -> dict[str, Any]:
    st = source_stats(sid, d)
    n = st["reviewed"]
    parts = []
    if st["kept"]:
        parts.append(f"{st['kept']} kept")
    if st["research"]:
        parts.append(f"{st['research']} research")
    if st["watch"]:
        parts.append(f"{st['watch']} watch")
    if st["rejected"]:
        parts.append(f"{st['rejected']} rejected")
    if st["omar_positive"]:
        parts.append(f"Omar +{st['omar_positive']}")
    if st["omar_negative"]:
        parts.append(f"Omar −{st['omar_negative']}")  # U+2212 MINUS SIGN, as in the old reason text
    counts = ", ".join(parts) if parts else "no reviewed companies"
    if n < MIN_REVIEWED:
        return {
            "source_id": sid,
            "adjustment": 0,
            "reviewed": n,
            "active": False,
            "stats": st,
            "label": LABEL,
            "reason": f"neutral prior — {n} of {MIN_REVIEWED} reviewed companies needed before this source is "
            f"adjusted ({counts})",
        }
    adj = max(-CAP, min(CAP, round_away(CAP * st["score"] / (2.0 * n))))
    return {
        "source_id": sid,
        "adjustment": adj,
        "reviewed": n,
        "active": True,
        "stats": st,
        "label": LABEL,
        "reason": f"{n} reviewed companies ({counts}) → net {st['score']:+d} over {n} → {adj:+d} "
        f"(cap ±{CAP}, ordering only)",
    }


def table(ledger: Any) -> dict[str, dict[str, Any]]:
    """{source_id: adjustment} for every source with any feedback in the ledger."""
    d = normalize(ledger)
    sids: set[str] = set()
    for e in d["decisions"].values():
        sids.update(e.get("source_ids") or [])
    for e in d["omar"].values():
        sids.update(e.get("source_ids") or [])
    return {sid: adjustment(sid, d) for sid in sorted(sids)}


def for_candidate(c: Mapping[str, Any], tbl: Mapping[str, Any]) -> dict[str, Any]:
    """The candidate's feedback block. Several producing sources add up, capped."""
    sids = source_ids_of(c)
    per = [tbl.get(s) or adjustment(s, empty_ledger()) for s in sids]
    total = max(-CAP, min(CAP, sum(p["adjustment"] for p in per)))
    if not sids:
        reason = "no source id on this candidate — neutral"
    elif len(per) == 1:
        reason = per[0]["reason"]
    else:
        reason = "; ".join(
            f"{p['source_id']} {p['adjustment']:+d} ("
            + (
                f"neutral prior, {p['reviewed']}/{MIN_REVIEWED} reviewed"
                if not p["active"]
                else f"{p['reviewed']} reviewed"
            )
            + ")"
            for p in per
        )
        reason += f" → sum {sum(p['adjustment'] for p in per):+d} capped to ±{CAP}"
    return {
        "label": LABEL,
        "adjustment": total,
        "active": any(p["active"] for p in per),
        "reason": reason,
        "sources": [
            {
                "source_id": p["source_id"],
                "adjustment": p["adjustment"],
                "reviewed": p["reviewed"],
                "active": p["active"],
            }
            for p in per
        ],
        "not_ml": NOT_ML,
    }
