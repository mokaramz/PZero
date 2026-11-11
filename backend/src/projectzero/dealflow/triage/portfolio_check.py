"""Project A portfolio / relationship / conflict lookup for discovered candidates (protected; old
``domain/portfolio_check.py``, verbatim).

Reuses what Project Zero already stores — nothing new is invented:
  * the Taste Map portfolio (``tagging.PORTFOLIO`` keywords + ``PORTFOLIO_WHAT`` below): active Project A companies;
    ``suggest_twins`` for resemblance
  * Conviction records with their human-set ``conflict`` field
  * Scout Intake items

Rules (deterministic):
  KNOWN_PORTFOLIO         the candidate's company name IS a Project A portfolio company (public membership)
  PROJECT_A_RELATIONSHIP  the candidate's own text names Project A as an investor / partner
  RESEMBLES_PORTFOLIO     ≥2 portfolio keywords of one company match (possible conflict — Omar decides)
  EXISTING_RECORD         already in Conviction or Scout Intake (shows the human-set conflict if any)
  NONE

The machine never clears a conflict: ``potential_conflict`` / ``unclear`` and every resemblance route to Omar.

The only change: the Conviction records and Scout Intake items are passed in (``Checker(signals, items)``), never read
from disk.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from projectzero.dealflow.ranking.names import norm_company
from projectzero.dealflow.ranking.tagging import PORTFOLIO as PORTFOLIO_KEYWORDS
from projectzero.dealflow.triage import entity_repair

# What each portfolio company does (old ``taste.PORTFOLIO``'s second column; the keywords live in ``tagging.PORTFOLIO``,
# same order). Shown in the evidence and twin lines.
PORTFOLIO_WHAT = {
    "Nexcade": "AI agents for freight forwarders: quoting, tenders, rates, bookings, reporting",
    "Tabular": "AI accounting automation, ledger entries, VAT, reconciliation",
    "Nettle": "AI commercial-insurance risk assessment and inspections for insurers",
    "Rematiq": "AI compliance for medtech regulations (FDA/MDR) integrated into development",
    "Resourcly": "AI platform turning idle parts / long-tail inventory into profit for manufacturers",
    "Linexa": "AI mapping and unifying automation logic across shop floors",
    "Avoltra": "industrial energy procurement intelligence",
    "Pactum": "autonomous negotiation of supplier contracts",
    "Vestigas": "digital delivery notes / supply-chain documents for construction",
    "Atmen": "certification data infrastructure for sustainable/industrial products, carbon intensity",
    "Enapi": "transaction broker / clearing house for EV charging",
    "Andercore": "AI-driven industrial supply trade platform with pricing, delivery, financing",
    "Metycle": "managed marketplace for secondary metals",
    "Waypoint": "B2B marketplace for fertilisers and commodity chemicals",
    "Laserhub": "procurement platform for custom metal parts",
    "Mimo": "SME payments platform with built-in credit",
    "Re:cap": "non-dilutive debt funding + financial operations for digital businesses",
    "Copay": "early-payment platform between main contractors and subcontractors",
    "Riva": "blockchain-based B2B instant payments",
    "ReStabilise": "FCA-authorised regulated digital-money stablecoin",
    "Baobab": "MGA for digital/cyber risks: cyber insurance, IT liability",
    "Claimer": "automation of UK R&D tax credit claims",
    "Project Q": "modular sensor systems fusing data sources into real-time intelligence for defence operations",
    "Scipio": "AI-driven military resupply/logistics planning integrated with C2/C4ISR",
    "ARX Robotics": "modular unmanned ground systems for military and commercial use",
    "Quantum Systems": "eVTOL ISR drones and multi-domain autonomous systems",
    "STARK": "software-defined defence systems (loitering munitions)",
    "Black Semiconductor": "graphene photonics chips",
    "Hades": "ultra-deep geothermal energy and critical mineral extraction",
    "Vaeridion": "electric regional aircraft (Microliner)",
    "Twig Bio": "AI-defined bio-fermented ingredients",
    "Distil Labs": "fine-tuning small language models from few examples",
    "Restack": "backend framework for reliable AI agents",
    "Flow AI": "test data engine / evaluation for AI agents",
    "Montamo": "training newcomers as heat-pump / green-tech installers",
    "Labrys": "workforce management and payments for global teams in hard regions",
    "11x": "AI SDR / sales agents",
    "Dixa": "AI customer service platform",
    "Root Global": "Scope 3 measurement in agricultural supply chains",
    "Architect": "AI that adapts web pages per visitor",
}
# old ``taste.PORTFOLIO``: (name, what, keywords), in the protected order
PORTFOLIO: list[tuple[str, str, list[str]]] = [(name, PORTFOLIO_WHAT[name], kws) for name, kws in PORTFOLIO_KEYWORDS]

_PROJECT_A = re.compile(r"\bproject\s*a\b(?!\s*[:\-–]?\s*\d)(\s+ventures)?", re.I)  # noqa: RUF001  (verbatim rule)
_RELATIONSHIP_WORDS = re.compile(r"\b(invest|backed|led by|participat|round|funding|portfolio|partner)", re.I)


def suggest_twins(text: str) -> list[tuple[str, str, int]]:
    """Keyword match candidate text against portfolio → list of (name, what, hits). Discovery aid only.
    (Old ``taste.suggest_twins``.)"""
    t = " " + text.lower() + " "
    out = []
    for name, what, kws in PORTFOLIO:
        hits = [k for k in kws if k in t]
        if hits:
            out.append((name, what, len(hits)))
    return sorted(out, key=lambda x: -x[2])[:3]


def _norm(s: str) -> str:
    return norm_company(s or "")


def _portfolio_index() -> dict[str, tuple[str, str]]:
    return {_norm(name): (name, what) for name, what, _kws in PORTFOLIO}


def _dict_records(seq: Any) -> list[Any]:
    """Old ``compat.records(seq, where)`` without required keys: the dict records of a list or of a dict's values."""
    if isinstance(seq, dict):
        seq = list(seq.values())
    if not isinstance(seq, list):
        return []
    return [r for r in seq if isinstance(r, dict)]


def records_index(signals: Any, items: Any) -> dict[str, dict[str, Any]]:
    """Old ``_records()``: Conviction ``signals`` (in file order, a later record of the same name wins) and Scout Intake
    ``items`` (a dict or a list; the first of a name wins and never replaces a Conviction record)."""
    out: dict[str, dict[str, Any]] = {}
    for e in _dict_records(signals or []):
        if isinstance(e, dict) and e.get("company"):
            out[_norm(e["company"])] = {
                "where": "Conviction",
                "name": e["company"],
                "conflict": e.get("conflict"),
                "slug": e.get("slug") or e.get("company"),
            }
    items = items or {}
    for it in items.values() if isinstance(items, dict) else items:
        if isinstance(it, dict) and it.get("entity_name"):
            out.setdefault(
                _norm(it["entity_name"]),
                {"where": "Scout Intake", "name": it["entity_name"], "conflict": None, "status": it.get("status")},
            )
    out.pop("", None)
    return out


class Checker:
    """Build once per request (indexes Conviction / Scout Intake once), then ``check`` many candidates."""

    def __init__(self, signals: Any = None, items: Any = None) -> None:
        self.portfolio = _portfolio_index()
        self.records = records_index(signals, items)

    def names_for(self, c: Mapping[str, Any]) -> list[str]:
        rep = entity_repair.repair(c)
        names = [rep["display_name"]] + [e["name"] for e in rep["entities"]]
        if not rep["broken"]:  # "KI-Security-Startup Kontext" is a usable label but the company is "Kontext"
            names += [e["name"] for e in entity_repair.extract_entities({"name": c.get("name"), "description": ""}, 2)]
        return [n for n in dict.fromkeys(names) if n and n.upper() != "UNKNOWN"]

    def check(self, c: Mapping[str, Any]) -> dict[str, Any]:
        names = self.names_for(c)
        text = f"{c.get('name') or ''} {c.get('description') or ''}"
        out: dict[str, Any] = {"status": "NONE", "route_to_omar": False, "evidence": [], "twins": [], "record": None}
        for n in names:
            hit = self.portfolio.get(_norm(n))
            if hit:
                out.update(status="KNOWN_PORTFOLIO", route_to_omar=True)
                out["evidence"].append(f"{hit[0]} is a Project A portfolio company ({hit[1]})")
                break
        m = _PROJECT_A.search(text)
        if m and _RELATIONSHIP_WORDS.search(text[max(0, m.start() - 120) : m.end() + 120]):
            if out["status"] == "NONE":
                out.update(status="PROJECT_A_RELATIONSHIP", route_to_omar=True)
            out["evidence"].append(
                "the source text names Project A: …" + text[max(0, m.start() - 80) : m.end() + 60].strip() + "…"
            )
        twins = [(n, w, h) for n, w, h in suggest_twins(text) if h >= 2]
        if twins:
            out["twins"] = [{"name": n, "what": w, "keyword_hits": h} for n, w, h in twins]
            if out["status"] == "NONE":
                out.update(status="RESEMBLES_PORTFOLIO", route_to_omar=True)
                out["evidence"].append(f"resembles portfolio company {twins[0][0]} ({twins[0][2]} keyword hits)")
        for n in names:
            rec = self.records.get(_norm(n))
            if rec:
                out["record"] = rec
                if rec.get("conflict") in ("potential_conflict", "unclear"):
                    out["route_to_omar"] = True
                    out["evidence"].append(f"{rec['where']} record has conflict = {rec['conflict']} (human-set)")
                if out["status"] == "NONE":
                    out["status"] = "EXISTING_RECORD"
                break
        return out
