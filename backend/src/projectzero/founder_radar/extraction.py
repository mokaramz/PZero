"""The old ``domain/founder_radar/extraction.py`` (rev 6c739b9), ported line for line: ``evidence_kind``,
``group_proposals``, ``recommended_ids``, ``research_summary`` and ``_norm_val`` (review 026a), and
``extract_proposals`` (one fetched page -> proposals) with ``_text``, ``_passage``, ``is_template_text``,
``source_rank``, ``_login_gated``, ``_iso_from_match`` and ``_proposal`` (review 026b). The patterns and tables are the
catalog's (cut by script).

Changes: ``group_proposals`` works on COPIES of the proposals (the old one ``setdefault``-ed ``evidence_kind`` on
the records it was given, which the ``radar_proposals`` answer then showed: the copies carry it too, so the answer is
the same, and the stored research document is never touched). ``extract_proposals`` / ``_proposal`` take the clock
(``now``: the Berlin wall clock of ``retrieved``; ``today``: the day that bounds a dated news item; decision (f))."""

from __future__ import annotations

import copy
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

from projectzero.founder_radar.catalog import (
    _ACTIVE,
    _DATE,
    _EARLY,
    _FOUNDED,
    _FOUNDED_BY,
    _FOUNDER_LINE,
    _FOUNDER_LINE2,
    _FUNDING,
    _GH_ORG,
    _HIRING,
    _LI_PROFILE,
    _MONTHS,
    _NAMES_FOUNDED,
    _OPERATING,
    _TEMPLATE_WORDS,
    DECISION_FIELDS,
    MACHINE_INFERENCE_FIELDS,
    WHY,
    _theme_terms,
)
from projectzero.founder_radar.names import _fold, clean_person_name, hashlib_sha, split_names

__all__ = ["_GH_ORG", "extract_proposals", "group_proposals", "recommended_ids", "research_summary"]


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


# ------------------------------------------------------------------ review 026b: one fetched page -> proposals
def _text(html: Any) -> str:
    t = re.sub(
        r"<script.*?</script>|<style.*?</style>|<nav\b.*?</nav>|<header\b.*?</header>|<footer\b.*?</footer>",
        " ",
        html or "",
        flags=re.S | re.I,
    )
    t = re.sub(r"</(p|div|li|h\d|tr|section|article)>", ". ", t, flags=re.I)  # block boundaries: sentence boundaries
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&nbsp;|&amp;", " & ", t)
    return re.sub(r"\s+", " ", t).strip()


def _passage(text: str, m: re.Match[str], before: int = 90, after: int = 120) -> str:
    """The sentence containing the match (bounded), never a raw window across navigation text."""
    s0 = max(text.rfind(". ", 0, m.start()), text.rfind("? ", 0, m.start()), text.rfind("! ", 0, m.start()))
    s0 = 0 if s0 < 0 else s0 + 2
    e1 = [text.find(x, m.end()) for x in (". ", "? ", "! ")]
    e0 = min([e for e in e1 if e >= 0] + [len(text)])
    e0 = min(e0 + 1, len(text))
    s0 = max(s0, m.start() - before - 60)
    e0 = min(e0, m.end() + after + 60)
    return re.sub(r"\s+", " ", text[s0:e0]).strip(" .") + "."


def is_template_text(passage: Any) -> bool:
    """Navigation / page-template text: short capitalised tokens without sentence punctuation, dominated by menu
    words."""
    w = re.findall(r"[^\W\d_]+", passage or "")
    lw = [x.lower() for x in w]
    if len(w) < 3:
        return True
    menu = sum(1 for x in lw if x in _TEMPLATE_WORDS)
    return (menu / max(1, len(w)) >= 0.4) or (
        not re.search(r"[,.;:]", passage or "") and sum(1 for x in w if x[:1].isupper()) / len(w) > 0.8 and len(w) <= 10
    )


def source_rank(url: str, stype: str = "official domain") -> int:
    """1 official press/news · 2 about/team/founders/people · 3 homepage · 4 careers · 5 other"""
    if stype != "official domain":
        return 6
    path = urlparse(url).path.lower() if url.startswith("http") else url.lower()
    if re.search(r"(news|press|announce|blog|insights)", path):
        return 1
    if re.search(r"(about|team|founder|people|leadership|company)", path):
        return 2
    if path in ("", "/"):
        return 3
    if re.search(r"(career|jobs|hiring)", path):
        return 4
    return 5


def _login_gated(text: Any) -> bool:
    t = (text or "").lower()
    return len(t) < 600 and bool(re.search(r"log ?in|sign ?in|password|create an account", t))


def _iso_from_match(m: re.Match[str]) -> str:
    try:
        if m.group("iso"):
            return date.fromisoformat(m.group("iso")).isoformat()
        mon = next(i for i, n in enumerate(_MONTHS.split("|")) if n == m.group("mon").lower()) + 1
        return date(int(m.group("y")), mon, int(m.group("d") or 1)).isoformat()
    except Exception:
        return ""


def _proposal(
    field: str,
    value: Any,
    passage: str,
    url: str,
    label: str,
    stype: str,
    conf: str,
    reason: str,
    activity_date: str = "",
    person: Any = None,
    *,
    now: datetime,
) -> dict[str, Any]:
    pid = hashlib_sha(field + "|" + str(value) + "|" + url)
    return {
        "id": pid,
        "field": field,
        "value": value,
        "passage": passage[:300],
        "url": url,
        "source_label": label,
        "source_type": stype,
        "activity_date": activity_date,
        "retrieved": now.strftime("%Y-%m-%d %H:%M"),
        "confidence": conf,
        "reason": reason,
        "status": "pending",
        "person": person,
    }


def extract_proposals(
    url: str, html: Any, company: Any, domain: str, stype: str = "official domain", *, now: datetime, today: date
) -> list[dict[str, Any]]:
    """Field-bound proposals from ONE retrieved public page. Passages are quoted exactly. Unknown stays unknown."""
    text = _text(html)
    out: list[dict[str, Any]] = []
    path = url.split(domain, 1)[-1] if domain in url else url
    label = "{} {}".format(company, (path.strip("/") or "homepage"))
    themes = _theme_terms()
    tl = text.lower()
    m = _FOUNDED.search(text)
    if m:
        out.append(
            _proposal(
                "founded", m.group("y"), _passage(text, m), url, label, stype, "medium", "page states a founding year",
                now=now,
            )
        )  # fmt: skip
    for m in _FUNDING.finditer(text):
        val = (m.group("round") or "").lower() + ((" · " + m.group("amt").strip()) if m.group("amt") else "")
        out.append(
            _proposal("funding", val, _passage(text, m), url, label, stype, "medium", "funding announcement wording",
                      now=now)
        )  # fmt: skip
        break
    m = _EARLY.search(text)
    if m:
        out.append(
            _proposal(
                "early_stage_signal",
                "yes",
                _passage(text, m),
                url,
                label,
                stype,
                "medium",
                f"early-stage wording: '{m.group(0)}'",
                now=now,
            )
        )
    m = _ACTIVE.search(text)
    if m:
        out.append(
            _proposal(
                "status", "active", _passage(text, m), url, label, stype, "medium",
                "explicit current-operation wording", now=now,
            )
        )  # fmt: skip
    m = _OPERATING.search(text)
    if m:
        out.append(
            _proposal(
                "operating_signal",
                "customer / deployment wording",
                _passage(text, m),
                url,
                label,
                stype,
                "low",
                "machine inference: customer wording suggests operation but never establishes active status",
                now=now,
            )
        )
    m = _HIRING.search(text)
    if m:
        out.append(
            _proposal(
                "hiring_signal",
                "open roles / hiring",
                _passage(text, m),
                url,
                label,
                stype,
                "low",
                "machine inference: hiring wording supports activity only — never establishes active status",
                now=now,
            )
        )
    dates = sorted(
        {d for d in (_iso_from_match(x) for x in _DATE.finditer(text)) if d and d <= today.isoformat()},
        reverse=True,
    )
    if dates and re.search(r"/(news|press|blog|insights|updates)", path):
        dm = next(x for x in _DATE.finditer(text) if _iso_from_match(x) == dates[0])
        out.append(
            _proposal(
                "recent_activity",
                "dated item on {} page ({})".format(path.strip("/"), dates[0]),
                _passage(text, dm),
                url,
                label,
                stype,
                "medium",
                "latest dated news/press/blog item",
                activity_date=dates[0],
                now=now,
            )
        )
    hits = sorted({t for t in themes if t in tl})[:6]
    if hits:
        fit = "HIGH" if len(hits) >= 3 else "MEDIUM"
        mm = re.search(re.escape(hits[0]), text, re.I)
        out.append(
            _proposal(
                "project_a_fit",
                fit,
                _passage(text, mm) if mm else text[:200],
                url,
                label,
                stype,
                "low" if fit == "MEDIUM" else "medium",
                "company description overlaps Project A themes: " + ", ".join(hits),
                now=now,
            )
        )
    if stype == "official domain":
        team = bool(re.search(r"/[^/]*(team|about|company|founders|people|leadership)", path.lower()))
        for m in list(_FOUNDER_LINE.finditer(text)) + list(_FOUNDER_LINE2.finditer(text)):
            nm = clean_person_name(m.group("name"), company)  # navigation/action prefixes, company words, roles out
            if nm:
                out.append(
                    _proposal(
                        "founder",
                        nm,
                        _passage(text, m, 40, 80),
                        url,
                        label,
                        stype,
                        "medium" if team else "low",
                        (
                            "official team/about page names this person with a founder role"
                            if team
                            else "official-domain page (%s) names this person with a founder role"
                            % (path.strip("/") or "homepage")
                        ),
                        person={"name": nm, "role": m.group("role"), "company": company},
                        now=now,
                    )
                )
    if stype == "official domain":
        seen_names = {p["person"]["name"] for p in out if p.get("person")}
        for m in _FOUNDED_BY.finditer(text):
            for nm in split_names(m.group("names")):
                if nm not in seen_names:
                    seen_names.add(nm)
                    out.append(
                        _proposal(
                            "founder",
                            nm,
                            _passage(text, m, 40, 120),
                            url,
                            label,
                            stype,
                            "medium" if re.search(r"/(news|press|blog|about|team|insights)", path.lower()) else "low",
                            "official page states the company was founded by this person",
                            person={"name": nm, "role": "founder", "company": company},
                            now=now,
                        )
                    )
        for m in _NAMES_FOUNDED.finditer(text):
            if _fold(company).split(" ")[0] in _fold(m.group("co")):
                for nm in split_names(m.group("names")):
                    if nm not in seen_names:
                        seen_names.add(nm)
                        out.append(
                            _proposal(
                                "founder",
                                nm,
                                _passage(text, m, 40, 120),
                                url,
                                label,
                                stype,
                                "medium",
                                "official page states this person founded the company",
                                person={"name": nm, "role": "founder", "company": company},
                                now=now,
                            )
                        )
        for m in _LI_PROFILE.finditer(html or ""):
            out.append(
                _proposal(
                    "linkedin_profile",
                    "https://www.linkedin.com/in/" + m.group(1).rstrip("/"),
                    "public LinkedIn profile link found on the official site (never fetched)",
                    url,
                    label,
                    stype,
                    "medium",
                    "canonical profile discovered on a permitted public source — LinkedIn itself is never scraped",
                    now=now,
                )
            )
    mail = re.search(r"[\w.+-]+@" + re.escape(domain), text)
    if mail:
        out.append(
            _proposal(
                "access_route",
                mail.group(0),
                _passage(text, mail, 30, 30),
                url,
                label,
                stype,
                "medium",
                "public contact address on the official domain",
                now=now,
            )
        )
    gh = _GH_ORG.search(html or "")
    if gh:
        out.append(
            _proposal(
                "access_route",
                "https://github.com/" + gh.group(1),
                "official page links to GitHub organisation " + gh.group(1),
                url,
                label,
                stype,
                "medium",
                "public GitHub link on the official domain",
                now=now,
            )
        )
    seen, uniq = set(), []
    for p in out:
        if p["id"] in seen:
            continue
        p["source_rank"] = source_rank(url, stype)
        p["template_text"] = is_template_text(p["passage"])
        p["why"] = WHY.get(p["field"], "")
        p["evidence_kind"] = evidence_kind(p["field"])
        seen.add(p["id"])
        uniq.append(p)
    return uniq
