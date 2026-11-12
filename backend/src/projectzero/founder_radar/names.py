# ruff: noqa: RUF001
"""The old ``domain/founder_radar/names.py`` (rev 6c739b9), ported line for line (review 026a): the person-name
guard, organisation / navigation-heading detection and the name helpers. The patterns and word sets are
``catalog``'s (cut by script). Pure, no clock."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

from projectzero.founder_radar.catalog import (
    _HEADING_FIRST,
    _HEADING_WORDS,
    _NAME_NOISE,
    _ORG_WORDS,
    _PLACEHOLDER,
    _ROLE_ONLY,
)


def is_organization_name(name: Any) -> bool:
    return bool(_ORG_WORDS.search(str(name or "")))


def is_navigation_heading(name: Any) -> bool:
    """Page-template / navigation text a scanner can mistake for a person; Unicode human names are untouched."""
    toks = [t.strip(",.:;|–—()").lower() for t in re.split(r"\s+", str(name or "").strip()) if t.strip(",.:;|–—()")]
    if not toks:
        return False
    if toks[0] in _HEADING_FIRST:
        return True
    heads = [t in _HEADING_WORDS for t in toks]
    if all(heads):
        return True
    return heads[0] and sum(heads) >= 2


def is_person_name(name: Any) -> bool:
    """True only for a plausible individual's name: letters (any script), 2+ tokens, no digits/brackets, no
    placeholders, role labels or navigation headings."""
    n = re.sub(r"\s+", " ", str(name or "")).strip()
    if not n or len(n) < 4 or len(n) > 80:
        return False
    if (
        re.search(r"[\d()\[\]{}<>@/|;:]", n)
        or _PLACEHOLDER.search(n)
        or _ROLE_ONLY.match(n)
        or is_organization_name(n)
        or is_navigation_heading(n)
    ):
        return False
    toks = [t for t in re.split(r"[ \-]", n) if t]
    return len(toks) >= 2 and all(re.match(r"^[^\W\d_][\w'’.\-]*$", t) for t in toks)


def canonical_linkedin(url: Any) -> str:
    u = str(url or "").strip()
    if not u:
        return ""
    u = re.sub(r"^https?://", "", u, flags=re.I)
    u = re.sub(r"^www\.", "", u, flags=re.I).split("?")[0].split("#")[0].rstrip("/")
    return ("https://www." + u).lower() if u.startswith("linkedin.com") else ("https://" + u).lower()


def _fold(s: Any) -> str:
    return re.sub(
        r"[^a-z0-9 ]", "", unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    ).strip()


def _canon_domain(url: Any) -> str:
    u = re.sub(r"^https?://", "", str(url or "").strip(), flags=re.I)
    u = re.sub(r"^www\.", "", u, flags=re.I)
    return u.split("/")[0].lower()


def clean_person_name(raw: Any, company: Any = "") -> str:
    """Strip navigation/action prefixes, company words and role fragments; return a plausible human name or ''."""
    toks = [t for t in re.split(r"\s+", str(raw or "").strip()) if t]
    cw = {w.lower() for w in re.split(r"\W+", company or "") if w}
    toks = [
        t
        for t in toks
        if not t.endswith("-") and t.lower().strip(",.:;|–—") not in _NAME_NOISE and t.lower().strip(",.:;") not in cw
    ]
    toks = [t.strip(",.:;|–—()") for t in toks if t.strip(",.:;|–—()")]
    while toks and not toks[0][:1].isupper():
        toks.pop(0)
    while toks and not toks[-1][:1].isupper():
        toks.pop()
    for i in range(len(toks)):
        cand = " ".join(toks[i : i + 4] if len(toks[i:]) > 4 else toks[i:])
        if 2 <= len(cand.split()) <= 4 and is_person_name(cand) and all(t[:1].isupper() for t in cand.split()):
            return cand
    return ""


def split_names(blob: Any) -> list[str]:
    """'A and B' / 'A, B and C' -> each plausible Unicode human name separately."""
    parts = re.split(r"\s*(?:,|;|\band\b|\bund\b|&)\s*", str(blob or ""))
    out: list[str] = []
    for part in parts:
        part = re.split(r"\s+(?=[a-z])", part.strip())[0]  # cut trailing lowercase clauses
        nm = clean_person_name(part)
        if nm and nm not in out:
            out.append(nm)
    return out


def hashlib_sha(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", "ignore")).hexdigest()[:12]
