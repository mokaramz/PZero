"""Attention Engine (protected; old ``domain/attention.py`` V2 + V3 differentiation + V3.1 entity qualification).

A RANKING-ONLY layer: it decides which existing candidates deserve human attention first, and never touches the
official investment scoring, the Analyst or Radar.

  gate      -> UNKNOWN / unresolved / roundup / mismatched entities never enter the Attention Queue (nothing deleted)
  score_v2  -> explainable evidence signals (earliness, technical depth, source quality, Project A fit)
  diff      -> evidence-only differentiation from the existing text
  entity    -> conservative venture-entity qualification; NON_VENTURE is gated, uncertainty is penalised
  final     -> score_v2 + lens + diff + entity penalty
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from projectzero.dealflow.ranking import themes
from projectzero.dealflow.ranking.names import norm_company
from projectzero.dealflow.ranking.pytext import joined, spaced_list

Applied = list[tuple[str, int]]

# ------------------------------------------------------------------ gates
_ROUNDUP = re.compile(
    r"\b(round-?ups?|recaps?|weekly|monthly|newsletter|digest|awards?|winners|shortlist|"
    r"top\s?\d+|\d+\s+(startups?|companies|scale-?ups?|founders)|startups? to watch|"
    r"companies to watch|funding (news|wrap|roundup)|this week in|week in review|"
    r"finalists?|nominees|overview of|list of|guide to|state of|report:|announces? \d+)\b",
    re.I,
)
_PERSON = re.compile(r"\b(dr\.|prof\.|professor|phd student|researcher|scientist|lecturer)\b", re.I)
_VERB_SUBJECT = re.compile(  # case-SENSITIVE on purpose: a capitalised subject before the verb
    r"\b([A-Z][\w\-\.]+(?: [A-Z][\w\-\.]+){0,2}) (raises|raised|secures|secured|closes|closed|"
    r"announces|announced|launches|launched|lands|receives|wins)\b"
)


def gate(c: Mapping[str, Any]) -> str | None:
    """None when the candidate may enter the Attention Queue, else a short reason."""
    name = (c.get("name") or "").strip()
    desc = (c.get("description") or "").strip()
    if not name or name.upper() == "UNKNOWN":
        return "company name UNKNOWN"
    try:
        if norm_company(name) in ("", "unknown"):
            return "company name unresolved"
    except Exception:
        pass
    if len(name) > 70 or len(name.split()) > 7:
        return "entity extraction low-quality (name looks like a headline)"
    if _ROUNDUP.search(name):
        return "roundup / recap / awards / multi-company article"
    if re.match(r"^\d+\s", name) or name.lower().startswith(("how ", "why ", "what ", "the ", "these ", "meet the ")):
        return "headline, not an entity"
    if c.get("noise"):
        return "flagged as noise by sourcing"
    if _PERSON.search(name) and not re.search(
        r"\b(gmbh|ag|inc|ltd|labs?|technolog|systems?|robotics|ai)\b", name, re.I
    ):
        return "person, not a venture"
    if desc and len(name) >= 4:
        nm = re.sub(r"[^a-z0-9]", "", name.lower())
        dn = re.sub(r"[^a-z0-9]", "", desc.lower())
        if nm[:12] not in dn:
            m = _VERB_SUBJECT.search(desc)
            if m and re.sub(r"[^a-z0-9]", "", m.group(1).lower())[:12] != nm[:12]:
                return "extracted entity does not match the company described (%s)" % m.group(1)  # noqa: UP031
    if (
        _ROUNDUP.search(desc[:120])
        and re.search(r"\b(startups|companies)\b", desc[:120], re.I)
        and len(name.split()) >= 3
    ):
        return "multi-company article"
    return None


# ------------------------------------------------------------------ score v2
_PRESEED = re.compile(r"\bpre-?seed\b", re.I)
_SEED_AMT = re.compile(
    r"\bseed\b[^.]{0,80}?(?:€|eur|\$|usd|chf|£)\s?(\d+(?:[.,]\d+)?)\s?(m|mn|mio|million)\b|"
    r"(?:€|eur|\$|usd|chf|£)\s?(\d+(?:[.,]\d+)?)\s?(m|mn|mio|million)\b[^.]{0,80}?\bseed\b",
    re.I,
)
_SERIES_A = re.compile(r"\bseries\s+[a-b]\b", re.I)
_MATURE = re.compile(
    r"\b(series\s+[c-z]|ipo|public company|listed on|acquired by|acquisition of|unicorn|"
    r"\d{3,}\s+employees|€\s?\d{3}\s?(m|million)|\$\s?\d{3}\s?(m|million)|growth round|late-stage)\b",
    re.I,
)
_GENERIC_SAAS = re.compile(
    r"\b(saas|crm|marketing automation|hr software|invoicing|project management tool|"
    r"all-in-one platform|productivity app|no-code website|social media tool)\b",
    re.I,
)
_TECH_DEPTH = re.compile(
    r"\b(proprietary|patent|sensor|hardware|model|algorithm|robot|photonic|quantum|"
    r"materials?|chip|semiconductor|physics|biolog|chem|reactor|battery|autonom)\w*",
    re.I,
)
_COHORT_NOW = re.compile(r"\b(cohort|batch)\b[^.]{0,40}\b(202[5-9])\b|\b(202[5-9])\b[^.]{0,40}\b(cohort|batch)\b", re.I)
_MANUAL_SRC = re.compile(
    r"\b(manual|relationship|referral|network|scout|personal|warm intro|conference|meetup)\b", re.I
)
_MATURE_PENALTY = ("Mature / later-stage", -20)


def score_v2(c: Mapping[str, Any], last_run: Any = None) -> tuple[int, Applied]:
    """Explainable attention score: (score, applied [(label, points)]).

    ``last_run`` is compared DIRECTLY with ``c["run_id"]`` (same type and format as the old inbox's ``last_run``).
    """
    text = joined(c, ("name", "description", "notes", "why", "founder_signal")).lower()
    tier = c.get("discovery_tier") or "announcement"
    th = themes.themes_for(c)
    applied: Applied = []

    # stage: exactly ONE of pre-company / grant / pre-seed (highest wins; no double counting)
    if tier == "pre_company":
        applied.append(("PRE-COMPANY", 20))
    elif tier == "grant":
        applied.append(("Technical grant / research project", 14))
    elif _PRESEED.search(text):
        applied.append(("Pre-seed", 12))

    # technical depth
    if themes.SPINOUT.search(text):
        applied.append(("Research spinout", 16))
    if themes.technical_founder_evidence(text):
        applied.append(("Technical founders", 10))

    # Project A fit: best single theme bonus only
    if "frontier" in th:
        applied.append(("Frontier", 10))
    elif "defence" in th:
        applied.append(("Defence", 8))
    elif "industrial_autonomy" in th or "physical_world" in th:
        applied.append(("Industrial Autonomy / Physical World", 6))

    # source quality
    src = str(c.get("source", "")) + " " + str(c.get("source_id", ""))
    if _MANUAL_SRC.search(src) or (c.get("src_quality") == 2 and tier != "announcement"):
        applied.append(("Non-obvious / proprietary source", 8))
    if c.get("bootstrap_source") or _COHORT_NOW.search(text):
        applied.append(("Latest cohort", 7))
    if last_run and c.get("run_id") == last_run:
        applied.append(("New this run", 5))

    # negatives: ONE stage penalty (most severe), announcement source, generic SaaS
    stage_pen: tuple[str, int] | None = None
    if _MATURE.search(text):
        stage_pen = _MATURE_PENALTY
    elif _SERIES_A.search(text):
        stage_pen = ("Series A or later", -16)
    elif m := _SEED_AMT.search(text):
        amt = float((m.group(1) or m.group(3)).replace(",", "."))
        if amt >= 8:
            stage_pen = ("Seed >= EUR 8m", -10)
    if stage_pen:
        applied.append(stage_pen)
    if tier == "announcement" and stage_pen != _MATURE_PENALTY:
        applied.append(("Announcement / funding-news source", -8))
    if _GENERIC_SAAS.search(text) and not (c.get("archetype_hits") or []) and not _TECH_DEPTH.search(text):
        applied.append(("Generic SaaS / weak technical signal", -8))
    return sum(p for _, p in applied), applied


def explain(applied: Applied) -> str:
    return " · ".join("%s %+d" % (label, points) for label, points in applied)  # noqa: UP031 - %+d is the format


def annotate(c: Mapping[str, Any], last_run: Any = None) -> dict[str, Any]:
    g = gate(c)
    sc, applied = score_v2(c, last_run)
    lens = themes.lens_signals(c)[0]
    return {"score": sc, "applied": applied, "explain": explain(applied), "gated": g, "lens": lens, "final": sc + lens}


# ------------------------------------------------------------------ differentiation (V3)
_TECH_SPEC = re.compile(
    r"\b(photonic\w*|quantum|neuromorphic|semiconductor\w*|chips?|lithography|lidar|radar|sensor\w*|"
    r"spectromet\w*|catalyst\w*|catalytic|electrolys\w*|battery (cells?|chemistry|anodes?|cathodes?)|"
    r"solid-state|stellarator|fusion|reactor|robot(?:ic)? (arms?|hands?|grippers?|platforms?)|actuators?|"
    r"exoskeleton|drones?|composites?|alloys?|graphene|nanoparticles?|bioprocess\w*|enzymes?|antibod\w+|"
    r"electrodes?|plasma|lasers?|optical|superconduct\w*|thermal (storage|management)|hydrogen|"
    r"additive manufacturing|3d.printed|machining|foundation models?|world models?|physics-(informed|based)|"
    r"proprietary (algorithms?|models?|datasets?|sensors?|process(es)?)|slam|inference engine|"
    r"printed electrodes|neural interface|iron-air|mesh network\w*|key management|welding|compute)\b",
    re.I,
)
_AUDIENCE = re.compile(
    r"\b(customers?|clients?|operators?|manufacturers?|insurers?|fleets?|utilities|hospitals?|farmers?|"
    r"vineyards?|oems?|suppliers?|retailers?|logistics|airlines?|carriers?|shippers?|forwarders?|banks?|"
    r"brokers?|smes?|enterprises?|factories|plants?|grid operators?|reinsurers?|municipalities|"
    r"defen[cs]e|armed forces|agencies|contractors?|industry|industrial)\b",
    re.I,
)
_USE = re.compile(
    r"\b(for|serving|helps?|enabl\w+|used by|automates?|reduces?|cuts?|saves?|replaces?|detects?|monitors?|"
    r"predicts?|orchestrates?|manages?|pilots? with|paying|contracts?|revenue|use case|problem|market)\b",
    re.I,
)
_PRODUCT = re.compile(
    r"\b(product|customers?|market|commercial\w*|pilot|launch\w*|sell\w*|pricing|revenue|clients?|"
    r"operators?|manufacturers?|insurers?|fleets?|utilities|use case)\b",
    re.I,
)
_WHY_NOW = re.compile(
    r"\b(regulat\w+ (change|requir\w+|mandate)|new (regulation|law|directive|standard)|eu (ai act|csrd|taxonomy|"
    r"directive)|mandat\w+|deadline 20\d\d|cost of \w+ (fell|dropped|halved)|now possible|recent (advances?|"
    r"breakthrough)|electrification|energy transition|reshoring|sovereignty|supply.chain (shift|crisis)|"
    r"grid (congestion|constraints)|labou?r shortage|skills shortage|nis2|dora|csrd|ai act|post-quantum|"
    r"fleet electrification|decarboni[sz]ation)\b",
    re.I,
)
_PLATFORM = re.compile(
    r"\b(platform|across (industries|sectors|markets|fleets|insurers|operators)|multiple (customers|industries|"
    r"applications|markets)|any (fleet|factory|insurer|operator|utility)|horizontal|api|marketplace|modular|"
    r"general-purpose|reusable|stack|infrastructure)\b",
    re.I,
)
_NARROW = re.compile(
    r"\b(for one|single (site|plant|customer|hospital|vineyard|client)|bespoke|custom-built|one-off|"
    r"specific to|only for|tailored to (the|a) \w+ (plant|site|facility)|in-house tool)\b",
    re.I,
)
_WEAK_FIT = re.compile(
    r"\b(biotech\w*|medtech|therapeut\w+|drugs?|clinical|patients?|assistive|wearable (for|health)|"
    r"consumer app|d2c|b2c|lifestyle|wellness|fitness app|dating|gaming|food delivery|cosmetics?)\b",
    re.I,
)


def differentiation(c: Mapping[str, Any]) -> tuple[int, Applied]:
    """Evidence-only differentiation from EXISTING candidate text. Missing evidence = 0, never guessed."""
    text = joined(c, ("name", "description", "notes", "why", "founder_signal", "why_found"))
    low = text.lower()
    hits = [h for h in (c.get("archetype_hits") or []) if isinstance(h, int)]
    applied: Applied = []
    if _TECH_SPEC.search(low):
        applied.append(("Technical specificity", 12))
    commercial = bool(_AUDIENCE.search(low) and _USE.search(low))
    if commercial:
        applied.append(("Industrial / commercial application", 10))
    th = themes.themes_for(c)
    depth = False
    if th:
        if hits and any(h in themes.ARCHETYPE_THEMES for h in hits):
            depth = True  # the strict sourcing matcher already anchored the theme
        else:
            depth = any(len(re.findall(themes.THEME_KW[tk], low, re.I)) >= 2 for tk in th)
    if depth:
        applied.append(("Project A theme depth", 10))
    if themes.technical_founder_evidence(text):
        applied.append(("Technical founder evidence", 8))
    if _WHY_NOW.search(low):
        applied.append(("Structural why-now", 8))
    if _PLATFORM.search(low) or (re.search(r"\b(across|multiple)\b", low) and _AUDIENCE.search(low)):
        applied.append(("Platform / scale potential", 6))
    academic_ctx = bool(
        themes.SPINOUT.search(low) or (c.get("discovery_tier") == "grant") or re.search(r"\b(research|grant)\b", low)
    )
    if academic_ctx and not commercial and not _PRODUCT.search(low):
        applied.append(("Academic / no commercial path visible", -10))
    if _NARROW.search(low):
        applied.append(("Narrow / bespoke application", -8))
    if _WEAK_FIT.search(low) and 15 not in hits and 14 not in hits:
        applied.append(("Weak core-fund fit", -8))
    return sum(p for _, p in applied), applied


def annotate_v3(c: Mapping[str, Any], last_run: Any = None) -> dict[str, Any]:
    base = annotate(c, last_run)
    ds, dap = differentiation(c)
    base.update(
        {"diff": ds, "diff_applied": dap, "diff_explain": explain(dap), "final": base["score"] + base["lens"] + ds}
    )
    return base


# ------------------------------------------------------------------ venture entity qualification (V3.1)
_LEGAL_SUFFIX = re.compile(
    r"(?:^|\s|,)(ltd\.?|limited|gmbh|ag|sas|s\.a\.s\.|sa|s\.a\.|sarl|srl|s\.r\.l\.|bv|b\.v\.|nv|n\.v\.|ab|oy|aps|"
    r"as|a/s|inc\.?|corp\.?|corporation|llc|plc|ug|kgaa|gmbh & co\. kg|se|s\.p\.a\.|spa|lda|sp\. z o\.o\.|d\.o\.o\.)(?:$|\s|,|\))",
    re.I,
)
_ORG_NAME = re.compile(
    r"\b(universit(y|ies|ät|é|eit)|hochschule|institute?s?|institut|society|association|associations|alliance|"
    r"federation|charity|foundation|stiftung|ngo|ministry|ministerium|agency|agentur|authority|council|"
    r"commission|department|faculty|fakultät|consortium|konsortium|trade body|verband|verein|e\.\s?v\.|"
    r"chamber of commerce|government|public body|programme|program|initiative|network|cluster|hub|"
    r"centre for|center for|laboratory|laboratories|observatory|academy|school of|college)\b",
    re.I,
)
_ORG_DESC = re.compile(
    r"\b(is an? (non-?profit|registered charity|trade association|research institute|public (body|agency)|"
    r"industry (association|alliance)|consortium|government (body|agency)|membership (body|organi[sz]ation)|"
    r"grant administrator|funding (body|agency)|academic department|network of))\b",
    re.I,
)
_VENTURE_TXT = re.compile(
    r"\b(start-?ups?|scale-?ups?|company|commercial spin-?(?:off|out)|incorporated|founded in (19|20)\d\d|"
    r"raises?|raised|seed round|pre-seed round|series [a-c]|venture-backed|our customers|revenue|"
    r"paying customers|headquartered|hq in|unicorn)\b",
    re.I,
)
_PRECO_TXT = re.compile(
    r"\b(start-?ups? in creation|pre-?company|spin-?(?:off|out) project|founding team|pre-?incorporation|"
    r"to be incorporated|project leaders?|venture (project|team)|batch (i|ii|iii|iv|v|20\d\d)|field study|"
    r"enterprise batch|startup project|company in formation)\b",
    re.I,
)
_POSSIBLE_TXT = re.compile(
    r"\b(team|product|platform|technology|builds?|develops?|offers?|customers?|clients?|market|"
    r"prototype|pilot|solution|founders?)\b",
    re.I,
)
_EXPLICIT_COMPANY = re.compile(
    r"\b(start-?ups?|company|commercial spin-?(?:off|out)|incorporated|founded in (19|20)\d\d|raises?|raised|"
    r"seed round|pre-seed round|series [a-c]|venture-backed)\b",
    re.I,
)

ENTITY_LABELS = {
    "VENTURE": "VENTURE",
    "PRE_COMPANY_PROJECT": "PRE-COMPANY PROJECT",
    "POSSIBLE_VENTURE": "POSSIBLE VENTURE",
    "UNKNOWN_ENTITY_TYPE": "UNKNOWN ENTITY TYPE",
    "NON_VENTURE": "NON-VENTURE",
}
ENTITY_PENALTY = {
    "VENTURE": 0,
    "PRE_COMPANY_PROJECT": 0,
    "POSSIBLE_VENTURE": -8,
    "UNKNOWN_ENTITY_TYPE": -12,
    "NON_VENTURE": 0,
}


def entity_type(c: Mapping[str, Any]) -> tuple[str, str]:
    """Conservative venture-entity qualification from EXISTING text only: (type, reason). Early or unincorporated
    never means NON_VENTURE."""
    name = str(c.get("name") or "")
    desc = str(c.get("description") or "")
    src = str(c.get("source") or "") + " " + str(c.get("source_id") or "")
    text = " ".join((desc, spaced_list(c.get("why"))))
    if _LEGAL_SUFFIX.search(name):
        return "VENTURE", "legal form in name"
    org = _ORG_NAME.search(name)
    if org and not _VENTURE_TXT.search(text):
        return "NON_VENTURE", "organisation-type name (%s)" % org.group(1).lower()  # noqa: UP031
    if _ORG_DESC.search(text):
        return "NON_VENTURE", "described as an organisation, not a venture"
    if org and _VENTURE_TXT.search(text):
        return "POSSIBLE_VENTURE", "organisation-type name but company/startup wording in text"
    strong_pre = bool(
        c.get("discovery_tier") == "pre_company"
        or _PRECO_TXT.search(text + " " + src)
        or re.search(r"start-?ups? in creation|pre-?company|spin-?off projects?|enterprise - batch", src, re.I)
    )
    weak_pre = bool(
        re.search(r"\bspin-?(?:off|out)\b", text, re.I)
        and re.search(r"\b(universit\w+|tu \w+|eth|epfl|institute|founders?|founding|team|researchers?)\b", text, re.I)
    )
    if _EXPLICIT_COMPANY.search(text) and not strong_pre:
        return "VENTURE", "explicit company/startup evidence"
    if strong_pre or weak_pre:
        return "PRE_COMPANY_PROJECT", "official pre-company / spinout-project context"
    if _VENTURE_TXT.search(text):
        return "VENTURE", "explicit company/startup evidence"
    if _POSSIBLE_TXT.search(text):
        return "POSSIBLE_VENTURE", "product/team wording without company or project proof"
    return "UNKNOWN_ENTITY_TYPE", "no entity-type evidence in text"


def entity_info(c: Mapping[str, Any]) -> dict[str, Any]:
    et, why = entity_type(c)
    pen = ENTITY_PENALTY[et]
    label = (
        "Entity: "
        + ENTITY_LABELS[et]
        + ((" %d" % pen) if pen else "")  # noqa: UP031
        + (" — excluded from Attention Queue" if et == "NON_VENTURE" else "")
    )
    return {"type": et, "label": label, "penalty": pen, "reason": why}


def annotate_v31(c: Mapping[str, Any], last_run: Any = None) -> dict[str, Any]:
    """The full annotation the Deal Flow view uses (``attention_v2`` in the old API)."""
    base = annotate_v3(c, last_run)
    e = entity_info(c)
    base["entity"] = e
    if e["type"] == "NON_VENTURE" and not base.get("gated"):
        base["gated"] = "non-venture entity: " + e["reason"]
    base["final"] = base["score"] + base["lens"] + base["diff"] + e["penalty"]
    return base
