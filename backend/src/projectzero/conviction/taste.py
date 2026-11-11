"""The Project A Taste Map v2.2 — the old ``domain/taste.py`` (protected gold-master), ported verbatim (review 011).

Every constant, string, weight, threshold and ordering below is copied byte for byte from the old module at revision
6c739b9 (only the type annotations are new). ``score`` is the frozen rubric; ``days_since`` takes the clock as a
parameter instead of reading ``date.today()``. ``meta`` is the old ``GET /api/meta`` body (``api/routers/system._meta``).
Goldens from the OLD code: ``tests/fixtures/golden_v1/oracle_conviction.json``. Pure logic, no I/O.
"""

from __future__ import annotations

from datetime import date
from typing import Any

# fmt: off
# ------------------------------------------------------------ archetypes ---
# id, name, one-line test, keywords (for discovery tagging only — never for judgment)
ARCHETYPES = [
    # (id, name — verbatim from PROJECT-A-TASTE-MAP.md §4, test, discovery keywords). Keywords tag candidates only; they never judge.
    (1, "Vertical AI agent for a paper-heavy operational job in a traditional European B2B industry",
     "freight forwarding, customs, insurance claims/underwriting, accounting/tax, construction logistics, medtech/pharma compliance, energy back-office — founder can name the role being replaced",
     ["freight", "forward", "customs", "zoll", "claims", "underwrit", "accounting", "buchhaltung", "invoice", "back-office", "ai worker", "agents", "workflow", "erp"]),
    (2, "Cross-border industrial trade or procurement platform for a fragmented physical commodity, with embedded financing, logistics or pricing intelligence",
     "metals, chemicals, fertiliser, packaging, industrial parts, building materials",
     ["procurement", "beschaffung", "marketplace", "metals", "metall", "chemical", "chemie", "fertili", "industrial supply", "parts", "materials trading", "packaging"]),
    (3, "\"Regulated-by-design\" financial infrastructure",
     "stablecoin/e-money under MiCA/FCA, B2B payment rails with credit, SME working capital in a vertical, non-dilutive financing",
     ["stablecoin", "mica", "e-money", "payments", "working capital", "financing", "credit", "lending", "treasury", "fca", "bafin"]),
    (4, "Insurance infrastructure for new or under-served commercial risks",
     "MGAs, AI underwriting/inspection, cyber/climate/fleet risk data",
     ["insurance", "versicher", "insurtech", "underwriting", "claims", "fraud", "mga", "risk assessment"]),
    (5, "Defence software layer",
     "sensor fusion, C2/C4ISR integration, resupply/logistics planning, training & simulation, EW/data — software-defined, legacy-compatible, European/NATO customers, dual-use path",
     ["defence", "defense", "verteidigung", "c2", "c4isr", "isr", "sensor fusion", "electronic warfare", "military", "nato", "bundeswehr", "diana", "eudis"]),
    (6, "Dual-use autonomous platforms with a fleet/software brain",
     "UGV, UAV, maritime, counter-drone from teams with defence access AND a commercial market",
     ["drone", "drohne", "uav", "ugv", "unmanned", "autonomous", "counter-drone", "evtol", "swarm", "robot"]),
    (7, "Industrial autonomy software for manufacturing",
     "PLC/automation-logic AI, adaptive robot control, predictive maintenance, MRO/spare-parts optimisation, digital twins for old plants",
     ["manufacturing", "fertigung", "shop floor", "plc", "automation", "automatisierung", "maintenance", "mro", "spare parts", "digital twin", "industrial ai"]),
    (8, "Energy & critical-infrastructure intelligence",
     "industrial energy procurement/PPA optimisation, EV-charging settlement/clearing, grid-asset software, geothermal/critical minerals with a sovereignty story",
     ["energy", "energie", "grid", "netz", "charging", "ladepunkt", "battery", "geothermal", "critical minerals", "ppa", "power"]),
    (9, "Decarbonisation compliance data infrastructure",
     "CBAM, product carbon certificates, Scope 3 in agri/steel/chemicals — where an EU regulation creates a mandatory buyer",
     ["cbam", "carbon", "co2", "scope 3", "certification", "zertifizierung", "emissions", "decarbon"]),
    (10, "Sovereign compute / chips / photonics / secure infrastructure",
     "Frontier, only with world-class technical founders and an 'Europe cannot depend on X' narrative",
     ["chip", "semiconductor", "photonic", "quantum", "compute", "sovereign", "souverän", "secure infrastructure"]),
    (11, "Agent-infrastructure with a sharp wedge from repeat/technical founders",
     "evaluation, fine-tuning, orchestration, domain-specific small models — London/Nordics-heavy",
     ["llm", "fine-tun", "agent framework", "orchestration", "evaluation", "inference", "small model", "developer", "sdk", "open-source"]),
    (12, "Workforce & skills platforms for physical industries with labour shortages",
     "installers, technicians, defence/industrial hiring, workforce in hard regions",
     ["workforce", "training", "installer", "technician", "fachkräfte", "skills", "hiring"]),
    (13, "Studio-style pre-company duos",
     "a domain insider + engineer with a thesis in archetypes 1–9, no company yet, ideally Munich/Berlin/London — Project A Studio candidates",
     ["stealth", "pre-company", "exploring", "building something new", "co-founder wanted", "studio"]),
    (14, "Sovereignty-framed bio-manufacturing / materials",
     "bio-fermented ingredients, alternative feedstocks, new materials — rare; needs exceptional team",
     ["bio-manufactur", "fermentation", "materials", "magnet", "rare earth", "feedstock", "biomaterial"]),
    (15, "OUTLIER / NEW FRONTIER (no portfolio twin required)",
     "exceptional founders + huge market + powerful why-now + genuine differentiation + early — no theme required; scored through the outlier route", []),
]
# NOTE: "Cyber & Risk Tech" is a Project A portfolio INDUSTRY (Baobab, Claimer, Project Q), not an approved archetype.
# Cyber/risk companies map to #4 (insurance/risk data), #9 (compliance data infra) or #3 where they fit, or are flagged ADJACENT (emerging=True).
ARCHETYPE_BY_ID = {a[0]: a for a in ARCHETYPES}

# ------------------------------------------------------------- portfolio ---
# Active Project A companies relevant to conflict checks: name, what it does, keywords.
PORTFOLIO = [
    ("Nexcade", "AI agents for freight forwarders: quoting, tenders, rates, bookings, reporting", ["freight", "forward", "quoting", "booking", "logistics agent"]),
    ("Tabular", "AI accounting automation, ledger entries, VAT, reconciliation", ["accounting", "buchhaltung", "ledger", "bookkeeping", "vat"]),
    ("Nettle", "AI commercial-insurance risk assessment and inspections for insurers", ["insurance", "underwriting", "inspection", "commercial insurance", "risk assessment"]),
    ("Rematiq", "AI compliance for medtech regulations (FDA/MDR) integrated into development", ["medtech", "mdr", "fda", "regulatory", "compliance", "medical device"]),
    ("Resourcly", "AI platform turning idle parts / long-tail inventory into profit for manufacturers", ["spare parts", "inventory", "idle parts", "mro", "manufactur"]),
    ("Linexa", "AI mapping and unifying automation logic across shop floors", ["shop floor", "plc", "automation logic", "manufactur", "downtime"]),
    ("Avoltra", "industrial energy procurement intelligence", ["energy procurement", "energy", "ppa", "industrial energy"]),
    ("Pactum", "autonomous negotiation of supplier contracts", ["negotiation", "supplier", "procurement"]),
    ("Vestigas", "digital delivery notes / supply-chain documents for construction", ["construction", "delivery note", "bau", "lieferschein"]),
    ("Atmen", "certification data infrastructure for sustainable/industrial products, carbon intensity", ["certification", "carbon intensity", "cbam", "hydrogen", "decarbon"]),
    ("Enapi", "transaction broker / clearing house for EV charging", ["ev charging", "charging", "clearing", "emsp", "cpo"]),
    ("Andercore", "AI-driven industrial supply trade platform with pricing, delivery, financing", ["industrial supply", "trade platform", "cross-border", "b2b marketplace"]),
    ("Metycle", "managed marketplace for secondary metals", ["metal", "metall", "scrap", "recycling marketplace"]),
    ("Waypoint", "B2B marketplace for fertilisers and commodity chemicals", ["fertili", "commodity chemical", "chemicals marketplace"]),
    ("Laserhub", "procurement platform for custom metal parts", ["metal parts", "sheet metal", "cnc", "laser cut"]),
    ("Mimo", "SME payments platform with built-in credit", ["sme payments", "accounts payable", "credit", "bookkeepers"]),
    ("Re:cap", "non-dilutive debt funding + financial operations for digital businesses", ["non-dilutive", "revenue-based", "debt funding", "financial operations"]),
    ("Copay", "early-payment platform between main contractors and subcontractors", ["early payment", "subcontractor", "construction payments"]),
    ("Riva", "blockchain-based B2B instant payments", ["blockchain payments", "instant payments", "b2b payments"]),
    ("ReStabilise", "FCA-authorised regulated digital-money stablecoin", ["stablecoin", "e-money", "digital money", "fca"]),
    ("Baobab", "MGA for digital/cyber risks: cyber insurance, IT liability", ["cyber insurance", "mga", "it liability", "cyber risk"]),
    ("Claimer", "automation of UK R&D tax credit claims", ["r&d tax", "tax credit", "hmrc"]),
    ("Project Q", "modular sensor systems fusing data sources into real-time intelligence for defence operations", ["sensor", "sensor fusion", "defence intelligence", "real-time intelligence", "c2"]),
    ("Scipio", "AI-driven military resupply/logistics planning integrated with C2/C4ISR", ["military logistics", "resupply", "c4isr", "defence logistics"]),
    ("ARX Robotics", "modular unmanned ground systems for military and commercial use", ["ugv", "ground robot", "unmanned ground"]),
    ("Quantum Systems", "eVTOL ISR drones and multi-domain autonomous systems", ["uav", "isr drone", "evtol drone", "reconnaissance"]),
    ("STARK", "software-defined defence systems (loitering munitions)", ["loitering", "munition", "strike drone"]),
    ("Black Semiconductor", "graphene photonics chips", ["photonic", "graphene", "chip", "semiconductor"]),
    ("Hades", "ultra-deep geothermal energy and critical mineral extraction", ["geothermal", "critical minerals", "mining", "subsurface"]),
    ("Vaeridion", "electric regional aircraft (Microliner)", ["electric aircraft", "regional aviation", "aviation"]),
    ("Twig Bio", "AI-defined bio-fermented ingredients", ["fermentation", "bio ingredient", "biomanufactur"]),
    ("Distil Labs", "fine-tuning small language models from few examples", ["small language model", "fine-tun", "slm"]),
    ("Restack", "backend framework for reliable AI agents", ["agent backend", "agent framework", "orchestration"]),
    ("Flow AI", "test data engine / evaluation for AI agents", ["agent evaluation", "test data", "agent testing"]),
    ("Montamo", "training newcomers as heat-pump / green-tech installers", ["installer", "heat pump", "training", "workforce"]),
    ("Labrys", "workforce management and payments for global teams in hard regions", ["workforce management", "global teams", "payroll"]),
    ("11x", "AI SDR / sales agents", ["sdr", "sales agent", "outbound"]),
    ("Dixa", "AI customer service platform", ["customer service", "support platform"]),
    ("Root Global", "Scope 3 measurement in agricultural supply chains", ["scope 3", "agri", "farm emissions"]),
    ("Architect", "AI that adapts web pages per visitor", ["landing page", "conversion", "personalis"]),
]

CONFLICT_LABELS = {
    "none": "No portfolio twin identified",
    "similar": "Similar taste, different market (+)",
    "complementary": "Complementary to a portfolio company (+, intro reason)",
    "potential_conflict": "POTENTIAL PORTFOLIO CONFLICT — do not forward until Omar/Project A confirms whether it is investable",
    "unclear": "Conflict unclear — verify with Omar before forwarding",
}

FUNDRAISING_TIMING = {
    "raising_now": ("Raising now (evidence)", "Contact within 48h. Ask who leads; offer Project A intro this week."),
    "0_6m": ("Likely raising in 0–6 months", "Contact this week. Build the relationship before the process starts."),
    "6_12m": ("Likely raising in 6–12 months", "Relationship mode: one honest conversation now, check-in every 6–8 weeks."),
    "recently_funded": ("Recently funded / probably not raising", "LOW urgency. Congratulate, learn, note the likely next window. Do not pitch a round."),
    "unknown": ("Unknown", "Find out — make timing the first question in your outreach."),
}

EARLINESS = {  # value: (label, points)
    "pre_company": ("Pre-company / no round", 10),
    "grant_angel": ("Grant or angel money only", 8),
    "pre_seed": ("Pre-seed closed", 6),
    "seed": ("Seed closed", 3),
    "series_a_plus": ("Series A or later", 0),
    "unknown": ("Unknown", 0),
}

DISCOVERY_TIERS = {
    "pre_company": "Pre-company channel (DIANA/EUDIS, TUM/UnternehmerTUM, transfer office, grant winner, stealth/talent exit) — THE EDGE",
    "announcement": "Announcement feed — discovery only, usually recently funded",
    "register": "Company register",
    "manual": "Manual / relationship",
}

# scoring option ladders shown in the dashboard (label, points)
FOUNDER_LADDER = [("Unknown / not researched yet", 0), ("Some relevant experience, nothing standout", 8),
                  ("Domain insider OR strong technical founder", 14), ("Domain insider + technical co-founder", 20),
                  ("Repeat founder / prior exit + technical depth, or world-class technical team", 25)]
VS_LADDER = [("Niche — hard to see a €300M+ outcome", 4), ("Solid vertical, €1B possible but stretch", 9),
             ("Large/expanding market, wedge can grow into a platform", 14), ("Huge market, clear platform expansion, Europe→global path", 19)]
WHYNOW_LADDER = [("No credible reason it must exist now", 2), ("Weak / generic 'AI is here'", 6),
                 ("Clear structural driver (regulation, capability step, labour shortage)", 11), ("Powerful, dated driver (hard deadline, geopolitical shift, cost curve crossed)", 15)]
TASTE_LADDER = [("Outside Project A's taste (consumer, generic SaaS, services)", 0), ("Touches a theme superficially", 5),
                ("Fits a theme and the underlying taste (B2B, structural moat)", 10), ("Squarely inside a theme, textbook example", 15)]
INSIGHT_LADDER = [("Nothing non-obvious yet", 2), ("Some domain insight", 5), ("Proprietary distribution, data or regulatory access", 8),
                  ("Hard-won insight a generalist could not have", 10)]
PENALTIES = {"consumer": ("Consumer / D2C", -20), "non_eu": ("Non-European, no European founders", -15),
             "known": ("Already known to every VC / late", -15), "wrapper": ("AI wrapper, no vertical or data wedge", -10)}
RESEMBLANCE = {"none": 0, "clone": 2, "similar": 4, "complementary": 5}


def score(entry: dict[str, Any]) -> dict[str, Any]:
    """Return dict with provisional, verified, breakdown, verdict, flags. Never raises."""
    s = entry.get("scores", {}) or {}
    ver = entry.get("verified", {}) or {}
    founder = int(s.get("founder", 0))
    vs = int(s.get("venture_scale", 0))
    wn = int(s.get("why_now", 0))
    taste = int(s.get("taste", 0))
    ins = int(s.get("insight", 0))
    earl = EARLINESS.get(entry.get("earliness", "unknown"), EARLINESS["unknown"])[1]
    conflict = entry.get("conflict", "none")
    resem = RESEMBLANCE.get("complementary" if conflict == "complementary" else "similar" if conflict == "similar" else "none", 0)
    if entry.get("archetype") == 15:
        resem = 0
    pen = sum(PENALTIES[p][1] for p in entry.get("penalties", []) if p in PENALTIES)
    if conflict == "potential_conflict":
        pen -= 25
    provisional = max(0, min(100, founder + vs + wn + taste + earl + ins + resem + pen))
    # verified: zero what isn't checked
    f_v = founder if ver.get("founders") else 0
    e_v = earl if ver.get("funding") else 0
    i_v = ins if ver.get("traction") else ins // 2
    verified = max(0, min(100, f_v + vs + wn + taste + e_v + i_v + resem + pen))
    missing = [k for k in ("founders", "traction", "funding") if not ver.get(k)]
    outlier_ok = (entry.get("archetype") == 15 and ver.get("founders") and founder >= 22 and vs >= 17 and wn >= 12 and ins >= 8 and earl >= 6)
    basis = verified if not missing else provisional
    if conflict == "potential_conflict":
        verdict = "Potential portfolio conflict — ask Omar before anything"
    elif basis >= 80:
        verdict = "Investigate immediately"
    elif basis >= 65:
        verdict = "Research this week"
    elif basis >= 50:
        verdict = "Watch"
    else:
        verdict = "Drop unless something changes"
    timing = entry.get("fundraising_timing", "unknown")
    return {"provisional": provisional, "verified": verified, "missing": missing, "fully_verified": not missing,
            "verdict": verdict, "outlier_ok": bool(outlier_ok),
            "breakdown": {"founder": founder, "venture_scale": vs, "why_now": wn, "taste": taste,
                          "earliness": earl, "insight": ins, "resemblance": resem, "penalties": pen},
            "timing_label": FUNDRAISING_TIMING.get(timing, FUNDRAISING_TIMING["unknown"])[0],
            "timing_action": FUNDRAISING_TIMING.get(timing, FUNDRAISING_TIMING["unknown"])[1]}

# fmt: on


def days_since(iso: Any, today: date) -> int:
    try:
        return max(0, (today - date.fromisoformat(str(iso)[:10])).days)
    except Exception:
        return 0


def meta() -> dict[str, Any]:
    """The old ``/api/meta``: static Taste Map reference data for the scoring form."""
    return {
        "archetypes": [{"id": a[0], "name": a[1], "test": a[2]} for a in ARCHETYPES],
        "ladders": {
            "founder": FOUNDER_LADDER,
            "venture_scale": VS_LADDER,
            "why_now": WHYNOW_LADDER,
            "taste": TASTE_LADDER,
            "insight": INSIGHT_LADDER,
        },
        "earliness": {k: v[0] for k, v in EARLINESS.items()},
        "timing": {k: v[0] for k, v in FUNDRAISING_TIMING.items()},
        "conflict": CONFLICT_LABELS,
        "penalties": {k: v[0] for k, v in PENALTIES.items()},
        "tiers": DISCOVERY_TIERS,
        "portfolio": [{"name": n, "what": w} for n, w, _ in PORTFOLIO],
    }
