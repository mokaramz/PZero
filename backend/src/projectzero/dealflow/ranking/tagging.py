"""Ingest tagging (protected; old ``connectors.make`` + the per-record step of ``connectors._scan_one`` + the
Taste Map archetype / portfolio tables of ``taste.py``), so new leads reach the ranking with the same fields an
old scan produced. Rules, keyword lists, labels and orderings are verbatim (review 007).

Two passes, exactly as the old scan:
1. ``make_core`` — on the FULL ``name + " " + description``: archetypes, twins, noise, ``why``, priority; then the
   stored ``name[:120]`` / ``description[:600]``.
2. ``per_source`` — on the TRUNCATED fields and the source config: ``src_quality``, ``sectors`` (bio ->
   opportunistic), the reliability priority bonus (with the old ``priority or 5`` quirk), the probation line.

Clock-dependent fields of the old code (``detected_on``, ``first_seen``) are parameters here, never ``today()``.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any, TypeGuard

# ------------------------------------------------------------ Taste Map v2.2 archetypes (ids, names, keywords)
ARCHETYPES: list[tuple[int, str, list[str]]] = [
    (1, "Vertical AI agent for a paper-heavy operational job in a traditional European B2B industry",
     ["freight", "forward", "customs", "zoll", "claims", "underwrit", "accounting", "buchhaltung", "invoice", "back-office", "ai worker", "agents", "workflow", "erp"]),
    (2, "Cross-border industrial trade or procurement platform for a fragmented physical commodity, with embedded financing, logistics or pricing intelligence",
     ["procurement", "beschaffung", "marketplace", "metals", "metall", "chemical", "chemie", "fertili", "industrial supply", "parts", "materials trading", "packaging"]),
    (3, "\"Regulated-by-design\" financial infrastructure",
     ["stablecoin", "mica", "e-money", "payments", "working capital", "financing", "credit", "lending", "treasury", "fca", "bafin"]),
    (4, "Insurance infrastructure for new or under-served commercial risks",
     ["insurance", "versicher", "insurtech", "underwriting", "claims", "fraud", "mga", "risk assessment"]),
    (5, "Defence software layer",
     ["defence", "defense", "verteidigung", "c2", "c4isr", "isr", "sensor fusion", "electronic warfare", "military", "nato", "bundeswehr", "diana", "eudis"]),
    (6, "Dual-use autonomous platforms with a fleet/software brain",
     ["drone", "drohne", "uav", "ugv", "unmanned", "autonomous", "counter-drone", "evtol", "swarm", "robot"]),
    (7, "Industrial autonomy software for manufacturing",
     ["manufacturing", "fertigung", "shop floor", "plc", "automation", "automatisierung", "maintenance", "mro", "spare parts", "digital twin", "industrial ai"]),
    (8, "Energy & critical-infrastructure intelligence",
     ["energy", "energie", "grid", "netz", "charging", "ladepunkt", "battery", "geothermal", "critical minerals", "ppa", "power"]),
    (9, "Decarbonisation compliance data infrastructure",
     ["cbam", "carbon", "co2", "scope 3", "certification", "zertifizierung", "emissions", "decarbon"]),
    (10, "Sovereign compute / chips / photonics / secure infrastructure",
     ["chip", "semiconductor", "photonic", "quantum", "compute", "sovereign", "souverän", "secure infrastructure"]),
    (11, "Agent-infrastructure with a sharp wedge from repeat/technical founders",
     ["llm", "fine-tun", "agent framework", "orchestration", "evaluation", "inference", "small model", "developer", "sdk", "open-source"]),
    (12, "Workforce & skills platforms for physical industries with labour shortages",
     ["workforce", "training", "installer", "technician", "fachkräfte", "skills", "hiring"]),
    (13, "Studio-style pre-company duos",
     ["stealth", "pre-company", "exploring", "building something new", "co-founder wanted", "studio"]),
    (14, "Sovereignty-framed bio-manufacturing / materials",
     ["bio-manufactur", "fermentation", "materials", "magnet", "rare earth", "feedstock", "biomaterial"]),
    (15, "OUTLIER / NEW FRONTIER (no portfolio twin required)", []),
]  # fmt: skip

# ------------------------------------------------------------ Project A portfolio (conflict-check hints only)
PORTFOLIO: list[tuple[str, list[str]]] = [
    ("Nexcade", ["freight", "forward", "quoting", "booking", "logistics agent"]),
    ("Tabular", ["accounting", "buchhaltung", "ledger", "bookkeeping", "vat"]),
    ("Nettle", ["insurance", "underwriting", "inspection", "commercial insurance", "risk assessment"]),
    ("Rematiq", ["medtech", "mdr", "fda", "regulatory", "compliance", "medical device"]),
    ("Resourcly", ["spare parts", "inventory", "idle parts", "mro", "manufactur"]),
    ("Linexa", ["shop floor", "plc", "automation logic", "manufactur", "downtime"]),
    ("Avoltra", ["energy procurement", "energy", "ppa", "industrial energy"]),
    ("Pactum", ["negotiation", "supplier", "procurement"]),
    ("Vestigas", ["construction", "delivery note", "bau", "lieferschein"]),
    ("Atmen", ["certification", "carbon intensity", "cbam", "hydrogen", "decarbon"]),
    ("Enapi", ["ev charging", "charging", "clearing", "emsp", "cpo"]),
    ("Andercore", ["industrial supply", "trade platform", "cross-border", "b2b marketplace"]),
    ("Metycle", ["metal", "metall", "scrap", "recycling marketplace"]),
    ("Waypoint", ["fertili", "commodity chemical", "chemicals marketplace"]),
    ("Laserhub", ["metal parts", "sheet metal", "cnc", "laser cut"]),
    ("Mimo", ["sme payments", "accounts payable", "credit", "bookkeepers"]),
    ("Re:cap", ["non-dilutive", "revenue-based", "debt funding", "financial operations"]),
    ("Copay", ["early payment", "subcontractor", "construction payments"]),
    ("Riva", ["blockchain payments", "instant payments", "b2b payments"]),
    ("ReStabilise", ["stablecoin", "e-money", "digital money", "fca"]),
    ("Baobab", ["cyber insurance", "mga", "it liability", "cyber risk"]),
    ("Claimer", ["r&d tax", "tax credit", "hmrc"]),
    ("Project Q", ["sensor", "sensor fusion", "defence intelligence", "real-time intelligence", "c2"]),
    ("Scipio", ["military logistics", "resupply", "c4isr", "defence logistics"]),
    ("ARX Robotics", ["ugv", "ground robot", "unmanned ground"]),
    ("Quantum Systems", ["uav", "isr drone", "evtol drone", "reconnaissance"]),
    ("STARK", ["loitering", "munition", "strike drone"]),
    ("Black Semiconductor", ["photonic", "graphene", "chip", "semiconductor"]),
    ("Hades", ["geothermal", "critical minerals", "mining", "subsurface"]),
    ("Vaeridion", ["electric aircraft", "regional aviation", "aviation"]),
    ("Twig Bio", ["fermentation", "bio ingredient", "biomanufactur"]),
    ("Distil Labs", ["small language model", "fine-tun", "slm"]),
    ("Restack", ["agent backend", "agent framework", "orchestration"]),
    ("Flow AI", ["agent evaluation", "test data", "agent testing"]),
    ("Montamo", ["installer", "heat pump", "training", "workforce"]),
    ("Labrys", ["workforce management", "global teams", "payroll"]),
    ("11x", ["sdr", "sales agent", "outbound"]),
    ("Dixa", ["customer service", "support platform"]),
    ("Root Global", ["scope 3", "agri", "farm emissions"]),
    ("Architect", ["landing page", "conversion", "personalis"]),
]

NOISE = [
    "holding",
    "immobilien",
    "real estate",
    "consulting",
    "beratung",
    "verwaltung",
    "gastro",
    "restaurant",
    "friseur",
    "praxis",
    "physio",
    "handel ",
    "beteiligung",
    "invest ag",
]  # fmt: skip  ("handel " keeps its space)

# Broad single industry words: never enough ON THEIR OWN to assign an archetype; they still count toward two hits.
AMBIGUOUS_KW = {
    "chemical", "chemicals", "packaging", "procurement", "credit", "financing", "financial", "finance", "insurance",
    "banking", "payments", "compliance", "logistics", "industrial", "manufacturing", "materials", "software",
    "platform", "infrastructure", "automation", "energy", "mobility", "healthcare", "pharma", "commerce", "retail",
    "construction", "agriculture", "security", "enterprise", "operations", "maintenance",
}  # fmt: skip

SECTOR_KEYWORDS = {
    "bio": r"\b(biotech\w*|bio-?pharm\w*|pharma\w*|drug|therapeut\w*|clinical|oncolog\w*|antibod\w*|vaccine\w*|genomic\w*|proteom\w*|cell therap\w*|medtech|medical device|diagnostic\w*|biomarker\w*|molecular biolog\w*)\b",
    "space": r"\b(satellite\w*|orbital|launch vehicle|space(craft|port| debris| station)?|in-orbit|earth observation|lunar|cubesat\w*|rocket\w*)\b",
    "defence": r"\b(defen[cs]e|dual-?use|military|nato|isr|battlefield|c4isr|counter-?uas|munition\w*)\b",
    "robotics": r"\b(robot\w*|autonomous (system\w*|vehicle\w*|driving|navigation|inspection)|drone\w*|uav|ugv|manipulat\w*|slam|humanoid\w*)\b",
    "climate": r"\b(climate|carbon|decarboni\w*|renewable\w*|solar|wind energy|geothermal|hydrogen|batter(y|ies)|energy storage|grid|fusion energy|e-?fuel\w*)\b",
    "semis_quantum": r"\b(semiconductor\w*|chip(let)?s?|photonic\w*|quantum|wafer\w*|lithograph\w*|asic|fpga|rf front|gan|sic power)\b",
    "deeptech": r"\b(deep-?tech|advanced material\w*|advanced manufactur\w*|additive manufactur\w*|3d print\w*|nanotech\w*|sensor\w*|catalys\w*|superconduct\w*|cryogenic\w*|spinoff|spin-?out|ausgründung)\b",
    "ai_sw": r"\b(ai|artificial intelligence|machine learning|llm\w*|foundation model\w*|computer vision|software|saas|api platform|agentic|data platform)\b",
}
_SECTOR_RE = {k: re.compile(v, re.I) for k, v in SECTOR_KEYWORDS.items()}

INTERSTITIAL = re.compile(
    r"(activate|enable|accept|allow)\s+(the\s+)?cookies|cookie\s+(settings|policy|banner|consent)|"
    r"consent\s+(manager|required)|we\s+use\s+cookies|diese\s+website\s+verwendet\s+cookies|"
    r"enable\s+javascript|javascript\s+(is\s+)?(required|disabled)|javascript\s+has\s+been\s+disabled|"
    r"are\s+you\s+a\s+(robot|human)|verify\s+you\s+are|captcha|access\s+denied|error\s+403|"
    r"log\s?in\s+to\s+continue|sign\s+in\s+to\s+continue|subscribe\s+to\s+(read|continue)|"
    r"browser\s+(is\s+)?(out\s?dated|not\s+supported|update)|your\s+browser|please\s+update\s+your",
    re.I,
)
RELIABILITY_POINTS = {"high": 2, "medium": 1, "low": 0}


def is_interstitial(text: str | None) -> bool:
    """Cookie banners, consent pages, bot checks, login walls, JS notices — page plumbing, never a company."""
    return bool(INTERSTITIAL.search(text or ""))


def interstitial_check_text(name: str, description: str) -> str:
    """The exact text the old scan tested before keeping a record: its STORED (already truncated) name and
    description, ``(name[:120] + " " + description[:600])[:400]``."""
    return (name[:120] + " " + description[:600])[:400]


def strong_archetypes(text: str | None) -> list[tuple[int, str, int]]:
    """Word-boundary matching; an archetype only on (a) a multi-word phrase hit, (b) a distinctive single keyword
    (>= 8 chars, not a broad industry word), or (c) two independent hits. Top 3 by (hits, id), descending."""
    t = " " + (text or "").lower() + " "
    out = []
    for aid, name, kws in ARCHETYPES:
        hits = [k for k in kws if re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", t)]
        strong_single = any((" " in k) or (len(k) >= 8 and k not in AMBIGUOUS_KW) for k in hits)
        if strong_single or len(hits) >= 2:
            out.append((len(hits), aid, name))
    return [(aid, name, n) for n, aid, name in sorted(out, reverse=True)[:3]]


def suggest_twins(text: str) -> list[str]:
    """Portfolio companies whose keywords appear (plain substring), top 3 by hits (stable for ties)."""
    t = " " + text.lower() + " "
    out = []
    for name, kws in PORTFOLIO:
        hits = [k for k in kws if k in t]
        if hits:
            out.append((name, len(hits)))
    return [name for name, _ in sorted(out, key=lambda x: -x[1])[:3]]


def classify_sectors(text: str | None) -> list[str]:
    """Sectors of the CANDIDATE from its own text — source sectors are context, never copied."""
    t = " " + (text or "") + " "
    return [k for k, rx in _SECTOR_RE.items() if rx.search(t)]


def record_id(source: str, name: str) -> str:
    return hashlib.sha1("|".join((source, name)).encode()).hexdigest()[:12]  # an id, not security


def make_core(name: str, description: str, tier: str, source: str) -> dict[str, Any]:
    """Old ``connectors.make`` minus its clock/url/location fields (the caller adds those)."""
    text = name + " " + description
    arche = strong_archetypes(text)
    twins = suggest_twins(text)
    noisy = any(n in (" " + text.lower() + " ") for n in NOISE)
    why = []
    if arche:
        why.append("Archetype keyword match: " + "; ".join(f"#{a} {n}" for a, n, _ in arche))
    if tier == "pre_company":
        why.append("Pre-company channel — this is where the sourcing edge is")
    if tier == "announcement":
        why.append("Announcement feed — discovery only; probably recently funded")
    if twins:
        why.append("Possible portfolio twin(s): " + ", ".join(twins) + " → run conflict check")
    if noisy:
        why.append("⚠ Looks like holding/consulting/services — likely noise")
    return {
        "id": record_id(source, name),
        "name": name[:120],
        "source": source,
        "discovery_tier": tier,
        "description": description[:600],
        "why": why,
        "archetype_hits": [a for a, _, _ in arche],
        "twins": twins,
        "noise": noisy,
        "decision": "rejected" if noisy else "new",
        "notes": "auto-rejected: looks like noise — bring back if wrong" if noisy else "",
        "priority": (3 if tier == "pre_company" else 1) + 2 * len(arche) + (1 if twins else 0) - (10 if noisy else 0),
    }


def per_source(record: dict[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    """The per-record part of old ``_scan_one`` that shapes ranking inputs (source config: id, reliability,
    probation, geo, sectors). Mutates and returns ``record``, like the old loop."""
    reliability = source.get("reliability", "low")
    record["source_id"] = source["id"]
    record["geo"] = source.get("geo", [])
    record["src_quality"] = RELIABILITY_POINTS[reliability]
    record["source_sectors"] = source.get("sectors", [])
    record["sectors"] = classify_sectors(record.get("name", "") + " " + record.get("description", ""))
    if "bio" in record["sectors"]:
        record["opportunistic"] = True
        record["why"] = (record.get("why") or []) + [
            "OPPORTUNISTIC — candidate text is bio/pharma; outside core themes, #15 outlier route only"
        ]
    record["priority"] = (record.get("priority") or 5) + RELIABILITY_POINTS[reliability]
    if source.get("probation"):
        record["probation_source"] = True
        record["why"] = (record.get("why") or []) + [
            "From a PROBATION source — new, limited trust, still being measured"
        ]
    return record


# ------------------------------------------------------------ cross-source provenance (old discovery.absorb)
_TIER_RANK = {"pre_company": 0, "grant": 1, "announcement": 2}


def finalize_provenance(record: dict[str, Any]) -> dict[str, Any]:
    """Old ``discovery.finalize_provenance``: every producing source id, and the deterministic quality source."""
    prov = [(record.get("source_id") or "", record.get("discovery_tier") or "announcement",
             record.get("source_date") or "")]  # fmt: skip
    for a in record.get("also_seen") or []:
        if a.get("source_id"):
            prov.append((a["source_id"], a.get("discovery_tier") or "announcement", a.get("source_date") or ""))
    prov = [x for x in prov if x[0]]
    record["all_source_ids"] = sorted({x[0] for x in prov})
    if prov:
        best = min(prov, key=lambda x: (_TIER_RANK.get(x[1], 3), x[2] or "9999-12-31", x[0]))
        record["quality_source_id"] = best[0]
    return record


def absorb(host: dict[str, Any], sighting: Mapping[str, Any]) -> int:
    """The scoring part of old ``discovery.absorb``: a source not yet on the host becomes provenance (+2 priority,
    a why line). Run counters, entity ids and funnel milestones are not ranking inputs and are not kept."""
    host.setdefault("also_seen", [])
    have = {host.get("source")} | {a.get("source") for a in host["also_seen"]}
    added = 0
    if sighting.get("source") and sighting["source"] not in have:
        host["also_seen"].append(dict(sighting))
        added += 1
        host["priority"] = (host.get("priority") or 5) + 2
        host["why"] = (host.get("why") or []) + [f"Cross-source signal: also seen on {sighting['source']}"]
    if added:
        finalize_provenance(host)
    return added


# ------------------------------------------------------------ decision 0002: Grok / manual leads
TAGGING_VERSION = 1
LIVE_SOURCES: dict[str, dict[str, Any]] = {
    "grok": {"id": "live-grok", "name": "Grok scout", "reliability": "medium", "probation": False},
    "manual": {"id": "live-manual", "name": "Manual", "reliability": "medium", "probation": False},
}


def live_tier(stage: Any, flags: Any) -> str:
    """Decision 0002 #2: pre_company when Grok says so (stage or flags pre_company / stealth), else manual."""
    if stage == "pre_company" or set(flags or []) & {"pre_company", "stealth"}:
        return "pre_company"
    return "manual"


def live_inputs(origin: str, name: Any, key_fact: Any, stage: Any, flags: Any) -> dict[str, Any]:
    """Everything the tags depend on, stored with them so a later read or re-report can replay them exactly."""
    source = LIVE_SOURCES[origin]
    return {
        "origin": origin,
        "name": str(name or "").strip(),
        "description": str(key_fact or ""),  # 0002 #1: key_fact -> description, full length for the first pass
        "tier": live_tier(stage, flags),
        "source": source["name"],
        "source_id": source["id"],
        "reliability": source["reliability"],
        "probation": source["probation"],  # 0002 #6: never on probation
        "stage": stage,
        "flags": list(flags or []),
    }


def sighting_for(origin: str, stage: Any, flags: Any, first_seen: str) -> dict[str, Any]:
    """A later delivery from a DIFFERENT live origin (0002 #4: evidence links are never sightings)."""
    source = LIVE_SOURCES[origin]
    return {"source": source["name"], "url": "", "source_id": source["id"],
            "discovery_tier": live_tier(stage, flags), "source_date": "", "first_seen": first_seen}  # fmt: skip


def tag(inputs: Mapping[str, Any], sightings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Versioned tags from stored inputs: a deterministic function, so equal inputs always give equal tags."""
    record = make_core(inputs["name"], inputs["description"], inputs["tier"], inputs["source"])
    record = per_source(record, {"id": inputs["source_id"], "reliability": inputs["reliability"],
                                 "probation": inputs["probation"], "geo": [], "sectors": []})  # fmt: skip
    # 0002 #7: a noisy lead stays new and gated; the generated auto-reject note never becomes an operator note
    record["decision"] = "new"
    record["notes"] = ""
    finalize_provenance(record)
    for sighting in sightings or []:
        absorb(record, sighting)
    return {"version": TAGGING_VERSION, "inputs": dict(inputs), "sightings": list(sightings or []), "record": record}


def is_current(tagging: Any) -> TypeGuard[dict[str, Any]]:
    return isinstance(tagging, dict) and tagging.get("version") == TAGGING_VERSION and "record" in tagging
