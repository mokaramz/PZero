# ruff: noqa: E501
# (protected gold-master data and rules, copied by script from the old modules; see the header)
"""The System health catalog (review 032a): constants and pure rules cut MECHANICALLY from the old
``services/health.py``, ``services/scheduler.py`` and ``services/health_overview.py`` at revision 6c739b9 by exact
line ranges (``scripts/gen_health_catalog.py``); nothing is retyped. ``tests/health/test_health_port.py`` checks every
cut against the old modules. No loader, no clock, no I/O.

From ``health.py``: ``STALE_DAYS``, ``_ts``, ``_days``, the source-repair ``REPAIR_RULES`` and ``_EXTERNAL_CAUSES``,
``diagnose``, ``STALE_JOB_REPORT_H`` and ``overall_status`` (the old texts: ``health.core`` uses it as it is when a
runner exists and rewords only the job-report sentences without one, decision k). From ``scheduler.py``:
``STALE_RUNNING_H``, ``REPEATED_FAILURES``, ``OUTCOMES`` and ``classify``; the ``JOBS`` rows as data (every key but
``run``; ``last`` / ``due`` name the old function, which ``health.core`` maps to the NEW readers). From
``health_overview.py``: ``HISTORY_DAYS`` and ``run_state``.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# fmt: off
# ── from services/health.py ──
STALE_DAYS = 21


def _ts(s: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace(" ", "T")[:19])
    except ValueError:
        return None


def _days(s: Any, now: datetime) -> int | None:
    t = _ts(s)
    return (now - t).days if t else None


REPAIR_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"no longer offers|became a web app|external change", re.I),
        "the publisher changed its site and removed this feed (external change)",
        "Nothing is broken in Project Zero. This source needs a new official data path before it can work again.",
    ),
    (
        re.compile(r"\b404\b|not found", re.I),
        "page moved or removed (HTTP 404)",
        "Open the site, find where the list moved (sitemap, news / portfolio section) and update the source URL.",
    ),
    (
        re.compile(r"\b(403|401)\b|forbidden|unauthori", re.I),
        "the site refuses automated access (HTTP 403)",
        "Do not try to get around it. Look for an official feed / API / RSS, or keep this source manual.",
    ),
    (
        re.compile(r"\b429\b|too many|rate", re.I),
        "rate limited (HTTP 429)",
        "Scan this source less often; never retry aggressively.",
    ),
    (
        re.compile(
            r"timed? ?out|timeout|deadline|\b408\b|connection (reset|aborted|refused)|remote ?end closed|remotedisconnected",
            re.I,
        ),
        "the site is slow or the scan budget ran out",
        "Usually transient. If it repeats, raise the per-source time budget or check whether the page got heavier.",
    ),
    (
        re.compile(r"ssl|certificate|tls", re.I),
        "TLS / certificate problem on the site",
        "Usually the site's fault; check the URL still uses the right host (www / non-www).",
    ),
    (
        re.compile(r"getaddrinfo|name or service|\bdns\b|nodename|could not resolve|failed to resolve", re.I),
        "domain does not resolve (DNS)",
        "The domain may be gone or renamed — check the organisation's current website.",
    ),
    (
        re.compile(r"\b5\d\d\b|server error|bad gateway|unavailable", re.I),
        "the site had a server error (HTTP 5xx)",
        "Transient on their side; wait for the next scan before acting.",
    ),
    (
        re.compile(r"parse|json|xml|no (items|results)|fetched but no|0 (records|results)|empty", re.I),
        "the page layout or feed format changed",
        "The parser no longer finds entries: check the page manually and adjust the parser / selector.",
    ),
]
_EXTERNAL_CAUSES = (
    "publisher changed",
    "refuses automated",
    "rate limited",
    "does not resolve",
    "TLS",
    "server error",
    "site is slow",
    "page moved",
)


def diagnose(error: str) -> dict[str, Any]:
    """Cause + what to do + whether it is EXTERNAL (Project Zero handled it safely) or a parser / code issue."""
    for rx, cause, fix in REPAIR_RULES:
        if rx.search(error or ""):
            return {"cause": cause, "suggestion": fix, "external": any(k in cause for k in _EXTERNAL_CAUSES)}
    return {
        "cause": "unknown error" if error else "no error recorded",
        "suggestion": "Open the source URL in a browser and compare with what the scanner expects.",
        "external": False,
    }


STALE_JOB_REPORT_H = 6  # the background task runs hourly: no job report for 6 h means the figures may be stale


def overall_status(verdict: str, issues: list[dict[str, str]], last_report: str, now: datetime) -> dict[str, Any]:
    """The dashboard's one-line answer. Derived from the existing verdict (never an average of unrelated metrics):
    only an issue that needs you makes it 'Action required'; external or self-recovering items mean 'Operational with
    limitations'; no job report for STALE_JOB_REPORT_H hours means the numbers may be stale ('Status unknown')."""
    n = {g: sum(1 for i in issues if i.get("group") == g) for g in ("need", "auto", "ext", "info")}
    t = _ts(last_report)
    age_h = round((now - t).total_seconds() / 3600, 1) if t else None
    if verdict in ("NEEDS ATTENTION", "UNHEALTHY"):
        key, label = "action", "Action required"
        sentence = f"{n['need']} item{'s' if n['need'] != 1 else ''} need{'s' if n['need'] == 1 else ''} you — see Needs your action."
    elif verdict == "DEGRADED":
        key, label = "degraded", "Degraded"
        sentence = "A part of Project Zero is degraded; everything else keeps working. Details under Needs your action."
    elif age_h is None or age_h > STALE_JOB_REPORT_H:
        key, label = "unknown", "Status unknown"
        sentence = ("No background job has reported yet" if age_h is None else f"No background job has reported for {age_h:.0f} h")
        sentence += " — the figures below may be stale. Is the computer asleep or the background task disabled?"
    elif any(n[g] for g in ("auto", "ext", "info")):
        key, label = "limited", "Operational with limitations"
        parts = []
        if n["ext"]:
            parts.append(f"{n['ext']} external limitation{'s' if n['ext'] != 1 else ''}")
        if n["auto"]:
            parts.append(f"{n['auto']} item{'s' if n['auto'] != 1 else ''} handled automatically")
        if n["info"]:
            parts.append(f"{n['info']} note{'s' if n['info'] != 1 else ''}")
        sentence = "Project Zero is running normally and nothing needs you. " + " · ".join(parts).capitalize() + "."
    else:
        key, label, sentence = "ok", "Operational", "Project Zero is running normally and nothing needs you."
    if key in ("action", "degraded") and age_h is not None and age_h > STALE_JOB_REPORT_H:
        sentence += f" No background job has reported for {age_h:.0f} h."
    return {"key": key, "label": label, "sentence": sentence, "groups": n, "last_job_report": last_report, "report_age_h": age_h}


# ── from services/scheduler.py ──
STALE_RUNNING_H = 2  # a "running" job older than this was interrupted (crash / closed window)
REPEATED_FAILURES = 2  # consecutive failures that make a job "keeps failing" (System health + Today)
OUTCOMES = {
    "completed": "completed",
    "no_findings": "completed — nothing new",
    "partial": "partially completed",
    "failed": "failed",
    "skipped": "skipped — another run was in progress",
    "budget_blocked": "blocked by a budget limit",
    "waiting_external": "waiting for an external dependency",
}


def classify(note: str, ok: bool) -> str:
    """The outcome of one job run, read from its own result line (jobs keep returning plain text)."""
    t = (note or "").lower()
    if not ok:
        return "failed"
    if t.startswith("skipped"):
        return "skipped"
    if "budget" in t and ("block" in t or "cap" in t or "limit" in t):
        return "budget_blocked"
    if re.search(r"\bpartial\b", t):
        return "partial"
    if re.search(r"relay unavailable|unavailable|still being written|key missing|not configured|provider error|"
                 r"weekend|bridge off|no hunt|awaiting", t):
        return "waiting_external"
    if re.search(r"(^|\D)0 (new|genuinely new|case|trigger|source candidate)|nothing|no new\b", t):
        return "no_findings"
    return "completed"


JOBS: tuple[dict[str, Any], ...] = (
    {"id": "watch_checks", "label": "WATCH checks", "interval_h": 24, "last": None},
    {"id": "deal_flow_scan", "label": "Deal Flow scan", "interval_h": 168, "last": "_last_scan"},
    {"id": "event_scan", "label": "Event source scan", "interval_h": 72, "last": "_last_event_scan"},
    {"id": "validation_snapshot", "label": "Validation snapshot", "interval_h": 24, "last": None},
    {"id": "news_refresh", "label": "News refresh", "interval_h": 24, "last": "_last_news"},
    {"id": "triage_retry", "label": "Machine triage retry (after a provider outage)", "interval_h": 1, "last": None},
    {"id": "news_weekly_review", "label": "Weekly learning review", "interval_h": 168, "last": None},
    {"id": "source_network", "label": "New-source discovery & probation", "interval_h": 24, "last": None},
    {"id": "triage_compression", "label": "Triage queue compression (human attention budget)", "interval_h": 6, "last": None},
    {"id": "native_scout", "label": "Native Scout hunt (signals / hypotheses — sourcing only)", "interval_h": 12, "last": None},
    {"id": "native_planner", "label": "Native Scout planner (2 rotating hunt lanes, free public sources)", "interval_h": 12, "last": None},
    {"id": "native_bridge", "label": "Native search bridge — production pilot (1 hunt per weekday, $0.25/day · $3/month caps)", "interval_h": 24, "last": None, "due": "_bridge_due", "while_open": True},
    {"id": "case_refresh", "label": "Case preparation freshness (stale / new Conviction cases)", "interval_h": 24, "last": None},
    {"id": "scout00_inbox", "label": "Scout 00 inbox — ingest completed packets into Scout Intake (free, no model call)", "interval_h": 1, "last": None},
    {"id": "news_source_review", "label": "News source comparison (monthly)", "interval_h": 720, "last": None},
)
# ── from services/health_overview.py ──
HISTORY_DAYS = 30


def run_state(r: dict[str, Any]) -> str:
    """The recorded outcome of one scheduled run. Older runs (before outcomes were recorded) only say ok / not ok."""
    oc = r.get("outcome")
    if r.get("ok") is False and oc in (None, "", "completed", "no_findings"):
        return "failed"
    if oc:
        return str(oc)
    return "completed" if r.get("ok", True) else "failed"


# fmt: on
