# ruff: noqa: RUF001, RUF003  (the protected regexes and word lists keep their typographic dashes and quotes)
"""Deterministic entity extraction for candidates whose stored name is not a company (protected; old
``domain/entity_repair.py``, verbatim).

Native watchers sometimes store a timestamp ("01.10.2026 17:08"), "UNKNOWN", an event string or a headline as the
candidate name while the real company is named in the text. This module recovers it — no LLM — by reusing the old
headline extractor (``extract_company``, ported here from ``connectors.extract_company`` with its ``_valid_company``
check) sentence by sentence, plus a few descriptor patterns ("defence technology company DOD Solution", "AI Research
Lab Grubel", "RheoCarti awarded …").

Every extracted name must occur verbatim in the candidate's own text and pass ``valid_company``. Nothing here rewrites a
stored record: callers show ``display_name`` alongside the original name. Regexes and word lists are verbatim; long
patterns are only split across string literals.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from projectzero.dealflow.ranking.names import norm_company

# ------------------------------------------------------------------ the old headline extractor (connectors.py)
_HEADLINE_LABELS = re.compile(
    r"^\s*(exclusive|breaking|interview|podcast|analysis|opinion|update|watch|meet|report)\s*[:\u2014\-–]\s*", re.I
)
_CITY_BASED = re.compile(r"^\s*[A-ZÀ-Ž][\w.\-]*(?:\s[A-ZÀ-Ž][\w.\-]*)?[\-\u2011]based\s+", re.I)
_COUNTRY_POSS = re.compile(r"^\s*[A-ZÀ-Ž][\w]*(?:\s[A-Z][\w]*)?[\u2019']s\s+")
_FUNDING_VERBS = (
    r"(?:raises?|raised|secures?|secured|closes?|closed|lands?|bags?|nabs?|gets?|receives?|announces?|launches?|"
    r"sammelt|erh[äa]lt|sichert(?:\s+sich)?|schlie[ßs]s?t)"
)
_NAME_TOKEN = r"[A-ZÀ-Ž0-9][\w&.\u2019'\-]*"
_NAME_RUN = _NAME_TOKEN + r"(?:\s+" + _NAME_TOKEN + r"){0,3}"
_NAME_STOP = {
    "exclusive", "breaking", "interview", "podcast", "analysis", "opinion", "startupnews", "startbase", "week",
    "weekly", "roundup", "review", "the", "this", "how", "why", "what", "meet", "inside", "from", "sweden", "germany",
    "deutschland", "switzerland", "schweiz", "france", "austria", "denmark", "norway", "finland", "netherlands",
    "belgium", "spain", "italy", "poland", "estonia", "europe", "eu", "munich", "münchen", "berlin", "hamburg",
    "zurich", "zürich", "geneva", "genf", "vienna", "wien", "stockholm", "copenhagen", "helsinki", "oslo", "amsterdam",
    "paris", "london", "madrid", "milan", "startup", "startups", "start-up", "start-ups", "report", "state", "top",
    "these", "here", "agtech", "fintech", "biotech", "medtech", "deeptech", "insurtech", "proptech", "healthtech",
    "cleantech", "climatetech", "regtech", "spacetech", "foodtech", "edtech", "saas", "company", "firm", "dutch",
    "german", "french", "swiss", "austrian", "british", "irish", "swedish", "danish", "norwegian", "finnish", "belgian",
    "spanish", "italian", "portuguese", "polish", "czech", "estonian", "european", "american", "canadian",
}  # fmt: skip
# "Dutch AgTech Gravity Gardens secures..." -> nationality is stripped ONLY together with a sector word (protects real
# names like "German Bionic"); a lone leading sector word is also stripped.
_NATS = (
    r"(?:dutch|german|french|swiss|austrian|british|uk|irish|swedish|danish|norwegian|finnish|belgian|spanish|italian|"
    r"portuguese|polish|czech|estonian|latvian|lithuanian|european|us|american|canadian)"
)
_SECT = (
    r"(?:agtech|fintech|biotech|medtech|deeptech|insurtech|proptech|healthtech|cleantech|climatetech|regtech|spacetech|"
    r"foodtech|edtech|adtech|legaltech|robotics|ai|saas|software|startup|scale-?up|company|firm)"
)


def valid_company(name: str | None) -> bool:
    """Old ``connectors._valid_company``."""
    if not name:
        return False
    toks = name.strip().split()
    if not toks or len(toks) > 4:
        return False
    low = name.strip().lower()
    if low in _NAME_STOP or (toks[0].lower() in _NAME_STOP and len(toks) == 1):
        return False
    if all(t.lower() in _NAME_STOP for t in toks):
        return False
    return not (len(name.strip()) < 2 or (name.isupper() and len(name) > 12))


def extract_company(title: str | None) -> str:
    """Actual company name from a news headline — UNKNOWN when the evidence is not there.
    Never invents: label words, cities, countries and site names are rejected. (Old ``connectors.extract_company``.)"""
    t = re.sub(r"\s+[|\u2013\u2014-]\s+[\w .]{3,30}$", "", (title or "").strip())  # strip trailing site suffix
    for _ in range(2):
        t = _HEADLINE_LABELS.sub("", t).strip()
    core = _CITY_BASED.sub("", t)
    core = _COUNTRY_POSS.sub("", core)
    core = re.sub(
        r"^(?:das\s+|the\s+)?(?:startup|start-?up|jungunternehmen|spin-?off|scale-?up)\s+", "", core, flags=re.I
    )
    core = re.sub(r"^" + _NATS + r"\s+" + _SECT + r"\s+(?=[A-ZÀ-Ž0-9])", "", core, flags=re.I)
    core = re.sub(r"^" + _SECT + r"\s+(?=[A-ZÀ-Ž][\w&.\u2019'\-]*\s)", "", core, flags=re.I)
    m = re.match(r"^(" + _NAME_RUN + r")\s+" + _FUNDING_VERBS + r"\b", core)
    if m and valid_company(m.group(1)):
        return m.group(1).strip()
    m = re.search(
        r"\b(?:startup|start-up|jungunternehmen|spin-?off)\s+(" + _NAME_TOKEN + r"(?:\s+" + _NAME_TOKEN + r"){0,2})", t
    )
    if m and valid_company(m.group(1)):
        return m.group(1).strip()
    m = re.match(r"^(" + _NAME_RUN + r")\s*:", core)
    if m and valid_company(m.group(1)):
        return m.group(1).strip()
    m = re.match(r"^(" + _NAME_RUN + r")\b", core)
    if m and valid_company(m.group(1)) and re.search(_FUNDING_VERBS, core, re.I):
        return m.group(1).strip()
    return "UNKNOWN"


# ------------------------------------------------------------------ entity repair (entity_repair.py)
_DATEISH = re.compile(
    r"^\s*((mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s*)?"
    r"(\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{1,2}\s+[a-zäéû]+\s+\d{4}|[a-z]+\s+\d{1,2},?\s+\d{4})"
    r"([,;\s]+\d{1,2}[:.]\d{2})?\s*[·•\-–]*\s*$",
    re.I,
)
_EVENTISH = re.compile(
    r"\b(summit|conference|career fair|masterclass|workshop|meetup|webinar|hackathon|demo day|info session|"
    r"ask the expert|industry day|open day|festival|award ceremony)\b",
    re.I,
)
_DESCRIPTOR = (
    r"(?i:startup|start-up|scale-?up|company|firm|unternehmen|spin-?off|spinout|lab|labs|studio|"
    r"insurtech|fintech|legaltech|defen[cs]etech|deeptech|climatetech|agritech|"
    r"medtech|biotech|healthtech|proptech|spacetech|foodtech|contech)"
)
_TOKEN = r"[A-ZÀ-Ž][\w&.’'\-]*(?:\.ai|\.io)?"
_NAME = _TOKEN + r"(?:\s+" + _TOKEN + r"){0,2}"
_AFTER_DESCRIPTOR = re.compile(
    r"\b" + _DESCRIPTOR + r"\s+(" + _NAME + r")"
    r"(?=\s+(?:has|hat|aus|from|in|is|ist|will|wird|raises|raised|secures|erh[äa]lt|sammelt|sichert|lands|closes)\b"
    r"|\s*[,.;:(—–]|\s*$)"
)
_BEFORE_VERB = re.compile(
    r"(?:^|[.;:—–]\s+)(" + _NAME + r")\s+(?:awarded|wins|won|obtains|holt sich|gewinnt|to enter|to expand|to launch|"
    r"enters|expands|launches|joins|named|selected)\b"
)
_DEMONYMS = {
    "swiss", "german", "french", "finnish", "estonian", "dutch", "british", "danish", "swedish", "norwegian",
    "austrian", "lithuanian", "latvian", "polish", "italian", "spanish", "portuguese", "irish", "belgian", "european",
    "ukrainian", "czech", "hungarian", "romanian", "greek", "american", "us", "canadian", "israeli", "nordic", "baltic",
}  # fmt: skip
_LEADING_NOISE = {"thriving", "the", "new", "das", "die", "der", "le", "la", "les", "funding", "exclusive", *_DEMONYMS}
_GENERIC = {
    "startup", "startups", "series", "seed", "pre-seed", "funding", "million", "millionen", "euro", "eur", "chf", "usd",
    "the", "and", "for", "with", "ai", "europe", "european", "university", "category", "project", "leader", "leaders",
    "award", "prize", "grand", "five", "twenty", "first", "second", "new", "find", "high", "read", "learn", "watch",
    "show", "more", "meet", "join", "apply", "register", "connect", "discover", "explore", "nih sbir", "sbir", "sttr",
    "nsf sbir", "nih", "nsf", "ukri", "innovate uk", "eic", "zero", "das", "die", "der", "den", "le", "la",
}  # fmt: skip
_NOT_A_COMPANY = re.compile(
    r"(-based|-founded|\bfair$|\bday$|\bsummit$|\baccelerator$|\baward$|\bprize$|\bprogram(me)?$|\bfund$|\bweek$)", re.I
)
_LEGAL_SUFFIX = re.compile(r"\b(inc|llc|ltd|limited|gmbh|ag|sa|sas|bv|oy|ab|plc|corp|corporation|pc|lp|llp)\b\.?", re.I)


def broken_name_reason(c: Mapping[str, Any]) -> str:
    """Why the stored name is not a usable company name ('' when it looks fine)."""
    name = str(c.get("name") or "").strip()
    if not name or name.upper() == "UNKNOWN":
        return "name UNKNOWN"
    if _DATEISH.match(name):
        return "name is a date / time"
    if _EVENTISH.search(name):
        return "name is an event"
    words = name.split()
    if all(w.lower().strip(",") in _DEMONYMS or re.fullmatch(r"[A-Z][a-z]+-[A-Z][a-z]+", w) for w in words) and all(
        any(part.lower() in _DEMONYMS for part in w.split("-")) for w in words
    ):
        return "name is a nationality / descriptor"
    if _LEGAL_SUFFIX.search(name):
        return ""  # a registered legal name is a company name even when long
    if len(words) >= 6 or re.search(
        r"\b(raises|secures|erhält|holt sich|awarded|acquires|launches|shaping)\b", name, re.I
    ):
        return "name is a headline"
    return ""


def _clean(name: str) -> str:
    toks = name.strip(" ,.;:").split()
    while len(toks) > 1 and (toks[0].lower().strip("’'") in _LEADING_NOISE or toks[0].lower().endswith("tech")):
        toks = toks[1:]
    out = " ".join(toks)
    return re.sub(r"[’']s$", "", out)  # "DeepPsy’s obtains" → DeepPsy


def _ok(name: str, text: str) -> bool:
    if not name or len(name) < 2 or len(name) > 40:
        return False
    low = name.lower()
    if low in _GENERIC or all(t.lower() in _GENERIC for t in name.split()):
        return False
    if _NOT_A_COMPANY.search(name) or _EVENTISH.search(name):
        return False
    if all(t.lower() in _DEMONYMS for t in re.split(r"[\s-]+", name)):
        return False
    if re.fullmatch(r"[\d\s.,:/-]+", name):
        return False
    return name in text and valid_company(name)


def extract_entities(c: Mapping[str, Any], limit: int = 5) -> list[dict[str, str]]:
    """Company names clearly stated in the candidate's text, each with the sentence that names it (provenance)."""
    name = str(c.get("name") or "")
    desc = str(c.get("description") or "")
    text = f"{name}. {desc}" if desc and desc != name else name
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\s+[—–]\s+", text) if s.strip()]
    found: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(n: str, sentence: str, how: str) -> None:
        n = _clean(n)
        key = norm_company(n)
        if key and key not in seen and _ok(n, text):
            seen.add(key)
            found.append({"name": n, "evidence": sentence[:240], "method": how})

    for s in sentences:
        got = extract_company(s)
        if got and got != "UNKNOWN":
            add(got, s, "headline extractor")
        for m in _AFTER_DESCRIPTOR.finditer(s):
            add(m.group(1), s, "descriptor phrase")
        for m in _BEFORE_VERB.finditer(s):
            add(m.group(1), s, "subject of event verb")
        if len(found) >= limit:
            break
    return found[:limit]


def repair(c: Mapping[str, Any]) -> dict[str, Any]:
    """{'broken': reason, 'display_name': best name, 'entities': [...], 'original_name': stored name} — read-only."""
    reason = broken_name_reason(c)
    original = str(c.get("name") or "")
    if not reason:
        return {"broken": "", "display_name": original, "entities": [], "original_name": original}
    ents = extract_entities(c)
    return {
        "broken": reason,
        "display_name": ents[0]["name"] if ents else original,
        "entities": ents,
        "original_name": original,
    }


def repair_name(name: str, desc: str) -> tuple[str, str]:
    """For NEW scan items: (company name, raw title). Keeps the raw title as provenance; never invents a name."""
    probe = {"name": name, "description": desc}
    r = repair(probe)
    if r["broken"] and r["entities"]:
        return r["entities"][0]["name"], name
    return name, ""
