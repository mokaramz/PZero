"""Operating-queue routing for the Europe-first view (protected; old ``domain/routing.py``, verbatim).

Pure, deterministic, computed on read. Nothing is deleted, rewritten or hidden permanently: every candidate keeps its
raw source record and history, and the Global view still shows everything. This only answers "does this candidate belong
in the normal Europe-first operating queue?"

  operating     Europe (or unresolved geography) and a plausible startup / venture entity
  global_only   routes to North America (US/CA grants etc.) with no clear European connection in its own text
  non_startup   a university, government body, Catapult centre, public research organisation or large incumbent —
                kept as a source record, not routed as a startup investment candidate (a separate spinout/company found
                in the same record is a different entity)

The only change: the workspace override (old ``workspace_geos.json``) is passed in, never read from disk. The ecosystem
city list the old code took from ``ecosys.CITIES`` is copied here (``CITIES``), unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from projectzero.dealflow import workspaces

_UNIVERSITY = re.compile(
    r"\b(universit(y|ies|ät|at|é|e|à|a|eit)|college|school of|polytechnic|politecnico|hochschule|"
    r"institute of technology|eth z[uü]rich|epfl|imperial college|kings? college|ucl\b|"
    r"tu (m[uü]nchen|berlin|delft|wien)|"
    r"\bkth\b|chalmers|tudelft)",
    re.I,
)
_GOVERNMENT = re.compile(
    r"\b(department (of|for)|ministry|ministerium|council\b|county|borough|municipal|government|"
    r"\bagency\b|\bdstl\b|defence science and technology|met office|nhs\b|nhs trust|health board|"
    r"uk research and innovation|innovate uk|research council|\bukri\b|european commission|bundesamt)",
    re.I,
)
_CATAPULT = re.compile(r"\bcatapult\b", re.I)
_PUBLIC_RESEARCH = re.compile(
    r"\b(national (physical )?laborator(y|ies)|national lab\b|fraunhofer|max[- ]planck|helmholtz|leibniz|\bcnrs\b|"
    r"\binria\b|\bcea\b|\btno\b|\besa\b|estec|\bcern\b|perimeter inst|alan turing institute|research institute|"
    r"institut (f[uü]r|national)|institute (for|of) (physics|theoretical|advanced study)|lawrence (berkeley|livermore)|"
    r"\bnasa\b|\bnist\b|"
    r"rutherford appleton|culham|\bstfc\b|\bnpl\b)",
    re.I,
)
# Large incumbents that appear as grant participants. A small, explicit list beats a size guess.
_INCUMBENTS = (
    "bae systems",
    "thales",
    "airbus",
    "siemens",
    "rolls-royce",
    "rolls royce",
    "johnson matthey",
    "bp ",
    "shell ",
    "astrazeneca",
    "glaxosmithkline",
    "gsk",
    "unilever",
    "leonardo",
    "babcock",
    "qinetiq",
    "ibm",
    "microsoft",
    "google",
    "amazon",
    "nokia",
    "ericsson",
    "alcatel",
    "bosch",
    "philips",
    "toshiba",
    "hitachi",
    "jaguar land rover",
    "ford motor",
    "british telecom",
    "bt group",
    "vodafone",
    "national grid",
    "edf ",
    "arm limited",
    "lockheed",
    "boeing",
    "raytheon",
    "northrop",
    "general electric",
    "ge aviation",
    "safran",
    "mbda",
    "saab",
    "kongsberg",
    "rheinmetall",
    "hensoldt",
    "dassault",
    "orange sa",
    "telefonica",
    "deutsche telekom",
    "sap se",
    "basf",
    "bayer ag",
    "novartis",
    "roche",
    "nestle",
    "abb ",
    "schneider electric",
    "volkswagen",
    "bmw",
    "daimler",
    "mercedes-benz",
)  # the trailing spaces in "bp ", "shell ", "edf ", "abb " are part of the rule
_PLC = re.compile(r"\b(plc|p\.l\.c\.)\b", re.I)

# old ``ecosys.CITIES``: the curated ecosystem cities
CITIES = ["Karlsruhe", "Munich", "Zürich", "Lausanne", "Stuttgart", "Frankfurt", "Paris", "Amsterdam", "Delft",
          "Eindhoven", "Berlin", "Darmstadt", "London"]  # fmt: skip
_EXTRA_PLACES = {
    "europe", "european", "eu-funded", "horizon europe", "london", "munich", "münchen", "berlin", "paris", "zurich",
    "zürich", "amsterdam", "stockholm", "helsinki", "tallinn", "vilnius", "riga", "copenhagen", "oslo", "vienna",
    "wien", "warsaw", "prague", "lisbon", "madrid", "barcelona", "milan",
}  # fmt: skip


def _build_eu_places() -> tuple[str, ...]:
    names = {str(v).lower() for v in workspaces.EUROPE_CC.values()}
    names |= {c.lower() for c in CITIES}
    names |= _EXTRA_PLACES
    return tuple(sorted(n for n in names if len(n) >= 4))


# European country names + curated ecosystem cities, lower-case (for 'clear European connection')
EU_PLACES = _build_eu_places()


def non_startup_reason(c: Mapping[str, Any]) -> str:
    """'' unless the candidate's NAME identifies an obvious non-startup entity (the description may legitimately
    mention universities etc. — e.g. a spinout — so only the entity name is checked)."""
    name = str(c.get("name") or "").strip()
    if not name or name.upper() == "UNKNOWN":
        return ""
    low = " " + name.lower() + " "
    if _CATAPULT.search(name):
        return "Catapult centre (public innovation body)"
    if _UNIVERSITY.search(name):
        return "university / academic institution"
    if _GOVERNMENT.search(name):
        return "government / public body"
    if _PUBLIC_RESEARCH.search(name):
        return "public research organisation"
    for inc in _INCUMBENTS:
        if " " + inc.strip() + " " in low or low.strip().startswith(inc.strip()):
            return f"large incumbent ({inc.strip()})"
    if _PLC.search(name):
        return "listed company (PLC) — likely incumbent"
    return ""


def european_connection(c: Mapping[str, Any]) -> str:
    """A European place named in the candidate's own name/description/location ('' when none)."""
    text = (
        " "
        + re.sub(r"[^\w\s-]", " ", " ".join(str(c.get(k) or "") for k in ("name", "description", "location"))).lower()
        + " "
    )
    for place in EU_PLACES:
        if f" {place} " in text:
            return place
    return ""


def route(c: Mapping[str, Any], override: workspaces.Override = workspaces.NO_OVERRIDE) -> dict[str, str]:
    """{'queue': operating | global_only | non_startup, 'reason': ...} — never deletes, never rewrites."""
    ns = non_startup_reason(c)
    if ns:
        return {"queue": "non_startup", "reason": ns}
    ws = workspaces.workspace_of(c, override)
    if ws == "na":
        eu = european_connection(c)
        if eu:
            return {"queue": "operating", "reason": f"North American record with a European connection ({eu})"}
        return {"queue": "global_only", "reason": "North America — Europe-first view (switch to Global to see it)"}
    return {"queue": "operating", "reason": "Europe" if ws == "eu" else "geography unresolved — kept visible"}
