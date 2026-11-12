# ruff: noqa: E501
"""The old ``domain/founder_radar/companies.py`` (rev 6c739b9), ported line for line (review 026a): company leads,
sourced facts, immutable founder references and the research priority.

Changes (decisions a, b, g):
* ``companies_queue`` never writes and never changes its input. It returns the queue AND ``Refs``: the companies
  document the old code would have saved (every grouped key ``setdefault``-ed, the new founder references added) and
  whether that differs from the input. The old ``_dirty`` flag (its ``any()`` short-circuit leaked it into 11 of the
  19 real records) is never set and is stripped from the returned document.
* The pipeline signals, the companies document and the research document are parameters (the old code loaded
  ``real_data.json``, ``radar_companies.json`` and ``radar_research.json``).
* The clock: ``now`` (Berlin wall clock) for the founder reference ``created`` and fact ``recorded``; ``today`` for the
  founding age and the 90-day priority window.
* ``research_priority`` reads the SORTED theme terms (``catalog._theme_terms``).
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from projectzero.conviction.pipeline import verified_facts as verified_facts
from projectzero.founder_radar.catalog import _NON_OFFICIAL, BUCKETS, DECISION_FIELDS, EARLY_STAGES, _theme_terms
from projectzero.founder_radar.evidence import add_evidence, valid_activity_date
from projectzero.founder_radar.names import _canon_domain, _fold, hashlib_sha, is_person_name
from projectzero.founder_radar.scoring import access_path
from projectzero.network.view import berlin_now


def _pipeline_index(signals: Any) -> dict[str, Any]:
    sig = signals if isinstance(signals, list) else []
    return {_fold(e.get("company")): e for e in sig if e.get("company")}


def company_key(name: Any, domain: Any = "", cid: Any = "") -> str:
    """Stable company id -> canonical domain -> normalized name. Used by the queue and by dedupe."""
    if cid:
        return "id:" + str(cid)
    if domain:
        return "dom:" + _canon_domain(domain)
    return "name:" + _fold(name)


def resolve_domain(
    name: Any, pipeline_entry: dict[str, Any], stored: dict[str, Any], founders_rows: list[dict[str, Any]]
) -> tuple[str, str]:
    """Order: pipeline website -> confirmed official_domain fact -> official-looking domains linked to the claimed
    founders (candidate, labelled) -> UNKNOWN. Never guessed from the company name."""
    if pipeline_entry.get("website"):
        return _canon_domain(pipeline_entry["website"]), "pipeline website"
    vf = verified_facts(stored)
    if "official_domain" in vf:
        return _canon_domain(vf["official_domain"]["value"]), "confirmed official_domain fact"
    cands: dict[str, int] = {}
    for p in founders_rows:
        for u in (
            list(p.get("profile_urls") or [])
            + [e.get("source_url", "") for e in (p.get("evidence") or [])]
            + [x.get("url", "") for x in (p.get("sources") or [])]
        ):
            dmn = _canon_domain(u)
            if (
                dmn
                and "." in dmn
                and not any(k in dmn for k in _NON_OFFICIAL)
                and (
                    _fold(name).replace(" ", "") in dmn.replace("-", "").replace(".", "")
                    or _fold(name).split(" ")[0] in dmn
                )
            ):
                cands[dmn] = cands.get(dmn, 0) + 1
    if cands:
        return max(cands, key=cands.__getitem__), (
            "candidate domain (linked to claimed founders — confirm as official_domain)"
        )
    return "", "UNKNOWN"


def sourced_fact(
    field: Any,
    value: Any,
    claim: Any,
    url: Any,
    label: Any,
    confirm: Any,
    activity_date: Any = None,
    *,
    now: datetime,
    today: date,
) -> dict[str, Any]:
    """One structured, sourced company fact. Evidence binds to exactly this field."""
    if field not in DECISION_FIELDS:
        return {"ok": False, "error": f"unknown decision field {field!r}"}
    ev = add_evidence("company", url, label, claim, now=now, today=today)
    if not ev["ok"]:
        return ev
    if not confirm:
        return {"ok": False, "error": "operator confirmation required"}
    v = value
    if field == "recent_activity" and not valid_activity_date(activity_date, today):
        return {
            "ok": False,
            "error": "recent_activity needs an explicit activity date YYYY-MM-DD (not in the future, not the recording time)",
        }
    if field == "early_stage_signal":
        v = (
            True
            if str(value).strip().lower() in ("true", "yes", "1")
            else False
            if str(value).strip().lower() in ("false", "no", "0")
            else None
        )
        if v is None:
            return {"ok": False, "error": "early_stage_signal must be yes/no"}
    elif not str(value or "").strip():
        return {"ok": False, "error": "value required"}
    fact = {
        "field": field,
        "value": v,
        "claim": claim.strip(),
        "source_url": url.strip(),
        "source_label": label.strip(),
        "confirmed": True,
        "recorded": now.strftime("%Y-%m-%d %H:%M"),
        "by": "operator",
    }
    if field == "recent_activity":
        fact["activity_date"] = str(activity_date).strip()
    return {"ok": True, "fact": fact}


def legacy_claims(stored: dict[str, Any]) -> dict[str, Any]:
    return {
        k: stored[k]
        for k in ("founded", "status", "stage", "funding", "project_a_fit", "early_stage_signal")
        if k in stored and stored[k] not in ("", None)
    }


def founder_ref(stored: Any, key: str, p: dict[str, Any], *, now: datetime) -> tuple[dict[str, Any], bool]:
    """Stable, immutable founder reference for a person under a company lead: id + claimed name/aliases as first seen
    (never the mutable display name). (the reference, whether it was created now) — the old ``_dirty`` flag."""
    refs = stored.setdefault("founder_refs", {}) if isinstance(stored, dict) else {}
    rid = "ref-" + hashlib_sha(key + "|" + p["id"])
    created = False
    if rid not in refs:
        nm = p.get("name") or ""
        handle_only = p.get("name_attributed") is False or not is_person_name(nm)
        refs[rid] = {
            "founder_ref_id": rid,
            "person_id": p["id"],
            "claimed_name": "" if handle_only else nm,
            "aliases": [a for a in (p.get("aliases") or []) if a] + ([nm] if handle_only and nm else []),
            "handle_only": handle_only,
            "created": now.strftime("%Y-%m-%d %H:%M"),
        }
        created = True
    return refs[rid], created


def founder_ref_matches(ref: dict[str, Any], proposed_name: Any) -> bool:
    """Normalized claimed name / known alias must match the proposal's human name; handle-only refs match only via an
    explicit pairing."""
    if ref.get("handle_only"):
        return False
    names = [ref.get("claimed_name", ""), *list(ref.get("aliases") or [])]
    return _fold(proposed_name) in {_fold(n) for n in names if n and is_person_name(n)}


@dataclass(frozen=True)
class Refs:
    """What the old ``companies_queue`` would have saved: ``doc`` is the companies document with every grouped key
    present and the new founder references added (``_dirty`` stripped everywhere); ``created`` the keys whose record
    gained a reference; ``changed``: a reference was created or a leaked ``_dirty`` stripped (the old code saved only
    when a record was dirty)."""

    doc: dict[str, Any]
    created: list[str] = field(default_factory=list)
    changed: bool = False


def loaded_companies(doc: Any) -> dict[str, Any]:
    """The old ``load_companies()`` over a stored body (missing -> ``{"companies": {}}``), as a deep copy."""
    return copy.deepcopy(doc) if doc is not None else {"companies": {}}


def companies_queue(
    people_rows: list[dict[str, Any]],
    *,
    companies_doc: Any,
    research_doc: Any,
    signals: Any,
    now: datetime,
    today: date,
) -> tuple[list[dict[str, Any]], Refs]:
    """Additive canonical company records: claimed founders grouped under ONE company lead. Company evidence lives
    here, never on the person. Conflicting stable ids never merge. Neither ``people_rows`` nor the documents are
    changed (the rows ARE referenced by the queue's ``_rows`` until it is built, as before, never mutated)."""
    now = berlin_now(now)
    pipe = _pipeline_index(signals)
    cd_all = loaded_companies(companies_doc)
    stored = cd_all.get("companies", {})
    groups: dict[str, Any] = {}
    created: list[str] = []
    for p in people_rows:
        for cname in dict.fromkeys([p.get("company"), *list(p.get("companies") or [])]):
            if not cname:
                continue
            pe = pipe.get(_fold(cname), {})
            cid = (p.get("company_ids") or {}).get(_fold(cname)) or pe.get("company_id") or ""
            key = company_key(cname, pe.get("website") or "", cid)
            stored.setdefault(key, {})
            # conflict guard: same name already grouped under a different stable id -> keep separate
            g = groups.get(key)
            if g is None:
                g = groups[key] = {
                    "key": key,
                    "name": cname,
                    "domain": _canon_domain(pe.get("website") or ""),
                    "company_id": cid,
                    "founders": [],
                    "pipeline": bool(pe),
                    "_rows": [],
                }
            g["_rows"].append(p)
            if not any(f["id"] == p["id"] for f in g["founders"]):
                ref, made = founder_ref(stored[key], key, p, now=now)
                if made and key not in created:
                    created.append(key)
                g["founders"].append(
                    {
                        "id": p["id"],
                        "name": p.get("name"),
                        "role": p.get("role", ""),
                        "identity_status": p.get("identity_status", ""),
                        "bucket": (p.get("signal") or {}).get("bucket", ""),
                        "name_attributed": p.get("name_attributed", True),
                        "founder_ref_id": ref["founder_ref_id"],
                        "claimed_name": ref["claimed_name"],
                        "claimed_aliases": ref["aliases"],
                        "handle_only": ref["handle_only"],
                    }
                )
    orphans = [
        p
        for p in people_rows
        if not (p.get("company") or p.get("companies"))
        and (p.get("signal") or {}).get("bucket") == BUCKETS[2]
        and p.get("radar_state") != "dismissed"
    ]
    if orphans:
        groups["name:no-company-recorded"] = {
            "key": "name:no-company-recorded",
            "name": "No company recorded",
            "domain": "",
            "company_id": "",
            "pipeline": False,
            "_rows": orphans,
            "founders": [
                {
                    "id": p["id"],
                    "name": p.get("name"),
                    "role": p.get("role", ""),
                    "identity_status": p.get("identity_status", ""),
                    "bucket": (p.get("signal") or {}).get("bucket", ""),
                    "name_attributed": p.get("name_attributed", True),
                }
                for p in orphans
            ],
        }
    leaked = False
    for st in stored.values():  # decision a: the leaked flag is never stored
        if isinstance(st, dict) and "_dirty" in st:
            st.pop("_dirty")
            leaked = True
    refs = Refs(cd_all, created, bool(created) or leaked)
    out = []
    for key, g in groups.items():
        pe = pipe.get(_fold(g["name"]), {})
        st = stored.get(key, {})
        ev = list(st.get("evidence") or [])
        if pe:
            ev.append(
                {
                    "claim": "pipeline entry: " + (pe.get("one_liner") or pe.get("company")),
                    "source": "Project Zero pipeline (claim)",
                    "source_url": pe.get("website") or "",
                    "field": "one_liner",
                }
            )
            if pe.get("funding_status"):
                ev.append(
                    {
                        "claim": "funding status (pipeline): " + str(pe["funding_status"]),
                        "source": "Project Zero pipeline (claim)",
                        "source_url": pe.get("website") or "",
                        "field": "funding_status",
                    }
                )
        vf = verified_facts(st)
        lc = legacy_claims(st)
        claims = {}  # visible, never decision-bearing
        if pe:
            for k, v in (
                ("stage", pe.get("earliness")),
                ("archetype", pe.get("archetype")),
                ("status", pe.get("status")),
                ("funding", pe.get("funding_status")),
            ):
                if v not in (None, ""):
                    claims[k] = "UNVERIFIED PIPELINE CLAIM: " + str(v)
        for k, v in lc.items():
            claims[k] = "UNVERIFIED (legacy unsourced field): " + str(v)
        dmn, dmn_src = resolve_domain(g["name"], pe, st, g["_rows"])
        g["domain"] = dmn
        founded = str(vf["founded"]["value"]) if "founded" in vf else "UNKNOWN"
        status = str(vf["status"]["value"]) if "status" in vf else "UNKNOWN"
        stage = str(vf["stage"]["value"]) if "stage" in vf else "UNKNOWN"
        recent = max(
            [
                f_last
                for f_last in (
                    next((x.get("last_signal") for x in people_rows if x["id"] == f["id"]), "") for f in g["founders"]
                )
                if f_last
            ]
            + [pe.get("discovery_date", "")]
            + [""]
        )
        early = vf["early_stage_signal"]["value"] if "early_stage_signal" in vf else None  # sourced boolean only
        if early is None:
            yr = re.search(r"(19|20)\d{2}", str(founded))
            age = (today.year - int(yr.group(0))) if yr else None
            if "stage" in vf and str(stage).lower().replace(" ", "_") in EARLY_STAGES:
                early = True  # a sourced early stage
            elif age is not None and age <= 3:
                early = True  # sourced founding date within 3 years
            elif age is not None and age >= 4:
                early = False  # sourced established company, no sourced early-stage fact
            else:
                early = None  # pipeline / legacy claims never decide
        resolved = sum(1 for f in g["founders"] if f["identity_status"] in ("resolved", "verified by operator"))
        access = any(
            access_path(x)["kind"] != "none" for x in people_rows if any(x["id"] == f["id"] for f in g["founders"])
        ) or bool([r for r in (st.get("access_routes") or []) if r.get("value")])
        fit = str(vf["project_a_fit"]["value"]) if "project_a_fit" in vf else "NOT ENOUGH INFORMATION"
        funding = str(vf["funding"]["value"]) if "funding" in vf else "UNKNOWN"
        recent_fact = str(vf["recent_activity"]["value"]) if "recent_activity" in vf else ""
        next_action = (
            "resolve official domain (no pipeline website, no confirmed official_domain fact, no founder-linked domain)"
            if not dmn
            else "resolve founder identities (%d of %d unresolved)"  # noqa: UP031
            % (len(g["founders"]) - resolved, len(g["founders"]))
            if resolved < len(g["founders"])
            else "confirm founding date / current status"
            if founded == "UNKNOWN" or status == "UNKNOWN"
            else "no current early-stage signal — monitor, not a lead"
            if early is False
            else "find access path"
            if not access
            else "evaluate as a lead"
        )
        out.append(
            {
                "key": key,
                "name": g["name"],
                "domain": g["domain"] or "UNKNOWN",
                "domain_source": dmn_src,
                "company_id": g["company_id"] or "",
                "founders": g["founders"],
                "description": st.get("description") or pe.get("one_liner") or "UNKNOWN",
                "founded": founded,
                "status": status,
                "stage": stage,
                "funding": funding,
                "recent_signal": recent_fact or recent or "UNKNOWN",
                "verified_facts": vf,
                "claims": claims,
                "project_a_fit": fit,
                "early_stage_fit": "yes"
                if early
                else "no — established / no current early-stage signal"
                if early is False
                else "UNKNOWN",
                "access": "recorded" if access else "none recorded",
                "next_action": next_action,
                "evidence": ev,
                "notes": st.get("notes", ""),
                "in_pipeline": bool(pe),
                "location": pe.get("location", ""),
                "verified_field_count": len(vf),
                "claim_count": len(claims),
                "access_routes": [r for r in (st.get("access_routes") or []) if r.get("value")],
            }
        )
    for c in out:
        rp = research_priority(c, today)
        c["research_priority"] = rp["priority"]
        c["priority_factors"] = rp["factors"]
        c["next_missing"] = rp["next_missing"]
        c["priority_label"] = priority_label(rp["priority"])
        c["priority_why"] = (
            "; ".join(f["factor"] for f in sorted(rp["factors"], key=lambda f: -f["points"])[:2] if f["points"] > 0)
            or "no positive signal yet"
        )
        try:
            research = research_doc if research_doc is not None else {"domains": {}}
            dom = research["domains"].get(c["key"], {})
            c["proposals_pending"] = sum(
                1 for p in (dom.get("proposals") or {}).values() if p.get("status") == "pending"
            )
            c["researched"] = bool(dom.get("done"))
        except Exception:
            c["proposals_pending"] = 0
            c["researched"] = False
    out.sort(key=lambda c: (-c["research_priority"], -len(c["founders"]), c["name"]))
    return copy.deepcopy(out), refs


def priority_label(score: int) -> str:
    return "High" if score >= 8 else "Medium" if score >= 4 else "Low"


def research_priority(c: dict[str, Any], today: date) -> dict[str, Any]:
    """Research-priority ORDERING for the queue (never a quality score, never Gold/Strong). Factors exposed."""
    f = []
    rs = str(c.get("recent_signal") or "")
    d0 = valid_activity_date(rs[:10], today)
    if d0 and (today - d0).days <= 90:
        f.append(("recent dated pipeline/public signal", 3))
    themes = _theme_terms()
    desc = str(c.get("description") or "").lower()
    hits = [t for t in themes if t in desc]
    if hits:
        f.append(
            ("Project A theme overlap in description ({})".format(", ".join(hits[:3])), 2 if len(hits) >= 2 else 1)
        )
    if any("early" in k or "stage" in k for k in (c.get("claims") or {})) or c.get("early_stage_fit") == "yes":
        f.append(("early-stage claim", 2))
    n = len(c.get("founders") or [])
    resolved = sum(
        1 for x in c.get("founders") or [] if x.get("identity_status") in ("resolved", "verified by operator")
    )
    if n:
        f.append(("founder identity completeness %d/%d" % (resolved, n), round(2 * resolved / n)))  # noqa: UP031
    missing = [
        k for k in ("founded", "status", "project_a_fit", "recent_activity") if k not in (c.get("verified_facts") or {})
    ]
    f.append(("missing qualification evidence: %d" % len(missing), 4 - len(missing)))  # noqa: UP031
    if c.get("domain") not in (None, "", "UNKNOWN"):
        f.append(("official domain available", 1))
    if c.get("access") == "recorded":
        f.append(("access path available", 1))
    return {
        "priority": sum(v for _, v in f),
        "factors": [{"factor": k, "points": v} for k, v in f],
        "next_missing": missing,
    }
