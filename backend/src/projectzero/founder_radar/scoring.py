"""The old ``domain/founder_radar/scoring.py`` (rev 6c739b9), ported line for line (review 026a): access paths, founder
eligibility, the shared Gold/Strong gate (buckets) and the explainable assessment. Only change: ``today`` (the Berlin
day) is a parameter of everything that reads the 90-day recency (``date.today()`` before)."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from projectzero.founder_radar.catalog import _FOUNDER_CLAIM, BUCKETS, NEI, NETWORK_STATES, QUEUE_LABELS
from projectzero.founder_radar.evidence import dedupe_evidence, is_recent, person_recent_activity
from projectzero.founder_radar.identity import identity_resolution
from projectzero.founder_radar.names import is_person_name


def contact_route(p: dict[str, Any]) -> str:
    """A contact route is NOT a warm path: LinkedIn URL, email or a public profile."""
    if p.get("linkedin"):
        return "LinkedIn profile — cold"
    if p.get("email"):
        return "email — cold"
    if p.get("profile_urls"):
        return "public profile — cold"
    return ""


def warm_path(p: Any) -> Any:
    """Genuine warm-path facts only."""
    if p.get("introduced_by_name") or p.get("introduced_by"):
        return "via " + (p.get("introduced_by_name") or p.get("introduced_by"))
    if p.get("intro_route"):
        return p["intro_route"]
    if p.get("linkedin_connection_degree") == 1 and p.get("connection_source") == "linkedin_export":
        return "first-degree LinkedIn connection"
    if p.get("relationship_strength") in ("warm", "strong", "close") or p.get("radar_state") in NETWORK_STATES[2:]:
        return "existing relationship (" + (p.get("relationship_strength") or p.get("radar_state")) + ")"
    return ""


def access_path(p: dict[str, Any]) -> dict[str, Any]:
    w = warm_path(p)
    if w:
        return {"kind": "warm", "label": "Warm path: " + w}
    c = contact_route(p)
    if c:
        return {"kind": "cold", "label": "Contact route: " + c}
    return {"kind": "none", "label": "No access path recorded"}


def founder_eligibility(p: dict[str, Any]) -> dict[str, Any]:
    """Founder eligibility = at least one ATTRIBUTED source showing founder status, active company building, credible
    stealth/building activity, spinout formation, incorporation, accelerator participation, or operator verification.
    Papers, authorship, technical keywords and affiliation never qualify. Pipeline names are claims until resolved."""
    ev = dedupe_evidence(p.get("evidence") or [])
    if p.get("identity_verified_by") == "operator" and str(p.get("founder_status", "")).lower().startswith(
        ("verified", "explicit")
    ):
        return {
            "eligible": True,
            "kind": "operator verified",
            "claim_only": False,
            "evidence": ["operator verification"],
        }
    hits = [
        x
        for x in ev
        if x.get("category") == "entrepreneurial"
        and _FOUNDER_CLAIM.search(str(x.get("claim") or ""))
        and (str(x.get("source_url") or "").startswith("http") or "(claim)" in str(x.get("source") or ""))
    ]  # pipeline claims count as CLAIMS even without a public URL
    if not hits:
        return {"eligible": False, "kind": "none", "claim_only": False, "evidence": []}
    claim_only = all(
        "unverified" in str(x.get("claim") or "").lower() or "(claim)" in str(x.get("source") or "") for x in hits
    )
    kind = (
        "explicit founder"
        if any(re.search(r"\b(founder|co-?founder|cofounder|founding)\b", x["claim"], re.I) for x in hits)
        else "building now"
        if any(re.search(r"stealth|building|incorporat", x["claim"], re.I) for x in hits)
        else "pre-company"
    )
    return {
        "eligible": not claim_only,
        "kind": kind,
        "claim_only": claim_only,
        "evidence": [x["claim"][:110] for x in hits[:3]],
    }


def founder_status_class(p: dict[str, Any]) -> Any:
    fe = founder_eligibility(p)
    if fe["eligible"]:
        return fe["kind"]
    if fe["claim_only"]:
        return "founder claim (unverified)"
    ev = dedupe_evidence(p.get("evidence") or [])
    if any(x.get("category") in ("technical", "technical_theme") for x in ev) and not any(
        x.get("category") == "builder" for x in ev
    ):
        return "researcher"
    return "unknown"


def bucket_of(p: dict[str, Any], a: Any = None, *, today: date) -> tuple[str, list[str]]:
    """Exactly one relevance bucket per person. ``a`` (the assessment being built) receives
    ``recent_activity_used`` / ``company_access``, as before."""
    a = a or {}
    fe = founder_eligibility(p)
    ev = dedupe_evidence(p.get("evidence") or [])
    resolved = p.get("identity_status") in ("resolved", "verified by operator")
    _cc0 = company_context(p, a.get("_companies"), today=today) if a else {}
    route = access_path(p)["kind"] != "none" or bool(
        _cc0.get("access_routes")
    )  # person route OR a confirmed official company route (cold, never warm)
    if fe["eligible"] and (p.get("name_attributed") is False or not is_person_name(p.get("name"))):
        return BUCKETS[2], ["no attributed human name (login / handle only) — not an outreach identity"]
    if fe["eligible"]:
        cc = company_context(p, a.get("_companies"), today=today)
        current_role = fe["kind"] in ("explicit founder", "building now", "operator verified", "pre-company")
        pra_p = person_recent_activity(p, today)
        recent_any = pra_p["recent"] or cc.get(
            "recent", False
        )  # DATED person trajectory OR sourced+dated company activity
        # Gold and Strong share ONE sourced gate; only the access route differs
        missing = [
            k
            for k, v in (
                ("identity", not resolved),
                ("current founder role", not current_role),
                ("sourced active-company status", not cc.get("active")),
                ("sourced current early-stage / timing evidence", cc.get("early") is not True),
                ("sourced company Project A fit", not cc.get("fit")),
                ("recent activity", not recent_any),
            )
            if v
        ]
        a["recent_activity_used"] = (
            ("person: " + pra_p["date"])
            if pra_p["recent"]
            else ("company: " + cc.get("recent_date", ""))
            if cc.get("recent")
            else ""
        )
        if missing:
            return BUCKETS[2], missing  # verified founder, company facts incomplete -> qualification queue
        if not route:
            return BUCKETS[1], ["access path — next action: find access path"]
        if access_path(p)["kind"] == "none":
            a["company_access"] = cc.get("access_routes", [])[0]
        return BUCKETS[0], []
    if fe["claim_only"]:
        return BUCKETS[2], ["identity / company status unresolved"]
    if any(x.get("category") in ("technical", "technical_theme") for x in ev):
        return BUCKETS[3], ["no founder / building evidence"]
    return BUCKETS[4], ["no attributed evidence"]


def assess(p: dict[str, Any], *, today: date) -> dict[str, Any]:
    """Separate, explainable dimensions from verified evidence only. Missing evidence stays NOT ENOUGH INFORMATION.
    Ordering exists ONLY for founder-eligible people in Gold / Strong buckets. Company context comes from
    ``p["_companies"]`` (the queue), as before."""
    ev = dedupe_evidence(p.get("evidence") or [])

    def cat(c: str) -> list[Any]:
        return [x for x in ev if x.get("category") == c]

    def band(items: list[Any], hi: int, med: int) -> str:
        n = len(items)
        return "HIGH" if n >= hi else "MEDIUM" if n >= med else "LOW" if n >= 1 else NEI

    b = {
        "builder": band(cat("builder"), 3, 2),
        "technical_depth": band(cat("technical"), 3, 2),
        "entrepreneurial": band(cat("entrepreneurial"), 2, 1),
        "trajectory": band(cat("trajectory"), 2, 1),
        "talent_magnet": band(cat("talent_magnet"), 2, 1),
        "project_a": band(cat("project_a"), 2, 1),
        "technical_theme_overlap": band(cat("technical_theme"), 2, 1),
    }
    factors = {
        k: [
            x.get("claim", "")[:110]
            for x in cat(
                {
                    "builder": "builder",
                    "technical_depth": "technical",
                    "entrepreneurial": "entrepreneurial",
                    "trajectory": "trajectory",
                    "talent_magnet": "talent_magnet",
                    "project_a": "project_a",
                    "technical_theme_overlap": "technical_theme",
                }[k]
            )
        ][:3]
        for k in b
    }
    status, _ = identity_resolution(p)
    conf = (
        "VERIFIED SOURCES"
        if ev and all(x.get("source_url", "").startswith("http") for x in ev)
        else ("PARTIAL" if ev else "UNRESOLVED")
    )
    fe = founder_eligibility(p)
    pre: dict[str, Any] = {"bands": b, "identity_status": status, "_companies": p.get("_companies")}
    bucket, missing = bucket_of(dict(p, identity_status=status), pre, today=today)
    order = None
    parts: list[tuple[str, int]] = []
    if fe["eligible"] and bucket in BUCKETS[:2] and status in ("resolved", "verified by operator"):
        w = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, NEI: 0}
        parts = [
            (
                k,
                w[v]
                * {
                    "builder": 10,
                    "technical_depth": 8,
                    "entrepreneurial": 14,
                    "trajectory": 12,
                    "talent_magnet": 8,
                    "project_a": 12,
                }[k],
            )
            for k, v in b.items()
            if k != "technical_theme_overlap" and v != NEI
        ]
        order = sum(x for _, x in parts) + (10 if bucket == BUCKETS[0] else 0)
    if fe["eligible"] and bucket == BUCKETS[1] and status not in ("resolved", "verified by operator"):
        order = None
    ap = access_path(p)
    pra = person_recent_activity(p, today)
    used = pre.get("recent_activity_used", "")
    ca = pre.get("company_access")
    if ap["kind"] == "none" and ca:
        ap = {
            "kind": "cold",
            "label": "Contact route: confirmed company route {} — cold".format(ca.get("value", "")),
            "provenance": ca.get("url", ""),
            "company_route": True,
        }
        if order is not None:
            parts.append(("cold company access route ({})".format(ca.get("value", "")), 0))
    queue_label = (
        QUEUE_LABELS["qualifying"]
        if (bucket == BUCKETS[2] and fe["eligible"] and status in ("resolved", "verified by operator"))
        else (QUEUE_LABELS["claim"] if bucket == BUCKETS[2] else "")
    )
    return {
        "bands": b,
        "factors": factors,
        "identity_status": status,
        "evidence_confidence": conf,
        "ordering": order,
        "founder_scorable": fe["eligible"],
        "access": ap,
        "warm": ap["kind"] == "warm",
        "queue_label": queue_label,
        "recent_activity": pra,
        "recent_activity_used": used,
        "last_observed": p.get("last_observed") or p.get("updated") or "",
        "founder_eligibility": fe,
        "founder_status_class": founder_status_class(p),
        "bucket": bucket,
        "missing": missing,
        "ordering_factors": [{"factor": k, "points": v} for k, v in parts]
        + ([{"factor": "gold bucket", "points": 10}] if order is not None and bucket == BUCKETS[0] else []),
        "relationship_strength": p.get("relationship_strength", ""),
        "human_conviction": p.get("human_judgment", "") or p.get("founder_potential", "") or NEI,
    }


def company_context(p: dict[str, Any], companies: Any = None, *, today: date) -> dict[str, Any]:
    """Company facts that the GOLD gate needs for a person (never copied into person evidence)."""
    cs = companies or []
    mine = [c for c in cs if any(f["id"] == p["id"] for f in c["founders"])]
    if not mine:
        return {"active": False, "early": None, "known": False}
    c = max(
        mine,
        key=lambda c: (len(c.get("verified_facts") or {}), c.get("in_pipeline", False), len(c.get("evidence") or [])),
    )  # the best-SOURCED company, not the first alias
    vf = c.get("verified_facts") or {}
    active = "status" in vf and normalized_active(vf["status"]["value"])  # explicit sourced active value only
    fit_val = str(vf["project_a_fit"]["value"]).strip().upper() if "project_a_fit" in vf else ""
    fit = fit_val in ("HIGH", "MEDIUM")  # sourced company-specific fit; LOW/UNKNOWN/empty/unsourced never qualify
    ra = vf.get("recent_activity") or {}
    recent = bool(ra) and is_recent(ra.get("activity_date"), today)  # sourced AND dated within 90 days
    routes = [r for r in (c.get("access_routes") or []) if r.get("value")]
    return {
        "active": active,
        "early": True if c["early_stage_fit"] == "yes" else False if c["early_stage_fit"].startswith("no") else None,
        "known": True,
        "company": c["name"],
        "fit": fit,
        "fit_value": fit_val or "NOT ENOUGH INFORMATION",
        "recent": recent,
        "recent_date": ra.get("activity_date", ""),
        "recent_source": ra.get("source_label", ""),
        "access_routes": routes,
    }


def normalized_active(value: Any) -> bool:
    v = str(value or "").strip().lower()
    if not v or re.search(r"\b(unknown|unclear|planned|inactive|closed|dissolved|acquired|dormant|defunct|wound)\b", v):
        return False
    return bool(
        re.search(
            r"\b(active|operating|trading|live|bootstrapped|profitable|growing|hiring|shipping|in business|funded)\b", v
        )
    )
