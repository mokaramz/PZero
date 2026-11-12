# ruff: noqa: E501, RUF001
# (protected gold-master data, copied by script from the old modules; see the header)
"""The Founder Radar catalog (review 026a): constants cut MECHANICALLY from the old ``domain/founder_radar/*.py`` at
revision 6c739b9 by exact top-level line ranges (``scripts/gen_founder_radar_catalog.py``); nothing is retyped.
``tests/founder_radar/test_founder_radar_port.py`` checks every cut against the old modules. Pure data.

``constants.py``: the states, buckets, decision fields and ``_theme_terms`` (the one function cut; it returns a SORTED
list, decision b). ``names.py``: the placeholder / role / organisation / heading patterns and word sets.
``records.py`` ``_HUMAN_KEYS``; ``identity.py`` the founded-by patterns; ``companies.py`` ``_NON_OFFICIAL``;
``leads.py`` ``HUMAN`` / ``UNKNOWN_LABELS``; ``sources.py`` ``BATCH_SIZE`` / ``LEGACY_GITHUB_IDS`` / ``SOURCE_ROLE``
(the region and source defaults are ``ecosystems.catalog``'s, re-exported here); ``extraction.py`` its patterns and
tables; ``collectors.py``, ``fetch.py`` and ``research.py`` the constants review 026b will use; ``store.py`` the
document names.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from projectzero.conviction import taste
from projectzero.ecosystems.catalog import DEFAULT_REGIONS as DEFAULT_REGIONS
from projectzero.ecosystems.catalog import RADAR_DEFAULT_SOURCES as DEFAULT_SOURCES
from projectzero.ecosystems.catalog import SOURCES_SCHEMA as SOURCES_SCHEMA

__all__ = ["DEFAULT_REGIONS", "DEFAULT_SOURCES", "SOURCES_SCHEMA"]

# fmt: off
# ── from domain/founder_radar/constants.py ──
STATES = [
    "detected",
    "needs identity resolution",
    "watchlisted",
    "researching",
    "introduction path identified",
    "introduction requested",
    "contacted",
    "replied",
    "first meeting completed",
    "active relationship",
    "trusted relationship",
    "opportunity introduced",
    "dormant",
    "dismissed",
]
NETWORK_STATES = STATES[4:12]
NEI = "NOT ENOUGH INFORMATION"
RADAR_FIELDS = [
    "aliases",
    "identity_status",
    "identity_evidence",
    "former_roles",
    "founder_status",
    "country",
    "institutions",
    "profile_urls",
    "github_id",
    "openalex_id",
    "orcid",
    "patent_inventor_id",
    "companies",
    "events",
    "ecosystems",
    "sources",
    "evidence",
    "signal_categories",
    "evidence_confidence",
    "last_signal",
    "radar_state",
    "state_history",
    "intro_route",
    "relationship_owner",
    "contact_channel",
    "machine_research",
    "human_judgment",
    "boardy",
    "opportunities",
    "updated",
    "why_surfaced",
    "signal",
    "dismissed_reason",
]
def _theme_terms() -> list[str]:
    terms: set[str] = set()
    for a in taste.ARCHETYPES:
        kws = (
            a[3]
            if len(a) > 3 and isinstance(a[3], (list, tuple))
            else (a[2] if isinstance(a[2], (list, tuple)) else [])
        )
        terms |= {str(k).lower() for k in kws if len(str(k)) > 3}
    terms |= {
        "robotics",
        "industrial",
        "defence",
        "defense",
        "resilience",
        "energy",
        "climate",
        "infrastructure",
        "developer tools",
        "devtools",
        "applied ai",
        "machine learning",
        "llm",
        "enterprise software",
    }
    return sorted(terms)  # decision b (review 026a): one order in every process


_FOUNDER_CLAIM = re.compile(
    r"\b(founder|co-?founder|cofounder|founding|building (a|an|the|something)|stealth|spin-?off|spin-?out|incorporat|accelerator|venture (lab|builder|studio)|cohort)\b",
    re.I,
)  # CEO/CTO/COO alone never qualify
BUCKETS = [
    "Gold now",
    "Strong investigation",
    "Founder claim — unverified",
    "Research & spinout talent",
    "Insufficient evidence / out of scope",
]
QUEUE_LABELS: dict[str, str] = {"claim": "Founder claim — unverified", "qualifying": "Founder verified — company facts incomplete"}
EARLY_STAGES = (
    "pre_seed",
    "pre-seed",
    "preseed",
    "seed",
    "pre-company",
    "pre_company",
    "stealth",
    "angel",
    "idea",
    "incorporating",
)
DECISION_FIELDS = (
    "founded",
    "status",
    "stage",
    "funding",
    "project_a_fit",
    "recent_activity",
    "early_stage_signal",
    "official_domain",
)
# ── from domain/founder_radar/names.py ──
_PLACEHOLDER = re.compile(
    r"\b(tbd|tba|n/?a|unknown|unnamed|undisclosed|anonymous|core team|team of \d+|names? via|founders?|co-?founders?|ceo|cto|coo|cfo|team|management|the team|not named|see (impressum|website)|impressum|people|leadership|board|advisors?|meet|our|the)\b",
    re.I,
)
_ROLE_ONLY = re.compile(
    r"^(dr\.?|prof\.?|mr\.?|ms\.?)?\s*(founder|co-?founder|ceo|cto|coo|cfo|chair|director|partner|engineer|scientist|researcher|team)s?\.?$",
    re.I,
)
_ORG_WORDS = re.compile(
    r"\b(fraunhofer|institut\w*|institute|university|universit\w+|hochschule|laborator\w+|labs?|gmbh|ag|inc|ltd|llc|sarl|bv|kg|se|plc|research|center|centre|group|team|department|faculty|foundation|stiftung|association|verein|company|corp\w*|technolog\w+|systems|solutions|ventures|capital|partners|studio|network|agency|federal|ministry|ipa|kit|eth|mit|dlr)\b",
    re.I,
)
_HEADING_WORDS: set[str] = {
    "about",
    "team",
    "contact",
    "meet",
    "our",
    "the",
    "careers",
    "career",
    "jobs",
    "imprint",
    "impressum",
    "news",
    "home",
    "people",
    "login",
    "log",
    "sign",
    "blog",
    "press",
    "menu",
    "products",
    "product",
    "services",
    "solutions",
    "faq",
    "faqs",
    "privacy",
    "terms",
    "cookies",
    "legal",
    "support",
    "pricing",
    "partners",
    "customers",
    "company",
    "leadership",
    "management",
    "investors",
    "media",
    "resources",
    "docs",
    "documentation",
    "download",
    "downloads",
    "subscribe",
    "newsletter",
    "search",
    "back",
    "next",
    "read",
    "learn",
    "more",
    "call",
    "email",
    "phone",
    "welcome",
    "hello",
    "über",
    "uns",
    "kontakt",
    "karriere",
    "presse",
    "datenschutz",
    "startseite",
    "mehr",
    "unser",
    "unsere",
}
_HEADING_FIRST: set[str] = {
    "about",
    "contact",
    "kontakt",
    "über",
    "welcome",
    "hello",
    "our",
    "the",
    "unser",
    "unsere",
    "read",
    "learn",
    "call",
    "email",
    "phone",
    "back",
    "next",
    "sign",
    "log",
    "login",
    "search",
    "subscribe",
    "download",
    "home",
    "menu",
    "startseite",
    "mehr",
}
_NAME_NOISE: set[str] = {
    "call",
    "about",
    "contact",
    "meet",
    "founder",
    "founders",
    "co-founder",
    "cofounder",
    "ceo",
    "cto",
    "coo",
    "team",
    "our",
    "the",
    "people",
    "leadership",
    "dr",
    "dr.",
    "prof",
    "prof.",
    "mr",
    "ms",
    "email",
    "phone",
    "linkedin",
    "twitter",
}
# ── from domain/founder_radar/records.py ──
_HUMAN_KEYS = (
    "notes",
    "human_judgment",
    "next_action",
    "next_action_date",
    "last_interaction",
    "intro_route",
    "introduced_by",
    "introduced_by_name",
    "contact_channel",
    "machine_research",
)
# ── from domain/founder_radar/identity.py ──
_FOUNDED_STOP = re.compile(
    r"\s+(?:in|at|to|who|after|with|as|from|for|on|today|now|which|that|including|together|alongside|while|when|where|during|since|before|based|located)\b|[.;:!?()\[\]—–]|\s-\s"
)
_FOUNDED_BY_ROUTES = [
    r"(?P<co>\w[\w'’&.\-]*(?: \w[\w'’&.\-]*){0,3}?)(?:,)? (?:was |were |is |are |has been |had been )?(?:co-?)?founded(?: in \d{4})?(?: in [\w\- ]{1,30}?)? by (?P<names>.{2,200})",  # "5U AI was founded in 2025 by A and B"
    r"(?P<names>.{2,200}?) (?:co-?)?founded (?P<co>\w[\w'’&.\-]*(?: \w[\w'’&.\-]*){0,3})",  # "A and B founded 5U AI"
    r"(?:^|[.;:!?]\s+)(?:co-?)?founded by (?P<names>.{2,200})",  # "Founded by A and B" (company = official-domain context)
]
# ── from domain/founder_radar/companies.py ──
_NON_OFFICIAL = (
    "github.com",
    "openalex.org",
    "orcid.org",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "medium.com",
    "substack.com",
    "google.",
    "youtube.com",
    "lu.ma",
    "meetup.com",
    "devpost.com",
    "example.org",
)
# ── from domain/founder_radar/leads.py ──
HUMAN: dict[str, Callable[[Any], str]] = {
    "founded": lambda v: f"Founded in {v}",
    "early_stage_signal": lambda v: "Early-stage company (current early-stage wording on the official site)",
    "funding": lambda v: f"Funding: {v}",
    "recent_activity": lambda v: f"Recent activity: {v}",
    "status": lambda v: "Company is operating (explicit current wording)",
    "stage": lambda v: f"Stage: {v}",
}
UNKNOWN_LABELS: dict[str, str] = {
    "founder evidence": "Founder role not yet sourced",
    "identity resolved": "Identity still unresolved",
    "founded / early stage": "Founding date / stage not sourced",
    "active status": "Active status not sourced",
    "recent activity": "No dated recent activity",
    "Project A fit": "Project A fit not assessed",
    "access route": "No contact route found",
}
# ── from domain/founder_radar/sources.py ──
BATCH_SIZE = 6  # GitHub user searches per scan (unauthenticated limit: 10 searches/min, 60 requests/h)
LEGACY_GITHUB_IDS = {"gh-munich", "gh-zurich", "gh-karlsruhe", "gh-berlin", "gh-paris"}
SOURCE_ROLE: dict[str, str] = {
    "github_users": "live discovery — builder evidence (not founder proof)",
    "openalex_works": "live discovery — researcher/inventor evidence (not founder proof)",
    "pz_data": "live discovery — Project Zero pipeline claims (unverified until resolved)",
    "apollo": "enrichment — contact data only, never quality evidence",
    "epo": "researcher/inventor evidence — configuration required",
    "orcid": "researcher/inventor evidence — configuration required",
    "harmonic": "optional licensed discovery",
    "dealroom": "optional licensed discovery",
    "crunchbase": "optional licensed discovery",
    "linkedin": "MANUAL / AUTHORIZED — never scanned automatically",
    "boardy": "manual introduction channel",
}
# ── from domain/founder_radar/extraction.py ──
_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_TEMPLATE_WORDS: set[str] = {
    "home",
    "about",
    "team",
    "careers",
    "contact",
    "news",
    "press",
    "blog",
    "products",
    "solutions",
    "login",
    "sign",
    "menu",
    "privacy",
    "imprint",
    "impressum",
    "cookies",
    "terms",
    "call",
    "meet",
    "learn",
    "more",
    "read",
}
_DATE = re.compile(
    r"(?P<iso>(19|20)\d{2}-\d{2}-\d{2})|(?P<d>\d{1,2})?\s*(?P<mon>" + _MONTHS + r")\s+(?P<y>(19|20)\d{2})", re.I
)
_FOUNDED = re.compile(r"(founded|established|started|launched|since|gegründet)\s*(in\s*)?(?P<y>(19|20)\d{2})", re.I)
_FUNDING = re.compile(
    r"(raised|secured|closed|announc\w+)\s+(a|an|its|our)?\s*(?P<amt>[€$£]?\s?\d+(?:[.,]\d+)?\s?(?:m|million|k|bn|billion)?)?\s*(?P<round>pre-?seed|seed|series [a-c]|angel|grant)",
    re.I,
)
_EARLY = re.compile(
    r"\b(pre-?seed|seed round|spin-?(off|out)|newly founded|just launched|stealth|incorporated in (19|20)\d{2}|founded in 202[4-9])\b",
    re.I,
)
_HIRING = re.compile(r"\b(we'?re hiring|we are hiring|open (roles|positions)|join (our|the) team|now hiring)\b", re.I)
_ACTIVE = re.compile(
    r"\b(currently (operating|building|shipping|serving)|in operation|is operating|live in production|now (operating|live))\b",
    re.I,
)
_OPERATING = re.compile(
    r"\b(our customers|serving customers|customers (include|such as)|deployed (at|with)|working with (customers|partners))\b",
    re.I,
)
_NAME = r"(?P<name>[^\W\d_][\w'’\-]+(?: [^\W\d_][\w'’\-]+){1,3})"  # any-script letters; uppercase enforced in the token filter
_ROLE = r"(?P<role>(?i:(?:co-?founder|founder|founding (?:engineer|team))(?:\s*(?:&|and|,)\s*(?:ceo|cto|coo))?|(?:ceo|cto|coo)\s*(?:&|and|,)\s*co-?founder))"
_FOUNDER_LINE = re.compile(_NAME + r"\s*[,:–\-—|(]?\s*" + _ROLE)  # "Name, Co-Founder & CEO"
_FOUNDER_LINE2 = re.compile(_ROLE + r"\s+(?:of\s+)?" + _NAME)  # "co-founder Name"
_FOUNDED_BY = re.compile(
    r"\b(?:founded|co-?founded|established|started)(?:\s+in\s+(?:19|20)\d{2})?\s+by\s+(?P<names>[^.;:!?]{4,160})", re.I
)  # "Founded in 2025 by A and B"
_NAMES_FOUNDED = re.compile(
    r"(?P<names>(?:[^\W\d_][\w'’\-]+(?: [^\W\d_][\w'’\-]+){1,3})(?:\s*(?:,|and|&|und)\s*(?:[^\W\d_][\w'’\-]+(?: [^\W\d_][\w'’\-]+){1,3}))*)\s+(?:co-?)?founded\s+(?P<co>\w[\w'’\-]*(?: \w[\w'’\-]*){0,3})",
    re.I,
)  # "A and B founded Company" (company may start with a digit: 5U AI)
_LI_PROFILE = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/([A-Za-z0-9_%\-]+)/?", re.I)
_GH_ORG = re.compile(r"https?://github\.com/([A-Za-z0-9_.\-]+)/?(?![\w/])")
MACHINE_INFERENCE_FIELDS = ("project_a_fit", "hiring_signal", "operating_signal", "official_domain")
WHY_EXTRA: dict[str, str] = {"linkedin_profile": "contact route: canonical profile found on a permitted public source"}
WHY: dict[str, str] = {
    "founded": "timing gate: a sourced founding date within 3 years is early-stage evidence",
    "status": "active-company gate: sourced explicit active status",
    "stage": "timing gate: sourced early stage",
    "funding": "stage/funding evidence (queue context)",
    "early_stage_signal": "timing gate: sourced current early-stage signal",
    "recent_activity": "recency gate: dated activity within 90 days",
    "project_a_fit": "fit gate: sourced company-specific Project A fit (HIGH/MEDIUM)",
    "official_domain": "confirms the canonical official domain used for research",
    "access_route": "Gold gate: cold company access route",
    "founder": "identity: individual pairing + confirmation required",
    "hiring_signal": "context only — never decision-bearing",
    "operating_signal": "context only — customer wording never establishes active status",
    "linkedin_profile": "contact route: canonical profile found on a permitted public source (LinkedIn itself is never scraped)",
}
# ── from domain/founder_radar/collectors.py ──
_ENTRE = re.compile(
    r"\b(founder|co-?founder|cofounder|founding|ceo|cto|building (a|an|the)|stealth|start-?up|startup|venture|incorporat|spin-?off|spin-?out|yc |y combinator|accelerator|entrepreneur)\b",
    re.I,
)
_TRANSITION = re.compile(
    r"\b(building|working on something new|new project|left|formerly|previously|ex-|open to|stealth|starting|launching|next chapter)\b",
    re.I,
)
# ── from domain/founder_radar/fetch.py ──
MAX_BODY = 400000
MAX_REDIRECTS = 3
LINK_PRIORITY = (
    "about",
    "team",
    "people",
    "founders",
    "leadership",
    "company",
    "news",
    "press",
    "blog",
    "insights",
    "careers",
    "contact",
)
# ── from domain/founder_radar/research.py ──
CRAWL_PATHS = (
    "",
    "/about",
    "/team",
    "/people",
    "/founders",
    "/leadership",
    "/company",
    "/news",
    "/press",
    "/blog",
    "/about-us",
)
MAX_PAGES = 9  # homepage + at most 8 same-domain pages (+1 GitHub-org page)
# ── from domain/founder_radar/store.py ──
SOURCES = "radar_sources.json"
HEALTH = "radar_health.json"
METRICS = "radar_metrics.json"
REGIONS = "radar_regions.json"
CURSOR = "radar_cursor.json"
MIGRATION = "radar_migration.json"
COMPANIES = "radar_companies.json"
RESEARCH = "radar_research.json"
RESEARCH_QUEUE = "radar_research_queue.json"
# fmt: on
