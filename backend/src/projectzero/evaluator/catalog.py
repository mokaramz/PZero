# ruff: noqa: E501
# (protected gold-master data, copied by script from the old module; see the header)
"""The Active Evaluator catalog (review 024): constants cut MECHANICALLY from the old ``domain/evaluator.py`` at
revision 6c739b9 by exact top-level line ranges (``scripts/gen_evaluator_catalog.py``); nothing is retyped.
``tests/evaluator/test_evaluator_port.py`` checks every cut against the old module. Pure data.

``FILE_NAME``, ``STATES``, the labels (``DECK_LABEL``, ``FOUNDER_LABEL``, ``UNKNOWN``), the rubric ``FAMILIES``
``(id, label, rubric dimension, base priority, opening question, verification hint)`` and ``FAM`` (by id), the
family keyword rules ``_FAM_WORDS``, the patterns ``_NUM`` / ``_MATERIAL`` / ``_COUNT_RX`` / ``_NEG_RX`` (with
``_WORDNUM`` and ``_COUNT_NOUNS``) and ``CANONICAL_MAP`` (rubric families -> the six first-call sections).
"""

from __future__ import annotations

import re

# fmt: off
FILE_NAME = "evaluations.json"
STATES = ["DECK CLAIM", "FOUNDER-REPORTED", "PUBLIC SOURCED FACT", "OPERATOR VERIFIED", "CONTRADICTION", "UNKNOWN"]
DECK_LABEL = "DECK CLAIM — UNVERIFIED"
FOUNDER_LABEL = "FOUNDER-REPORTED — unverified"
UNKNOWN = "UNKNOWN"
FAMILIES = [
    (
        "founder_team",
        "Founder / team",
        "founder",
        10,
        "Walk me through the founding team: who does what, what has each of you built before, and how long have you worked together?",
        "LinkedIn is a contact route; verify via official team page, prior-company press, GitHub, publications",
    ),
    (
        "problem",
        "Problem severity",
        "insight",
        8,
        "Whose problem is this, how severe is it today, and what does it cost them when it goes wrong?",
        "customer reference or public case",
    ),
    (
        "customer_budget",
        "Customer & budget owner",
        "venture_scale",
        8,
        "Who is the buyer, who owns the budget, and who can say no?",
        "named customer / budget owner reference",
    ),
    (
        "product",
        "Product today vs roadmap",
        "insight",
        7,
        "What does the product do today — in production, not on the roadmap — and what is roadmap?",
        "demo, docs, public release notes",
    ),
    (
        "traction",
        "Traction",
        "insight",
        9,
        "What traction is real today — paying customers, pilots, LOIs — with numbers and dates?",
        "contracts, invoices, customer confirmation",
    ),
    (
        "retention",
        "Retention",
        "insight",
        6,
        "What do customers do after the first 90 days — retention, usage, renewals?",
        "cohort data, renewal contracts",
    ),
    (
        "growth",
        "Growth quality",
        "venture_scale",
        6,
        "How did the last three months of growth happen — inbound, outbound, referrals — and what did it cost?",
        "pipeline / CRM export, spend",
    ),
    (
        "market",
        "Market / bottom-up sizing",
        "venture_scale",
        8,
        "Bottom-up: how many buyers like your first customers exist, at what price — what is the wedge and how does it grow into a platform?",
        "bottom-up count from public registers / industry data",
    ),
    (
        "competition",
        "Competition / status quo",
        "taste",
        7,
        "What do customers use today instead of you, and who else is building this?",
        "Project Zero portfolio twins, public competitor list",
    ),
    (
        "moat",
        "Moat / defensibility",
        "venture_scale",
        6,
        "What becomes harder for a competitor every month you operate — data, distribution, regulation, switching costs?",
        "patents (granted vs filed), exclusive contracts",
    ),
    (
        "economics",
        "Economics",
        "insight",
        6,
        "Unit economics: price, gross margin, cost to serve, payback?",
        "P&L extract, pricing page",
    ),
    (
        "sales_cycle",
        "Sales cycle / ACV / conversion",
        "insight",
        5,
        "Sales cycle length, ACV, and conversion from first contact to signed?",
        "CRM export, signed contracts",
    ),
    (
        "fundraising",
        "Fundraising / runway / round timing",
        "why_now",
        9,
        "Runway, what you are raising, when, who is leading, and what is already committed?",
        "term sheet / cap table / registry filing",
    ),
    (
        "why_now",
        "Why now",
        "why_now",
        8,
        "Why does this have to exist now — what changed (regulation, capability, cost curve) and when?",
        "dated public trigger (regulation text, benchmark, price data)",
    ),
    (
        "risks",
        "Risks",
        "insight",
        5,
        "What would make this fail — and what is the single unknown you most need to resolve?",
        "—",
    ),
    (
        "project_a_fit",
        "Project A fit / platform leverage",
        "taste",
        5,
        "Where does Project A's platform help you concretely — which portfolio companies or theses?",
        "theme mapping (Taste Map)",
    ),
    (
        "conflict",
        "Conflict",
        "taste",
        6,
        "Which Project A portfolio companies or adjacent funds are closest to you — any overlaps?",
        "Omar / Project A confirmation",
    ),
    (
        "evidence_gaps",
        "Evidence gaps",
        "",
        4,
        "Which of today's claims can you evidence in writing — and what will you send after the call?",
        "documents received",
    ),
]
FAM = {f[0]: f for f in FAMILIES}
_FAM_WORDS = {
    "founder_team": r"founder|co-?founder|cto|ceo|team|hired|phd|ex-|previously|background|worked at",
    "traction": r"arr|mrr|revenue|customers?|paying|pilots?|lois?|contracts?|signed|users|bookings|gmv",
    "retention": r"retention|churn|renew|nrr|usage|active",
    "growth": r"growth|grew|mom|yoy|month-over-month|\d+\s?%",
    "market": r"market|tam|sam|som|bottom-?up|billion|€\s?\d+\s?bn|addressable",
    "competition": r"competitor|competition|incumbent|alternative|status quo|nobody else",
    "moat": r"moat|defensib|patent|proprietary|exclusive|switching|network effect|data advantage",
    "economics": r"margin|cac|ltv|payback|unit economics|gross|pricing|price",
    "sales_cycle": r"sales cycle|acv|conversion|close rate|procurement",
    "fundraising": r"rais(e|ing)|round|seed|series|runway|investors?|valuation|term sheet",
    "why_now": r"why now|regulation|directive|act\b|mandate|deadline|cost curve|breakthrough|since 20\d\d",
    "product": r"product|platform|feature|roadmap|beta|launch|ship|release|api",
    "problem": r"problem|pain|costs? them|manual|waste|downtime|error",
    "risks": r"risk|fail|dependency|single point",
    "project_a_fit": r"project a|portfolio",
    "conflict": r"overlap|conflict",
    "customer_budget": r"buyer|budget|decision maker|procurement|cfo|cio|head of",
}
_NUM = re.compile(r"(?P<cur>€|\$|£|eur|usd|chf)?\s?(?P<n>\d[\d.,]*)\s?(?P<mag>k|m|mio|mn|million|bn|b)?\b", re.I)
_MATERIAL = re.compile(
    r"\d|arr|mrr|revenue|customer|pilot|patent|raised|round|team|founder|growth|retention|churn|margin|contract|loi|market|competit|hired|launch|users",
    re.I,
)
_WORDNUM: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "hundred": 100,
}
_COUNT_NOUNS = [
    ("paying customers", r"(?:paying|paid|commercial)\s+(?:customers?|clients?|accounts?|logos?)"),
    ("pilots", r"(?:active\s+|evaluation\s+|unpaid\s+|paid\s+|running\s+)?pilots?(?:\s+customers?)?"),
    ("customers", r"customers?|clients?|logos?"),
    ("LOIs", r"lois?|letters? of intent"),
    ("signed contracts", r"(?:signed\s+)?contracts?"),
    ("users", r"(?:active\s+|monthly\s+|daily\s+|paying\s+)?users"),
    ("employees", r"employees|fte|ftes|people|staff|engineers|team members"),
    ("patents", r"patents?(?:\s+(?:granted|filed))?"),
    ("countries", r"countries|markets"),
    ("hospitals", r"hospitals|clinics|sites|plants|factories"),
]
_COUNT_RX = re.compile(
    r"(?<![\d.,€$£])(?P<n>\d{1,6}|"
    + "|".join(_WORDNUM)
    + r")\s+(?P<noun>"
    + "|".join(f"(?:{rx})" for _, rx in _COUNT_NOUNS)
    + r")\b",
    re.I,
)
_NEG_RX = re.compile(
    r"(?:\bnot|n't|\bno longer|\brather than|\binstead of|\bnever|\bwithout|\bnor)\s*(?:\w+\s+){0,2}$", re.I
)
CANONICAL_MAP: dict[str, list[str]] = {
    "why": ["why_now", "problem"],
    "who": ["customer_budget", "problem"],
    "built": ["product", "moat"],
    "pull": ["traction", "retention", "growth", "sales_cycle", "economics"],
    "scale": ["market", "competition"],
    "team": ["founder_team", "fundraising", "risks"],
}
# fmt: on
