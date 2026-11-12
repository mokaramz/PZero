"""The old ``domain/founder_radar/leads.py`` (rev 6c739b9), ported line for line (review 026a): the output-first founder
leads. Changes: ``founder_leads`` reads the research document it is GIVEN (the old one loaded
``radar_research.json``) and ``today`` (the Berlin day) is the recency clock. ``HUMAN`` / ``UNKNOWN_LABELS`` are the
catalog's (cut by script)."""

from __future__ import annotations

import re
import urllib.parse
from datetime import date
from typing import Any

from projectzero.founder_radar.catalog import BUCKETS, DECISION_FIELDS, HUMAN, UNKNOWN_LABELS
from projectzero.founder_radar.evidence import is_recent
from projectzero.founder_radar.extraction import evidence_kind
from projectzero.founder_radar.names import _fold, is_organization_name, is_person_name
from projectzero.founder_radar.scoring import access_path


def _quoted_company_facts(dom: dict[str, Any]) -> dict[str, Any]:
    """Clean official-domain quoted facts from the research record — confirmed OR pending (machine view only)."""
    out: dict[str, Any] = {}
    for p in (dom.get("proposals") or {}).values():
        if (
            p.get("field") in DECISION_FIELDS
            and p.get("evidence_kind", evidence_kind(p["field"])) == "quoted_fact"
            and p.get("source_type") == "official domain"
            and not p.get("template_text")
            and p.get("status") not in ("rejected",)
        ):
            cur = out.get(p["field"])
            if (
                cur is None
                or (p.get("status") == "confirmed") > (cur.get("status") == "confirmed")
                or p.get("source_rank", 5) < cur.get("source_rank", 5)
            ):
                out[p["field"]] = p
    return out


def _founder_named_on_official(dom: dict[str, Any], name: Any) -> list[Any]:
    return [
        p
        for p in (dom.get("proposals") or {}).values()
        if p.get("field") == "founder"
        and p.get("status") != "rejected"
        and _fold((p.get("person") or {}).get("name")) == _fold(name)
    ]


def _linkedin_for(dom: dict[str, Any], name: Any) -> Any:
    toks = [t for t in _fold(name).split() if len(t) > 2]
    for p in (dom.get("proposals") or {}).values():
        if (
            p.get("field") == "linkedin_profile"
            and p.get("source_type") == "official domain"
            and p.get("status") != "rejected"
        ):
            slug = p.get("value", "").lower()
            if toks and all(t in slug for t in toks):
                return p
    return None


def founder_verification(p: dict[str, Any], dom: dict[str, Any]) -> dict[str, Any] | None:
    """Sourced evidence that EXPLICITLY connects a plausible human name + founder role + a named company."""
    if not is_person_name(p.get("name")) or p.get("name_attributed") is False:
        return None
    named = _founder_named_on_official(dom, p.get("name", ""))
    if named:
        return {
            "kind": "official page",
            "role": named[0]["person"]["role"],
            "company": named[0]["person"]["company"],
            "url": named[0]["url"],
            "passage": named[0]["passage"],
            "confirmed": any(n.get("status") == "confirmed" for n in named),
        }
    if p.get("identity_verified_by") == "operator" and str(p.get("founder_status", "")).lower().startswith(
        ("explicit", "verified")
    ):
        ev = next(
            (
                e
                for e in (p.get("evidence") or [])
                if e.get("category") in ("entrepreneurial", "identity")
                and str(e.get("source_url", "")).startswith("http")
                and re.search(r"co-?founder|founder|founding", str(e.get("claim", "")), re.I)
            ),
            None,
        )
        if ev:
            return {
                "kind": "operator-confirmed",
                "role": "founder",
                "company": p.get("company") or "",
                "url": ev["source_url"],
                "passage": ev["claim"],
                "confirmed": True,
            }
    return None


def founder_lead(p: dict[str, Any], companies: list[dict[str, Any]], research: Any, today: date) -> dict[str, Any]:
    """One decision-ready founder card. Machine-qualified = clean official-domain quoted facts + founder evidence;
    never a bucket change. Human-confirmed Gold stays the existing shared gate."""
    s = p.get("signal") or {}
    comps = [c for c in companies if any(f["id"] == p["id"] for f in c["founders"])]
    c = max(comps, key=lambda c: (len(c.get("verified_facts") or {}), c.get("in_pipeline", False))) if comps else None
    dom = (research.get("domains") or {}).get(c["key"], {}) if c else {}
    qf = _quoted_company_facts(dom)
    named = _founder_named_on_official(dom, p.get("name", ""))
    fv = founder_verification(p, dom)
    founder_evidence = bool(fv)  # hard admission gate: explicit sourced name + founder role + company
    proof = []
    if fv:
        proof.append(
            {
                "fact": "{} of {} — stated on the company's {}".format(
                    fv["role"].capitalize(),
                    fv["company"] or (c["name"] if c else ""),
                    "official site" if fv["kind"] == "official page" else "public evidence (operator-confirmed)",
                ),
                "passage": fv["passage"],
                "url": fv["url"],
                "source": fv["kind"],
                "kind": "quoted_fact",
                "status": "confirmed" if fv["confirmed"] else "pending",
            }
        )
    for fld in ("founded", "early_stage_signal", "funding", "recent_activity", "status"):
        if fld in qf and len(proof) < 3:
            proof.append(
                {
                    "fact": HUMAN.get(fld, lambda v, fld=fld: f"{fld}: {v}")(qf[fld]["value"]),
                    "passage": qf[fld]["passage"],
                    "url": qf[fld]["url"],
                    "source": qf[fld]["source_label"],
                    "kind": "quoted_fact",
                    "status": qf[fld].get("status"),
                }
            )
    for e in [
        e
        for e in (p.get("evidence") or [])
        if e.get("category") in ("builder", "trajectory") and str(e.get("source_url", "")).startswith("http")
    ]:
        if fv and len(proof) < 3 and not any(pp["passage"] == e.get("claim") for pp in proof):
            proof.append(
                {
                    "fact": e["claim"][:100],
                    "passage": e["claim"],
                    "url": e["source_url"],
                    "source": e.get("source"),
                    "kind": "quoted_fact",
                    "status": "enrichment",
                }
            )  # enrichment only after founder verification
    ra = qf.get("recent_activity")
    pra = s.get("recent_activity") or {}
    why_now = (
        ("Official site: {}".format(re.sub(r"^dated item on (\w+) page \((.*)\)$", r"news on \2", ra["value"])))
        if ra and is_recent(ra.get("activity_date"), today)
        else ("dated activity {} ({})".format(pra.get("date"), pra.get("source")))
        if pra.get("recent")
        else ("Early-stage wording on the official site")
        if "early_stage_signal" in qf
        else ("Founded in {}".format(qf["founded"]["value"]) if "founded" in qf else "No dated signal yet")
    )
    fit_inf = next(
        (
            x
            for x in (dom.get("proposals") or {}).values()
            if x.get("field") == "project_a_fit" and x.get("status") != "rejected"
        ),
        None,
    )
    fit_conf = (c or {}).get("verified_facts", {}).get("project_a_fit")
    project_a = (
        ("confirmed company fit: {}".format(fit_conf["value"]))
        if fit_conf
        else (
            (
                fit_inf["reason"].replace("company description overlaps Project A themes: ", "themes: ")
                + " (machine inference)"
            )
            if fit_inf
            else (
                "person themes: " + ", ".join((s.get("factors") or {}).get("project_a") or [])[:120]
                if (s.get("factors") or {}).get("project_a")
                else "NOT ENOUGH INFORMATION"
            )
        )
    )
    li = _linkedin_for(dom, p.get("name", ""))
    linkedin = p.get("linkedin") or (li["value"] if li else "")
    contacts = (
        [r["value"] for r in ((c or {}).get("access_routes") or [])]
        + [
            x["value"]
            for x in (dom.get("proposals") or {}).values()
            if x.get("field") == "access_route" and x.get("status") == "pending"
        ]
        + ([p["email"]] if p.get("email") else [])
    )
    access = dict(s.get("access") or access_path(p))
    access_kind = access["kind"] if access["kind"] != "none" else ("cold" if contacts or linkedin else "none")
    if access["kind"] == "none" and access_kind == "cold":
        access["label"] = "Contact route: public %s — cold" % (
            "e-mail " + contacts[0] if contacts else "LinkedIn profile found on the official site"
        )
    gates = {
        "founder evidence": founder_evidence,
        "identity resolved": s.get("identity_status") in ("resolved", "verified by operator"),
        "founded / early stage": ("founded" in qf) or ("early_stage_signal" in qf),
        "active status": "status" in qf,
        "recent activity": bool(ra and is_recent(ra.get("activity_date"), today)) or bool(pra.get("recent")),
        "Project A fit": bool(fit_conf) or bool(fit_inf),
        "access route": access_kind != "none",
    }
    unknowns = [UNKNOWN_LABELS.get(k, k) for k, v in gates.items() if not v]
    score = sum(1 for v in gates.values() if v)
    machine = (
        founder_evidence and score >= 4 and (("founded" in qf) or ("early_stage_signal" in qf) or ("status" in qf))
    )
    human_gold = s.get("bucket") == BUCKETS[0]
    standout = (
        (
            "{} is named {} of {} on the company's own site{}.".format(
                p.get("name"),
                fv["role"],
                fv["company"] or (c["name"] if c else ""),
                (" — " + why_now[0].lower() + why_now[1:]) if why_now != "No dated signal yet" else "",
            )
        )
        if fv and fv["kind"] == "official page"
        else (
            "{}: founder status confirmed by you with public evidence{}.".format(
                p.get("name"),
                (" at " + (fv["company"] or c["name"])) if fv and (fv["company"] or c) else "",  # type: ignore[index]
            )
        )
        if fv
        else ("{}: no sourced founder evidence yet.".format(p.get("name")))
    )
    next_action = (
        ("Reach out via %s" % (contacts[0] if contacts else linkedin or "the recorded route"))
        if human_gold
        else (
            "Resolve identity — pair the official-site founder line with this record"
            if not gates["identity resolved"] and fv
            else "Confirm the sourced company facts in the Research Queue"
            if machine
            else (
                "Research the official domain"
                if c and not dom.get("done")
                else "Find founder evidence on an official source"
            )
        )
    )
    return {
        "id": p["id"],
        "name": p.get("name"),
        "company": c["name"] if c else (p.get("company") or "UNKNOWN"),
        "role": (named[0]["person"]["role"] if named else p.get("role") or "role UNKNOWN"),
        "location": p.get("location") or ((c or {}).get("location") or "UNKNOWN"),
        "standout": standout,
        "proof": proof[:3],
        "why_now": why_now,
        "project_a": project_a,
        "linkedin": linkedin,
        "linkedin_search": "https://www.linkedin.com/search/results/people/?keywords="
        + urllib.parse.quote(p.get("name", "") + " " + (c["name"] if c else "")),
        "contacts": contacts[:3],
        "access": access_kind,
        "access_label": access.get("label", ""),
        "unknowns": unknowns,
        "next_action": next_action,
        "machine_qualified": bool(machine),
        "human_gold": bool(human_gold),
        "score": score,
        "founder_verified": bool(fv),
        "founder_verification": fv,
        "identity_status": s.get("identity_status"),
        "bucket": s.get("bucket"),
        "company_key": c["key"] if c else "",
    }


def founder_leads(
    people_rows: list[dict[str, Any]], companies: list[dict[str, Any]], research: Any, today: date, limit: int = 10
) -> dict[str, Any]:
    research = research if research is not None else {"domains": {}}
    leads = []
    for p in people_rows:
        if p.get("radar_state") == "dismissed" or (
            p.get("provenance") == "user_provided" and not (p.get("evidence") or [])
        ):
            continue
        if p.get("invalid_record") or is_organization_name(p.get("name")):
            continue  # never a person
        lead = founder_lead(p, companies, research, today)
        if not lead["founder_verified"]:
            continue  # hard admission gate
        leads.append(lead)
    leads.sort(
        key=lambda ld: (
            not ld["human_gold"],
            not ld["machine_qualified"],
            -ld["score"],
            -len(ld["proof"]),
            ld["name"] or "",
        )
    )
    top = [ld for ld in leads if ld["human_gold"] or ld["machine_qualified"]][:limit]
    near = [ld for ld in leads if ld not in top and (ld["score"] >= 2)][:limit]
    return {"top": top, "near": near, "total_candidates": len(leads)}
