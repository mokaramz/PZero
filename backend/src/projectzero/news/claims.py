"""The ``claims.classify`` slice News reads (review 028a): the old ``services/claims.py`` source classification by
domain rules only (``domain_of``, ``registrable``, ``_match``, ``_tokens``, ``classify``), ported line for line over
the domain lists cut into ``news/catalog.py``. Pure. The rest of the Claim Index is not part of News.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from projectzero.dealflow.ranking.names import norm_company
from projectzero.news.catalog import (
    AGGREGATOR,
    GOVERNMENT,
    MEDIA,
    PRESS_WIRE,
    PROGRAM,
    REGISTRY_MIRROR,
    REGISTRY_OFFICIAL,
    SOCIAL,
)


def domain_of(url: str) -> str:
    try:
        host = (urlparse(str(url)).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def registrable(host: str) -> str:
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "gov", "ac") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _match(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", norm_company(name or "")) if len(t) >= 3]


def classify(url: str, company: str = "", website: str = "", investors: list[str] | None = None) -> dict[str, str]:
    """{source_type, publisher_class, domain, independence_group} — by domain rules only."""
    host = domain_of(url)
    if not host:
        return {"source_type": "none", "publisher_class": "unknown", "domain": "", "independence_group": "none"}
    site = domain_of(website) if website else ""
    reg = registrable(host)
    toks = _tokens(company)
    inv = [t for i in (investors or []) for t in _tokens(i) if len(t) >= 4]
    if _match(host, REGISTRY_OFFICIAL):
        st, pc = "registry_official", "state"
    elif _match(host, REGISTRY_MIRROR):
        st, pc = "registry_mirror", "registry"
    elif (site and registrable(site) == reg) or (toks and toks[0] in reg.split(".")[0]):
        st, pc = "company_official", "company"
    elif inv and any(t in reg for t in inv):
        st, pc = "investor", "investor"
    elif _match(host, GOVERNMENT):
        st, pc = "government", "state"
    elif _match(host, PROGRAM) or host.endswith((".edu", ".ac.uk")) or re.match(r"^(www\.)?(tu|uni|fh|hs)-", host):
        st, pc = "program", "program"
    elif _match(host, MEDIA):
        st, pc = "media", "media"
    elif _match(host, PRESS_WIRE):
        st, pc = "press_release", "company"
    elif _match(host, AGGREGATOR):
        st, pc = "aggregator", "aggregator"
    elif _match(host, SOCIAL):
        st, pc = "social", "social"
    else:
        st, pc = "web", "unknown"
    group = f"company:{toks[0] if toks else reg}" if pc == "company" else f"{pc}:{reg}"
    return {"source_type": st, "publisher_class": pc, "domain": host, "independence_group": group}
