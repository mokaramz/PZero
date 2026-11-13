# (protected gold-master data, copied by script from the old modules; see the header)
"""The Today catalog (review 030a): constants cut MECHANICALLY from the old ``services/today.py`` and
``services/compressor.py`` at revision 6c739b9 by exact line ranges (``scripts/gen_today_catalog.py``); nothing is
retyped. ``tests/today/test_today_port.py`` checks every cut against the old modules. Pure data.

From ``today.py`` (top level): ``MAX_ACTIONS``, the ten action ``TYPES`` (the old order; the two retired Scout types
stay listed, decision c drops only their sections) and ``_CLEAR_CONFLICT``. From ``compressor.py``: the routing
``STATES`` (the order of ``triage.counts``), ``LABEL`` (``triage.labels``), the attention-budget ``DEFAULTS`` (read by
``settings``) and ``_job``, the job state ``summary`` reports: no compression run is ported, so it is always idle.
"""

from __future__ import annotations

from typing import Any

# fmt: off
# ── from services/today.py ──
MAX_ACTIONS = 7
TYPES = (
    "CONTACT_FOUNDER",
    "ASK_OMAR_CONFLICT",
    "PREPARE_FOUNDER_CALL",
    "REVIEW_VERIFICATION",
    "EVENT_ACTION",
    "TRIAGE_REVIEW",
    "WATCH_TRIGGER",
    "CASE_READY",
    "NATIVE_INTEL",
    "SCOUT00_CYCLE",
)
_CLEAR_CONFLICT = ("none", "similar", "complementary")
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
LABEL = {
    "NEEDS_MOHAMED": "needs your judgment",
    "CASE_PREPARING": "queued for case preparation",
    "BACKGROUND_RESEARCH": "machine research queue",
    "MACHINE_WATCH": "machine watch",
    "DEFERRED_LOW_PRIORITY": "deferred",
    "CONFLICT_GATED": "conflict — Omar first",
    "CALIBRATION_SAMPLE": "calibration sample",
}
DEFAULTS: dict[str, Any] = {
    "human_review_daily_limit": 10,
    "calibration_sample_weekly": 5,
    "second_pass_daily_limit": 60,  # 5 batches of 12 on DeepSeek V4.1 Flash ≈ $0.006 / day
    "case_prep_per_run": 5,  # also bounded by case_prep.AUTO_MODEL_CASES_PER_DAY and the gateway budgets
    "auto_ic_chair": True,  # convene the IC Chair on hard prepared cases, within its weekly cap
}
_job: dict[str, Any] = {"running": False, "done": 0, "total": 0, "stage": "", "started": None, "finished": None}
# fmt: on
