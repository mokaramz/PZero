# (protected gold-master data, copied by script from the old modules; see the header)
"""The Validation catalog (review 027a): constants cut MECHANICALLY from the old ``services/validation.py`` and
``services/compressor.py`` at revision 6c739b9 by exact line ranges (``scripts/gen_validation_catalog.py``); nothing
is retyped. ``tests/validation/test_validation_port.py`` checks every cut against the old modules. Pure data.

From ``validation.py`` (top level): the four log names (``OUTCOMES``, ``AUDITS``, ``SNAPSHOTS``, ``SCOUT_LOG``),
``MIN_N``, the outcome kinds (``POSITIVE_KINDS``, ``NEGATIVE_KINDS``, ``BENCHMARK_KINDS``, ``KINDS`` in that order:
the select order), ``LEAD_KINDS``, ``REAL_WORLD_STRONG``, ``MISS_REASONS``, ``FP_CAUSES``, ``EVIDENCE_CLASS``,
``STAGES`` (the table columns), ``STAGE_LABEL``, ``MISS_TYPES``, ``VALUE_WEIGHTS`` / ``SMOOTH`` (the source ranking),
``BENCHMARK_KINDS_ALL`` and the benchmark column names (``_NAME_COLS``, ``_DATE_COLS``). From ``compressor.py``: the
routing ``STATES``.
"""

from __future__ import annotations

# fmt: off
# ── from services/validation.py ──
OUTCOMES = "validation/outcomes.jsonl"
AUDITS = "validation/audits.jsonl"
SNAPSHOTS = "validation/snapshots.jsonl"
SCOUT_LOG = "validation/scout_feedback.jsonl"
MIN_N = 5  # below this a rate is not shown — only the counts
POSITIVE_KINDS = {
    "institutional_round": "Institutional funding round announced",
    "accelerator": "Accelerator / programme acceptance announced",
    "mainstream_press": "First mainstream startup-news appearance",
    "commercial_milestone": "Material commercial milestone (customer, launch, revenue)",
    "acquisition": "Acquired (positive exit)",
    "omar_interested": "Omar interested / requested follow-up",
    "project_a_invested": "Project A invested",
}
NEGATIVE_KINDS = {
    "shutdown": "Company shut down / founders left",
    "weak_outcome": "Proved weak on closer inspection (Mohamed)",
    "omar_declined": "Omar not interested",
}
BENCHMARK_KINDS = {"external_db_listing": "Visible in an external database (Dealroom / Crunchbase / …)"}
KINDS = {**POSITIVE_KINDS, **NEGATIVE_KINDS, **BENCHMARK_KINDS}
LEAD_KINDS = ("institutional_round", "accelerator", "mainstream_press", "commercial_milestone", "external_db_listing")
REAL_WORLD_STRONG = ("institutional_round", "commercial_milestone", "acquisition", "project_a_invested")
MISS_REASONS = (
    "source_not_covered",
    "source_covered_but_failed",
    "entity_extraction",
    "filtered_as_noise",
    "machine_reject",
    "mohamed_reject",
    "watch_not_followed",
    "too_late_signal_only",
    "other",
)
FP_CAUSES = (
    "weak_source",
    "bad_entity_extraction",
    "duplicated_pr_as_independent",
    "late_stage_mistaken_for_early",
    "founder_quality_overestimated",
    "technical_novelty_not_venture",
    "ai_wrapper",
    "portfolio_conflict",
    "poor_market",
    "insufficient_evidence",
    "model_error",
    "mohamed_judgment_error",
    "other",
)
EVIDENCE_CLASS: dict[int, str] = {
    1: "verified real-world outcome",
    2: "human decision / response (Mohamed, Omar)",
    3: "deterministic Project Zero gate (verification, Radar, IMQ)",
    4: "independent external observation (e.g. later funding news seen by a scan)",
}
STAGES = (
    "discovered",
    "machine_keep_research",
    "mohamed_accepted",
    "conviction",
    "verified",
    "radar",
    "imq",
    "omar",
)
STAGE_LABEL = {
    "discovered": "Discovered",
    "machine_keep_research": "Machine KEEP / RESEARCH",
    "mohamed_accepted": "Mohamed accepted",
    "conviction": "Conviction",
    "verified": "Fully verified",
    "radar": "Radar",
    "imq": "IMQ qualified",
    "omar": "Sent to Omar",
}
MISS_TYPES = {
    "never_found": "Project Zero never saw it",
    "found_too_late": "seen only at or after its public event",
    "found_early_but_rejected": "seen early, then rejected (machine or Mohamed)",
    "watch_not_followed": "seen early, put on WATCH, then it became strong",
    "found_early_not_progressed": "seen early, left undecided",
}
VALUE_WEIGHTS: dict[str, float] = {
    "strong": 10.0,
    "conviction": 4.0,
    "mohamed_accepted": 2.0,
    "machine_keep_research": 1.0,
    "pre_company": 0.5,
    "pre_funding": 0.5,
    "at_announcement": -0.5,
}
SMOOTH = 5
BENCHMARK_KINDS_ALL = ("institutional_round", "accelerator", "mainstream_press", "external_db_listing")
_NAME_COLS = ("name", "company", "company name", "organization", "organisation", "organization name")
_DATE_COLS = (
    "first seen",
    "added",
    "date added",
    "created",
    "launch date",
    "first funding date",
    "announced date",
    "last funding date",
    "date",
)
# ── from services/compressor.py ──
STATES = (
    "NEEDS_MOHAMED",
    "CASE_PREPARING",
    "BACKGROUND_RESEARCH",
    "MACHINE_WATCH",
    "DEFERRED_LOW_PRIORITY",
    "CONFLICT_GATED",
    "CALIBRATION_SAMPLE",
)
# fmt: on
