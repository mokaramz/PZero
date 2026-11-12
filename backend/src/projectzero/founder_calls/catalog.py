# (protected gold-master data, copied by script from the old module; see the header)
"""The Founder Calls catalog (review 023): constants cut MECHANICALLY from the old ``domain/founder_calls.py`` at
revision 6c739b9 by exact top-level line ranges (``scripts/gen_founder_calls_catalog.py``); nothing is retyped.
``tests/founder_calls/test_founder_calls_port.py`` checks every string literal against the old module. Pure data.

``FILE_NAME``, the labels (``LABEL``, ``SUMMARY_LABEL``, ``UNKNOWN``), the enums (``CHANNELS``, ``CALL_TYPES``,
``RECOMMENDATIONS``, ``CONFIDENCE``, ``OWNERS``), ``UPCOMING_DAYS``, the call ``TEMPLATES`` and ``ASSESSMENT_FIELDS``.
"""

from __future__ import annotations

from typing import Any

# fmt: off
FILE_NAME = "founder_calls.json"
LABEL = "Founder-reported — unverified"
SUMMARY_LABEL = "Machine-generated from your private notes — " + LABEL
UNKNOWN = "UNKNOWN"
CHANNELS = ["video", "phone", "in-person", "email", "message", "other"]
CALL_TYPES = {
    "first": "First scout call",
    "followup": "Follow-up / diligence call",
    "intro_prep": "Project A introduction preparation",
}
RECOMMENDATIONS = ["Pass", "Monitor", "Follow up", "Consider for Omar"]
CONFIDENCE = ["Low", "Medium", "High"]
OWNERS = ["Mohamed", "Founder", "Omar", "Other"]
UPCOMING_DAYS = 7
TEMPLATES: dict[str, dict[str, Any]] = {
    "first": {
        "label": CALL_TYPES["first"],
        "sections": [
            {
                "id": "why",
                "q": "Why this company, problem and timing?",
                "followups": [
                    "What changed recently that makes this possible now?",
                    "Why did you personally start this — what did you see that others missed?",
                    "What would make you stop?",
                ],
            },
            {
                "id": "who",
                "q": "Who experiences the problem and how painful is it?",
                "followups": [
                    "Who is the buyer, who is the user, who pays?",
                    "How do they solve it today and what does that cost them?",
                    "How often does the problem occur?",
                ],
            },
            {
                "id": "built",
                "q": "What has been built and what is genuinely different?",
                "followups": [
                    "What exists today (demo, pilot, production)?",
                    "What is hard to copy, and why?",
                    "What did you build yourselves vs. assemble?",
                ],
            },
            {
                "id": "pull",
                "q": "What customer pull, usage, pilots or revenue exists?",
                "followups": [
                    "Named customers, pilots, LOIs, paid vs. free?",
                    "Retention, usage frequency, expansion?",
                    "Who said no and why?",
                ],
            },
            {
                "id": "scale",
                "q": "Why can this become a large company, and who competes?",
                "followups": [
                    "How big is the reachable market from where you start?",
                    "Who are the direct and indirect competitors, incumbents?",
                    "What is the wedge and the second product?",
                ],
            },
            {
                "id": "team",
                "q": "Why this team, what is being raised, and what happens next?",
                "followups": [
                    "Who are the founders, how did you meet, how are roles split?",
                    "Round size, timing, lead, valuation expectation?",
                    "Milestones for the next 12 months and what the money buys?",
                ],
            },
        ],
    },
    "followup": {
        "label": CALL_TYPES["followup"],
        "sections": [
            {
                "id": "metrics",
                "q": "Metrics",
                "followups": [
                    "Revenue / ARR, growth, burn, runway",
                    "Pipeline and conversion",
                    "Unit metrics you track weekly",
                ],
            },
            {
                "id": "customers",
                "q": "Customer evidence",
                "followups": [
                    "Reference customers we may speak to",
                    "Churn, NPS, expansion",
                    "Contract sizes and terms",
                ],
            },
            {
                "id": "gtm",
                "q": "Go-to-market",
                "followups": ["Channel, sales cycle, who sells", "Cost of acquisition", "Partnerships"],
            },
            {
                "id": "economics",
                "q": "Economics",
                "followups": ["Gross margin, pricing, payback", "Cost drivers", "Path to profitability"],
            },
            {
                "id": "tech",
                "q": "Technical defensibility",
                "followups": ["IP, data, integrations", "What would a well-funded competitor need?", "Technical risks"],
            },
            {
                "id": "gaps",
                "q": "Team gaps",
                "followups": ["Key hires next 12 months", "Advisors / board", "Equity split, vesting"],
            },
            {
                "id": "risks",
                "q": "Risks",
                "followups": ["Regulatory, platform, concentration", "What keeps you up at night?"],
            },
            {
                "id": "fundraising",
                "q": "Fundraising and milestones",
                "followups": [
                    "Round status, commitments, timeline",
                    "Milestones the round must reach",
                    "Runway if the round slips",
                ],
            },
        ],
    },
    "intro_prep": {
        "label": CALL_TYPES["intro_prep"],
        "sections": [
            {"id": "pitch", "q": "One-line pitch", "followups": []},
            {
                "id": "founder_case",
                "q": "Exceptional founder case",
                "followups": ["What in the founder's history proves it?"],
            },
            {"id": "fit", "q": "Project A fit", "followups": ["Archetype / theme, stage, geography"]},
            {"id": "round", "q": "Round details", "followups": ["Size, timing, lead, terms"]},
            {"id": "use_of_funds", "q": "Use of funds", "followups": []},
            {
                "id": "conflicts",
                "q": "Portfolio conflicts",
                "followups": ["Closest portfolio company and why it is / is not a conflict"],
            },
            {"id": "evidence", "q": "Strongest evidence", "followups": ["What could be verified publicly, and where?"]},
            {"id": "unresolved", "q": "Unresolved risks", "followups": []},
            {
                "id": "permission",
                "q": "Explicit permission to introduce",
                "followups": [
                    "Did the founder explicitly agree to an introduction to Project A? (yes / no / not asked)"
                ],
            },
        ],
    },
}
ASSESSMENT_FIELDS = [
    ("why_exceptional", "Why this founder may be exceptional"),
    ("founder_market_insight", "Founder-market insight"),
    ("speed_resourcefulness", "Speed and resourcefulness"),
    ("product_differentiation", "Product differentiation"),
    ("customer_pull", "Customer pull"),
    ("venture_scale", "Venture-scale potential"),
    ("project_a_relevance", "Project A relevance"),
    ("red_flags", "Red flags"),
    ("verify_facts", "Facts requiring verification"),
]
# fmt: on
