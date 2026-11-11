"""Workspace routing for geo tags (protected; old ``domain/workspaces.py``, Scout Loop Hardening RC1.2).

ONE data-driven answer to "which workspace does this geo tag / source / candidate belong to?" The tables and rules
are verbatim. The only change: the operator override (old ``workspace_geos.json``) is passed in, never read from disk.

Rules (in order):
  1. legacy region tags keep their meaning (DACH, CH, NORD, BNL, FR, UK, SEU, EU and the server-side spellings) ->
     Europe; US, CA, NA -> North America;
  2. any ISO 3166-1 alpha-2 code of a European country -> Europe; US / CA -> North America;
  3. a country NAME routes the same way; geo_scope "region-eu" -> Europe;
  4. anything else -> unresolved. Nothing defaults to Europe.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# ISO 3166-1 alpha-2 — Europe (geographic Europe incl. the Caucasus-adjacent states commonly counted as European by EU
# statistics)
EUROPE_CC = {
    "AD": "Andorra",
    "AL": "Albania",
    "AT": "Austria",
    "BA": "Bosnia and Herzegovina",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "BY": "Belarus",
    "CH": "Switzerland",
    "CY": "Cyprus",
    "CZ": "Czechia",
    "DE": "Germany",
    "DK": "Denmark",
    "EE": "Estonia",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GB": "United Kingdom",
    "GI": "Gibraltar",
    "GR": "Greece",
    "HR": "Croatia",
    "HU": "Hungary",
    "IE": "Ireland",
    "IS": "Iceland",
    "IT": "Italy",
    "LI": "Liechtenstein",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "MC": "Monaco",
    "MD": "Moldova",
    "ME": "Montenegro",
    "MK": "North Macedonia",
    "MT": "Malta",
    "NL": "Netherlands",
    "NO": "Norway",
    "PL": "Poland",
    "PT": "Portugal",
    "RO": "Romania",
    "RS": "Serbia",
    "SE": "Sweden",
    "SI": "Slovenia",
    "SK": "Slovakia",
    "SM": "San Marino",
    "UA": "Ukraine",
    "VA": "Vatican City",
    "XK": "Kosovo",
    "FO": "Faroe Islands",
    "GL": "Greenland",
    "IM": "Isle of Man",
    "JE": "Jersey",
    "GG": "Guernsey",
    "AX": "Åland Islands",
    "SJ": "Svalbard",
}
NORTH_AMERICA_CC = {"US": "USA", "CA": "Canada"}
# legacy / regional tags (kept verbatim — the registry, the report and the UI all use them)
EUROPE_TAGS = {
    "EU": "EU-wide",
    "DACH": "DACH",
    "CH": "Switzerland",
    "NORD": "Nordics",
    "BNL": "Benelux",
    "FR": "France",
    "UK": "UK/Ireland",
    "SEU": "South/CEE",
    "NORDICS": "Nordics",
    "BENELUX": "Benelux",
    "BALTICS": "Baltics",
    "CEE": "CEE",
    "EUROPE": "Europe",
}
NORTH_AMERICA_TAGS = {"US": "USA", "CA": "Canada", "NA": "North America"}
# country names → workspace (for sources / candidates that carry a country instead of a tag)
_EU_NAMES = {n.lower() for n in EUROPE_CC.values()} | {
    "deutschland",
    "schweiz",
    "österreich",
    "oesterreich",
    "uk",
    "england",
    "scotland",
    "wales",
    "great britain",
    "the netherlands",
    "holland",
    "czech republic",
    "eesti",
    "polska",
    "europe",
    "eu",
    "suomi",
    "sverige",
    "danmark",
    "norge",
    "españa",
    "italia",
    "belgique",
    "belgië",
    "nederland",
    "lietuva",
    "latvija",
}
_NA_NAMES = {"usa", "united states", "united states of america", "america", "canada"}


Override = Mapping[str, set[str]]
NO_OVERRIDE: Override = {"eu": set(), "na": set()}


def parse_override(doc: Any) -> Override:
    """The old ``workspace_geos.json``: {"eu": [...], "na": [...]}; anything unreadable means "no override"."""
    try:
        return {k: {str(t).strip().upper() for t in (doc.get(k) or []) if str(t).strip()} for k in ("eu", "na")}
    except Exception:
        return {"eu": set(), "na": set()}


def workspace_of_tag(tag: Any, override: Override = NO_OVERRIDE) -> str | None:
    """'eu' · 'na' · None (unresolved) for one geo tag / country code / country name."""
    k = str(tag or "").strip()
    if not k:
        return None
    u = k.upper()
    if u in override["na"] or u in NORTH_AMERICA_TAGS or u in NORTH_AMERICA_CC:
        return "na"
    if u in override["eu"] or u in EUROPE_TAGS or u in EUROPE_CC:
        return "eu"
    lo = k.lower()
    if lo in _NA_NAMES:
        return "na"
    if lo in _EU_NAMES:
        return "eu"
    return None


def workspace_of(obj: Mapping[str, Any], override: Override = NO_OVERRIDE) -> str:
    """'eu' · 'na' · 'un' for a configured source or a candidate: geo tags first, then country, then geo_scope."""
    tags = obj.get("geo") or []
    if isinstance(tags, str):
        tags = [tags]
    ws = {workspace_of_tag(t, override) for t in tags} - {None}
    if "na" in ws:
        return "na"
    if "eu" in ws:
        return "eu"
    c = workspace_of_tag(obj.get("country"), override)
    if c:
        return c
    if obj.get("geo_scope") == "region-eu":
        return "eu"
    return "un"


def label(tag: Any) -> str:
    u = str(tag or "").strip().upper()
    return EUROPE_TAGS.get(u) or NORTH_AMERICA_TAGS.get(u) or EUROPE_CC.get(u) or NORTH_AMERICA_CC.get(u) or str(tag)


def ws_geos(
    sources: Iterable[Mapping[str, Any]], base: Iterable[str] = (), override: Override = NO_OVERRIDE
) -> dict[str, list[str]]:
    """Every geo tag in use (registry + the legacy base list) sorted into workspaces — what the UI filters with."""
    seen: list[str] = []
    for t in list(base) + [t for s in sources for t in (s.get("geo") or [])]:
        u = str(t or "").strip().upper()
        if u and u not in seen:
            seen.append(u)
    out: dict[str, list[str]] = {"eu": [], "na": [], "un": []}
    for u in seen:
        out[workspace_of_tag(u, override) or "un"].append(u)
    return out
