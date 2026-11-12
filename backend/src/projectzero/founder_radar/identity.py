"""The old ``domain/founder_radar/identity.py`` (rev 6c739b9), ported line for line (review 026a): identity resolution,
the merge rules, the explicit founded-by / role-binding checks and the promotion guard. Only change:
``official_page_hardened`` reads the research document it is GIVEN (the old one loaded ``radar_research.json``)."""

from __future__ import annotations

import re
from typing import Any

from projectzero.founder_radar.catalog import _FOUNDED_BY_ROUTES, _FOUNDED_STOP
from projectzero.founder_radar.names import _canon_domain, _fold, canonical_linkedin, is_person_name


def identity_resolution(p: dict[str, Any]) -> tuple[str, list[str]]:
    """Resolved only with a verified external identity AND a corroborating fact (employer/institution or location).
    Similar names never resolve anything on their own."""
    ev = []
    if p.get("github_id"):
        ev.append("GitHub identity #" + str(p["github_id"]))
    if p.get("openalex_id"):
        ev.append("OpenAlex author " + str(p["openalex_id"]))
    if p.get("orcid"):
        ev.append("ORCID " + str(p["orcid"]))
    if p.get("patent_inventor_id"):
        ev.append("patent inventor id")
    corroborate = [k for k in ("company", "location") if p.get(k)] + (["institutions"] if p.get("institutions") else [])
    if p.get("provenance") == "user_provided" or p.get("identity_verified_by") == "operator":
        return "verified by operator", ev + (
            ["typed by Mohamed"] if p.get("provenance") == "user_provided" else ["identity verified by operator action"]
        )
    if p.get("name_attributed") is False or not is_person_name(p.get("name")):
        return "needs identity resolution", [
            *ev,
            "no attributed human name (login / handle only) — not an outreach identity",
        ]
    if ev and corroborate:
        return "resolved", [*ev, "corroborated by " + ", ".join(corroborate)]
    return "needs identity resolution", ev


def can_merge(a: dict[str, Any], b: dict[str, Any]) -> tuple[bool, str]:
    """Merge only with sufficient identity evidence: same folded name AND (shared verified id OR same
    employer/institution OR same location + shared profile domain/project)."""
    # 1) verified external identities decide first — before any name comparison
    ids = (("github_id", "same GitHub id"), ("openalex_id", "same OpenAlex id"), ("orcid", "same ORCID"))
    for key, _why in ids:
        va, vb = str(a.get(key) or "").strip(), str(b.get(key) or "").strip()
        if va and vb and va != vb:
            return False, f"conflicting {key} ({va} vs {vb}) — never merged automatically"
    # review 026a (Codex H-213): two DIFFERENT patent inventor ids are two people as surely as two ORCIDs. The old code
    # never compared them and the merged record kept only one, losing the other's identifier; refuse instead. A
    # matching patent id is still no reason to merge on its own (the old positive rules are unchanged).
    pa, pb = str(a.get("patent_inventor_id") or "").strip(), str(b.get("patent_inventor_id") or "").strip()
    if pa and pb and pa != pb:
        return False, f"conflicting patent_inventor_id ({pa} vs {pb}) — never merged automatically"
    la, lb = canonical_linkedin(a.get("linkedin")), canonical_linkedin(b.get("linkedin"))
    if la and lb and la != lb:
        return False, "conflicting LinkedIn URLs — never merged automatically"
    for key, why in ids:
        va, vb = str(a.get(key) or "").strip(), str(b.get(key) or "").strip()
        if va and va == vb:
            return True, why
    if la and la == lb:
        return True, "same canonical LinkedIn URL"
    # 2) without a shared external id, a name match alone is never enough
    if _fold(a.get("name")) != _fold(b.get("name")):
        return False, "different names"
    inst_a = {_fold(x) for x in ([a.get("company"), *list(a.get("institutions") or [])]) if x}
    inst_b = {_fold(x) for x in ([b.get("company"), *list(b.get("institutions") or [])]) if x}
    if inst_a & inst_b:
        return True, "same employer/institution: " + ", ".join(sorted(inst_a & inst_b))
    loc = _fold(a.get("location")) and _fold(a.get("location")).split(",")[0] == _fold(b.get("location")).split(",")[0]
    dom_a = {re.sub(r"^https?://(www\.)?", "", u).split("/")[0] for u in (a.get("profile_urls") or []) if u}
    dom_b = {re.sub(r"^https?://(www\.)?", "", u).split("/")[0] for u in (b.get("profile_urls") or []) if u}
    if loc and (dom_a & dom_b):
        return True, "same location + shared profile domain"
    return False, "same name only — not enough identity evidence"


def _founded_names(chunk: Any) -> list[str]:
    """The explicit list of people in a founded-by clause — cut at the first preposition / clause boundary."""
    chunk = _FOUNDED_STOP.split(str(chunk or ""), 1)[0]
    return [x.strip(" ,") for x in re.split(r"\s*(?:,|\band\b|&|\bund\b|\bet\b)\s*", chunk) if x.strip(" ,")]


def founded_by_connection(fact: Any, human_name: Any, company: Any) -> bool:
    """True ONLY when the exact passage explicitly says this human founded / co-founded this company."""
    f = re.sub(r"\s+", " ", str(fact or "")).strip()
    n = _fold(human_name)
    c = _fold(company)
    if not (n and is_person_name(human_name) and n in _fold(f)):
        return False
    for i, pat in enumerate(_FOUNDED_BY_ROUTES):
        for m in re.finditer(pat, f, flags=re.I):
            if i < 2:
                co = _fold(m.group("co")).strip()
                if not c or not (co == c or co.startswith(c + " ") or co.endswith(" " + c)):
                    continue
            names = _founded_names(m.group("names"))
            if not names or not all(is_person_name(x) for x in names):
                continue
            if n in {_fold(x) for x in names}:
                return True
    return False


def role_bound_to_name(fact: Any, human_name: Any) -> bool:
    """The founder role must be tied to THIS name in the exact passage."""
    f = _fold(re.sub(r"\s+", " ", str(fact or "")))
    n = _fold(human_name)
    if not n or n not in f:
        return False
    role = r"(?:co-?founder|founder|founding(?:\s+(?:engineer|team|member|partner))?)"
    after = re.compile(re.escape(n) + r"[,\s\-–—(]{1,4}(?:(?:the|a|an|is|was|as|and|&|,|–|-)\s*){0,3}" + role + r"\b")  # noqa: RUF001
    before = re.compile(
        role
        + r"\b(?:\s*(?:&|and|,|/)?\s*(?:ceo|cto|coo|cfo|chief\s+\w+\s+officer|of\s+[\w\s.&'’-]{1,40}?))?[:,\s\-–—]{1,4}"  # noqa: RUF001
        + re.escape(n)
    )
    return bool(after.search(f) or before.search(f))


def official_page_hardened(url: Any, official_domain: Any, research: Any) -> bool:
    """The page must have been retrieved through the hardened public fetch: recorded in the company's research record
    with status 200 and a final URL on the same official domain. Unrecorded or blocked pages never qualify."""
    if not url or not official_domain or _canon_domain(url) != _canon_domain(official_domain):
        return False
    for dom in (research.get("domains") or {}).values():
        if _canon_domain(dom.get("domain") or "") != _canon_domain(official_domain):
            continue
        rec = (dom.get("pages") or {}).get(url) or next(
            (v for k, v in (dom.get("pages") or {}).items() if k.rstrip("/") == url.rstrip("/")), None
        )
        if (
            rec
            and str(rec.get("status")) == "200"
            and _canon_domain(rec.get("final_url") or url) == _canon_domain(official_domain)
        ):
            return True
    return False


def proposed_identity(p: dict[str, Any]) -> dict[str, Any] | None:
    """A candidate resolution the operator can confirm: only when evidence text already links a human name to the
    handle."""
    if p.get("name_attributed") is not False:
        return None
    for x in p.get("evidence") or []:
        m = re.search(r"([A-Z][\w'\-]+(?: [A-Z][\w'\-]+)+)", str(x.get("claim") or ""))
        if (
            m
            and is_person_name(m.group(1))
            and any(a.lower() in str(x.get("claim") or "").lower() for a in (p.get("aliases") or []))
        ):
            return {"name": m.group(1), "source": x.get("source"), "url": x.get("source_url")}
    return None


def promotion_guard(p: dict[str, Any]) -> str | None:
    """Network, opportunity and Boardy actions are blocked until the identity is resolved."""
    if p.get("identity_status") in ("resolved", "verified by operator"):
        return None
    return "Resolve identity before promotion"
