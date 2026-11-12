"""Investment Manager Qualified (IMQ) — the old ``domain/imq.py``, ported verbatim (review 011).

A final reputation gate on top of the Verified judgment (``taste.score``): "has this opportunity earned one unit of
Omar's scarce attention NOW?" Derived, explainable, never sends anything. States (only these):
    NOT YET IMQ · IMQ — QUALIFIED NOW · CONFLICT GATED · IMQ — STALE

Gates (unchanged): A score / route, B core case, C evidence safety, D conflict (``potential_conflict`` AND
``unclear`` gate), E timing (a verified, dated trigger within ``TIMING_WINDOW`` = 90 days).

Only change: the clock is a PARAMETER (``today`` for the 90-day window, ``now`` for the persisted timestamps); the old
module read ``date.today()`` / ``datetime.now()``. The founder records are passed in (``plist``); the old default of
loading ``people.json`` is the caller's job (``conviction.inputs``).

Persistence (decision a, Codex 011): ``evaluate`` is pure and runs on every read; ``persist`` runs ONLY on writes, so a
history timestamp is the time a write observed the transition, and the next write appends a pending transition once.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any

from projectzero.conviction import taste

STATES = ["NOT YET IMQ", "IMQ — QUALIFIED NOW", "CONFLICT GATED", "IMQ — STALE"]
VERIFIED_MIN = 80
FOUNDER_BAND = 20  # FOUNDER_LADDER: "Domain insider + technical co-founder" and above
VS_BAND = 14  # VS_LADDER: "Large/expanding market, wedge can grow into a platform" and above
TIMING_WINDOW = 90
TIMING_KINDS = {
    "founder_formation": "fresh founder formation",
    "fundraising": "active / imminent fundraising",
    "incorporation": "fresh incorporation / spinout",
    "trigger": "fresh technical or commercial trigger",
    "window": "documented perishable sourcing window",
}
TIMING_NOT_ESTABLISHED = "NOT YET IMQ — TIMING NOT ESTABLISHED"
RESOLVED_STATES = ("resolved", "verified by operator")
QUALIFIED = "IMQ — QUALIFIED NOW"


def _now(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M")


def _fold(s: Any) -> str:
    folded = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", "", folded).strip()


def _days(iso: Any, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(str(iso)[:10])).days
    except (TypeError, ValueError):
        return None


def founder_names(entry: dict[str, Any]) -> list[str]:
    out = []
    for f in entry.get("founders") or []:
        n = f.get("name") if isinstance(f, dict) else f
        if n and str(n).strip():
            out.append(str(n).strip())
    return out


def founder_identities(entry: dict[str, Any], plist: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Founder Radar identity state of every named founder: resolved / unresolved / no record.
    Founder names are claims until a person record resolves them."""
    out = []
    for n in founder_names(entry):
        k = _fold(n)
        p = next(
            (p for p in plist if _fold(p.get("name")) == k or k in [_fold(a) for a in p.get("aliases") or []]), None
        )
        if p is None:
            out.append({"name": n, "status": "no Founder Radar record", "resolved": False, "person_id": ""})
        else:
            # same default as founder_radar.migrate_person
            st = p.get("identity_status", "") or (
                "verified by operator" if p.get("provenance") == "user_provided" else "needs identity resolution"
            )
            out.append({"name": n, "status": st, "resolved": st in RESOLVED_STATES, "person_id": p["id"]})
    return out


def timing_evidence(entry: dict[str, Any], research: dict[str, Any] | None, today: date) -> dict[str, Any]:
    """A dated, sourced reason to care NOW. Never derived from undated text, scout reports or founder statements."""
    cands = []
    t = entry.get("imq_trigger") or {}
    if t.get("date") and t.get("url") and t.get("fact") and t.get("by") == "operator":
        cands.append(
            {
                "kind": t.get("kind", "trigger"),
                "label": TIMING_KINDS.get(t.get("kind"), t.get("kind", "trigger")),  # type: ignore[arg-type]
                "date": t["date"],
                "source": t["url"],
                "fact": t["fact"],
                "origin": "operator-recorded sourced trigger",
            }
        )
    vf = (research or {}).get("verified_facts") or {}
    for field, lab in (
        ("recent_activity", "fresh technical or commercial trigger"),
        ("funding", "active / imminent fundraising"),
    ):
        f = vf.get(field) or {}
        d0 = f.get("activity_date") or ""
        if f.get("confirmed") and d0 and str(f.get("source_url", "")).startswith("http"):
            cands.append(
                {
                    "kind": field,
                    "label": lab,
                    "date": d0,
                    "source": f["source_url"],
                    "fact": f.get("claim", ""),
                    "origin": "confirmed company fact (Founder Radar research)",
                }
            )
    fresh = [c for c in cands if (n := _days(c["date"], today)) is not None and 0 <= n <= TIMING_WINDOW]
    if fresh:
        best = sorted(fresh, key=lambda c: c["date"], reverse=True)[0]
        return {"established": True, **best, "days": _days(best["date"], today)}
    stale = sorted([c for c in cands if _days(c["date"], today) is not None], key=lambda c: c["date"], reverse=True)
    if stale:
        return {
            "established": False,
            "latest": stale[0],
            "why": "latest dated trigger ({}, {}) is older than {} days".format(
                stale[0]["label"], stale[0]["date"], TIMING_WINDOW
            ),
        }
    return {
        "established": False,
        "why": "no verified, dated why-now trigger recorded (fundraising timing '{}' is a label, not dated evidence)".format(
            entry.get("fundraising_timing", "unknown")
        ),
    }


def evaluate(
    entry: dict[str, Any],
    plist: list[dict[str, Any]],
    research: dict[str, Any] | None,
    contradictions: list[dict[str, Any]] | None,
    *,
    today: date,
) -> dict[str, Any]:
    """Derived IMQ state + exact blockers. Pure read: never writes, never sends."""
    sc = taste.score(entry)
    s = entry.get("scores") or {}
    ver = entry.get("verified") or {}
    blockers: list[str] = []
    conflict = entry.get("conflict", "none")
    conflict_gated = conflict in ("potential_conflict", "unclear")
    if conflict_gated:
        blockers.append(
            f"D · unresolved Project A portfolio conflict ({taste.CONFLICT_LABELS.get(conflict, conflict)}) — ask Omar before anything"
        )
    route = (
        "verified"
        if (sc["fully_verified"] and sc["verified"] >= VERIFIED_MIN)
        else ("outlier" if sc["outlier_ok"] else "")
    )
    if not route:
        if not sc["fully_verified"]:
            blockers.append(
                "A · score not eligible: unverified {} (Verified score is withheld until checked)".format(
                    ", ".join(sc["missing"])
                )
            )
        elif sc["verified"] < VERIFIED_MIN:
            blockers.append(f"A · Verified score {int(sc['verified'])} < {VERIFIED_MIN} and no outlier route")
    if not (ver.get("founders") and int(s.get("founder", 0)) >= FOUNDER_BAND):
        blockers.append(
            "B · founder strength not substantial and verified (band {}/25, founders verified: {})".format(
                s.get("founder", 0), bool(ver.get("founders"))
            )
        )
    if int(s.get("venture_scale", 0)) < VS_BAND:
        blockers.append(
            "B · venture-scale potential below the 'large / expanding market' band ({}/19)".format(
                s.get("venture_scale", 0)
            )
        )
    ids = founder_identities(entry, plist)
    if not ids:
        blockers.append("C · no named founder on the record — identity cannot be resolved")
    for i in ids:
        if not i["resolved"]:
            blockers.append("C · founder identity not resolved: {} ({})".format(i["name"], i["status"]))
    open_contra = [
        c
        for c in (contradictions or [])
        if str(c.get("state", "")).upper() == "CONTRADICTION" and not c.get("resolved")
    ]
    for c in open_contra:
        blockers.append("C · unresolved contradiction: {}".format((c.get("text") or c.get("claim") or "")[:120]))
    timing = timing_evidence(entry, research, today)
    if not timing["established"]:
        blockers.append("E · " + TIMING_NOT_ESTABLISHED + " — " + timing["why"])
    prev = entry.get("imq") or {}
    if conflict_gated:
        state = "CONFLICT GATED"
    elif not blockers:
        state = QUALIFIED
    elif prev.get("qualified_at"):
        # RC1.1: once qualified, any lost condition is STALE — also after a CONFLICT GATED spell (was silently NOT YET IMQ)
        state = "IMQ — STALE"
    else:
        state = "NOT YET IMQ"
    reason = ""
    if state == QUALIFIED:
        reason = "{} route (Verified {}), founder band {} verified, venture-scale band {}, identities resolved ({}), timing: {} on {}".format(
            route,
            int(sc["verified"]),
            s.get("founder"),
            s.get("venture_scale"),
            ", ".join(i["name"] for i in ids),
            timing.get("label"),
            timing.get("date"),
        )
    return {
        "state": state,
        "blockers": blockers,
        "route": route,
        "verified_score": sc["verified"],
        "provisional_score": sc["provisional"],
        "fully_verified": sc["fully_verified"],
        "founder_identities": ids,
        "timing": timing,
        "conflict_status": conflict,
        "reason": reason,
        "persisted": prev,
        "stale_reasons": blockers if state == "IMQ — STALE" else [],
        "never_auto_sends": True,
    }


def persist(entry: dict[str, Any], ev: dict[str, Any], *, now: datetime) -> bool:
    """Write the qualification snapshot when IMQ turns on; mark stale when it turns off. True when the entry changed.
    Called on WRITES only (decision a): ``now`` is the time that write observed the transition."""
    prev = entry.get("imq") or {}
    changed = False
    if ev["state"] == QUALIFIED:
        if prev.get("state") != QUALIFIED:
            timing = ev["timing"]
            entry["imq"] = {
                "state": ev["state"],
                "qualified_at": _now(now),
                "verified_score_at_qualification": ev["verified_score"],
                "trigger_date": timing.get("date", ""),
                "trigger_kind": timing.get("label", ""),
                "trigger_source": timing.get("source", ""),
                "qualification_reason": ev["reason"],
                "conflict_status": ev["conflict_status"],
                "route": ev["route"],
                "evidence_snapshot": {
                    "scores": dict(entry.get("scores") or {}),
                    "verified": dict(entry.get("verified") or {}),
                    "founder_identities": ev["founder_identities"],
                    "timing": {k: timing.get(k) for k in ("kind", "date", "source", "fact", "origin")},
                    "earliness": entry.get("earliness"),
                    "archetype": entry.get("archetype"),
                },
                "history": [*(prev.get("history") or []), {"on": _now(now), "to": ev["state"]}],
            }
            changed = True
    elif (
        prev.get("qualified_at")
        and prev.get("state") != ev["state"]
        and ev["state"] in ("IMQ — STALE", "CONFLICT GATED")
    ):
        prev["state"] = ev["state"]
        prev["stale_since"] = _now(now)
        prev["stale_reasons"] = ev["blockers"]
        prev.setdefault("history", []).append({"on": prev["stale_since"], "to": ev["state"], "why": ev["blockers"][:3]})
        changed = True
    return changed


def record_trigger(
    entry: dict[str, Any], kind: Any, when: Any, url: Any, fact: Any, confirm: bool, *, now: datetime, today: date
) -> dict[str, Any]:
    """Operator-recorded, sourced, dated why-now trigger (never inferred). Same evidence rules as public company facts.
    (Review 024: the old ``record_trigger``; ``now`` is the Berlin wall clock, ``today`` the Berlin day.)"""
    from projectzero.evaluator.evidence import add_evidence, valid_activity_date  # lazy: the evaluator imports imq

    if not confirm:
        return {"ok": False, "error": "explicit confirmation required"}
    if kind not in TIMING_KINDS:
        return {"ok": False, "error": "trigger kind must be one of: " + ", ".join(TIMING_KINDS)}
    if not valid_activity_date(when, today):
        return {"ok": False, "error": "trigger date must be YYYY-MM-DD and not in the future"}
    ev = add_evidence("trajectory", url, "why-now trigger", fact, activity_date=when, now=now, today=today)
    if not ev["ok"]:
        return ev
    entry["imq_trigger"] = {
        "kind": kind,
        "label": TIMING_KINDS[kind],
        "date": str(when)[:10],
        "url": url,
        "fact": fact,
        "by": "operator",
        "recorded": _now(now),
    }
    return {"ok": True, "trigger": entry["imq_trigger"]}
