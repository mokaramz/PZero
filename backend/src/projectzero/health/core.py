# ruff: noqa: E501
# (protected gold-master logic: the old expressions, issue texts and sentences are kept verbatim, long lines included)
"""SYSTEM HEALTH (review 032a): the old ``GET /api/system_health`` (``services/health.py`` ``system()``) and ``GET
/api/system_health_overview`` (``services/health_overview.py`` ``overview()``) at revision 6c739b9, as pure functions
of ``HealthInputs`` and ONE Berlin clock (decision b). Key for key in the old order; reads never write (decision a);
the inputs are never mutated (every reader below works on copies).

CUT by script (``health.catalog``, ``scripts/gen_health_catalog.py``): ``diagnose`` and its rules, ``_ts`` /
``_days``, every branch of ``overall_status``, ``classify``, ``run_state``, ``OUTCOMES`` and the ``JOBS`` rows.

HAND-PORTED line for line (each old body calls a loader or the machine clock, replaced by a field of ``inputs`` and
the request clock; the expressions between are the old ones, in the old order): ``system`` (the issue rules, the
verdict), ``source_health``, ``_coverage_summary``, ``_providers``, ``last_job_report``; the scheduler's ``plan``,
``_interval``, ``failing_jobs`` and the three ``last`` readers (``_last_scan``, ``_last_event_scan``, ``_last_news``);
``budget.summary``'s spend (``ledger.spend``); ``job_history``, ``models``, ``pipeline``; ``news.health`` and
``news_sources.health``; and of ``watch.view()`` only the two counts the payload shows (``companies``,
``open_triggers``).

The ported NEW helpers reused (each the old function, checked in ``tests/health``):

* ``dealflow.triage.view.pending_map``: the old ``auto_triage.pending_map`` (given a COPY: it ``setdefault``s);
* ``validation.core.build`` / ``read_jsonl``: the old ``validation.build()`` / ``_read_jsonl``;
* ``ecosystems.coverage.coverage_view``: the old ``coverage.report()``;
* ``core.inference.budget.windows`` / ``limits``: the old ``ledger.spend`` windows / ``budget.limits``;
* ``conviction.operator.watch_triggers``: the old ``watch.triggers()``; ``dealflow.ranking.names.norm_company``;
* ``news.core`` ``load`` / ``_rows`` / ``_relevant`` and ``news.sources`` ``cached`` / ``_state`` / ``_network``.

Declared differences, all in ``ops/parity_health.normalise``: (c) the retired Scout parts are gone (the
``bridge_job`` repair research, rules 16 / 17, the four Scout jobs, the overview's ``search_bridge`` / ``scout00`` /
``native`` / ``pipeline.intake``); (d) every absent subsystem is ``{"deferred": reason}`` and the rules reading only
them (5, 12, 19, 20, 21, 22) are omitted; (e) the jobs are the imported snapshot and an imported ``running`` is
``interrupted`` (no runner is alive); (f) the paid switch's NEW semantics; (k) without a runner (``RUNNER = None``
until 032c) no issue and no headline promises a mechanism the app does not have: rules 3, 4 and 6-11 and the
job-report sentences are reworded (revision 2's table); with a runner the old texts are restored exactly.
"""

from __future__ import annotations

import copy
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Protocol

from projectzero.conviction.operator import watch_triggers
from projectzero.conviction.records import records
from projectzero.core.inference import budget
from projectzero.core.inference import config as icfg
from projectzero.dealflow.ranking.names import norm_company
from projectzero.dealflow.triage.view import decisions as read_jsonl  # the old ``validation._read_jsonl``
from projectzero.dealflow.triage.view import pending_map
from projectzero.ecosystems.coverage import coverage_view
from projectzero.health.catalog import (
    HISTORY_DAYS,
    JOBS,
    OUTCOMES,
    REPEATED_FAILURES,
    STALE_DAYS,
    STALE_JOB_REPORT_H,
    STALE_RUNNING_H,
    _days,
    _ts,
    classify,
    diagnose,
    overall_status,
    run_state,
)
from projectzero.health.inputs_model import HealthInputs
from projectzero.news import core as news_core
from projectzero.news import sources as news_sources
from projectzero.news.catalog import DEFAULT_WINDOW
from projectzero.news.inputs_model import NewsInputs
from projectzero.validation.core import build as validation_build


class Runner(Protocol):
    """The background-job runner (032c). Its presence restores the old job guidance (decision k); it decides whether
    a job recorded as ``running`` is still running (the old ``pid == os.getpid() or pid_alive(pid)``)."""

    def pid_alive(self, pid: Any) -> bool: ...


RUNNER: Runner | None = None  # decision (k): no runner until 032c

# decision (c): the retired Scout jobs (their rows stay in the catalog, cut from the old table)
RETIRED_JOBS = ("scout00_inbox", "native_scout", "native_planner", "native_bridge")

# decision (d): the absent subsystems, each sent as ``{"deferred": reason}``
SELFCHECK_DEFERRED = "The self-check is not ported yet: it was a state inside the old app's process."
LOCK_DEFERRED = "The background-job runner is not ported yet, so there is no job-runner lock."
BUILD_DEFERRED = "The release and stale-interface check is not ported yet."
SOURCE_DISCOVERY_DEFERRED = "The source network is not ported yet (review 032b)."
WATCH_CHECKS_DEFERRED = "The WATCH page checks are not ported yet."
BACKUPS_DEFERRED = "Backups are not ported yet (review 032b)."
INTEGRITY_DEFERRED = "The data-integrity check is not ported yet (review 032b)."
RELEASES_DEFERRED = "Releases are not ported yet (review 032b)."

# decision (c): rule 1 never offers the retired repair research job, with or without a runner
RULE1_DO = "Open Sources health below: each has a diagnosis."
# decision (k): revision 2's table, the advice without a runner (level / group: rule 1 keeps warn / need; the rest
# are info / info)
NO_RUNNER_DO = {
    3: "Finding new candidates arrives with the scan port; the last scan is the imported one.",
    4: "Preserved, nothing was lost. The machine-triage retry arrives with the background-job runner.",
    6: "The background-job runner is not ported yet: these jobs do not run, and Run overdue now is unavailable until it is.",
    7: "Recorded in the imported job history; nothing retries it until the runner is ported. Open Background jobs below for the error.",
    8: "Recorded in the imported job history; nothing runs it again until the runner is ported.",
    9: "Recorded in the imported job history; caps are never overridden, and nothing retries it until the runner is ported. Review spend under Models and budget.",
    10: "Recorded in the imported job history; the rest is not retried until the runner is ported.",
    11: "Recorded in the imported job history; nothing checks it again until the runner is ported.",
}
NO_RUNNER_UNKNOWN = "The background-job runner is not ported yet: no job has run since the imported snapshot (last report {at}). The job figures below are that snapshot."
NO_RUNNER_NO_REPORT = "The background-job runner is not ported yet: the imported snapshot holds no job report. The job figures below are that snapshot."
NO_RUNNER_SUFFIX = " The background-job runner is not ported yet; the job figures are the imported snapshot."


# declared (f): under the NEW switch paid calls run only when ``PZ_AI_PAID=on`` and a provider key is set (029a), so
# rule 15's old advice ("Intentional? Unset it to resume machine triage.") would keep them off
PAID_OFF_DO = (
    "Paid calls run only when PZ_AI_PAID=on and a provider key is set; switching them on is a deliberate choice."
)


def deferred(reason: str) -> dict[str, Any]:
    return {"deferred": reason}


# ---------------------------------------------------------------------------------------------------- sources
def source_health(inputs: HealthInputs, now: datetime) -> dict[str, Any]:
    """The old ``health.source_health(now)`` over the stored registry, the imported last scan and the inbox. Decision
    (c): the repair keeps its diagnosis, never the retired ``bridge_job``."""
    reg_sources = copy.deepcopy(inputs.sources)
    scans = (copy.deepcopy(inputs.scan_history) or {}).get("scans") or []
    last_report = {r.get("source_id") or r.get("source"): r for r in (scans[-1].get("sources") if scans else []) or []}
    by_src: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for c in records(copy.deepcopy(inputs.candidates), ("id",)):
        for sid in c.get("all_source_ids") or [c.get("source_id")]:
            if sid:
                by_src[sid].append(c)
    rows = []
    for s in reg_sources:
        if not isinstance(s, dict):
            continue
        fails = int(s.get("failures_in_row") or 0)
        rep = last_report.get(s.get("id")) or last_report.get(s.get("name")) or {}
        ok_days = _days(s.get("last_ok"), now)
        if not s.get("enabled"):
            state = "DISABLED"
        elif not s.get("last_ok") and (fails or s.get("last_scan")):
            state = "NEVER_SUCCESSFUL"
        elif fails >= 3:
            state = "FAILING"
        elif fails >= 1:
            state = "DEGRADED"
        elif ok_days is not None and ok_days > STALE_DAYS:
            state = "STALE"
        elif s.get("last_ok"):
            state = "HEALTHY"
        else:
            state = "NEVER_RUN"
        cands = by_src.get(s.get("id"), [])
        noise = sum(1 for c in cands if c.get("noise"))
        early = sum(1 for c in cands if c.get("discovery_tier") == "pre_company")
        last_useful = max((str(c.get("first_seen") or "")[:10] for c in cands if not c.get("noise")), default="")
        err: Any = rep.get("note") if rep.get("status") == "failed" else ""
        row: dict[str, Any] = {
            "id": s.get("id"),
            "name": s.get("name"),
            "url": s.get("url"),
            "state": state,
            "last_ok": s.get("last_ok"),
            "failures_in_row": fails,
            "last_useful_discovery": last_useful,
            "candidates": len(cands),
            "noise_rate": round(noise / len(cands), 2) if len(cands) >= 10 else None,
            "early_share": round(early / len(cands), 2) if len(cands) >= 10 else None,
            "last_error": err or "",
        }
        if state in ("FAILING", "NEVER_SUCCESSFUL", "STALE", "DEGRADED"):
            row["repair"] = {**diagnose(err)}  # decision (c): no ``bridge_job``
        rows.append(row)
    order = {
        "FAILING": 0,
        "NEVER_SUCCESSFUL": 1,
        "STALE": 2,
        "DEGRADED": 3,
        "NEVER_RUN": 4,
        "HEALTHY": 5,
        "DISABLED": 6,
    }
    rows.sort(key=lambda r: (order.get(r["state"], 9), str(r["name"])))
    return {
        "sources": rows,
        "counts": dict(Counter(r["state"] for r in rows)),
        "stale_days": STALE_DAYS,
        "rule": "Health is about retrieval, not volume — a quiet week is not a bad source.",
    }


def coverage_summary(inputs: HealthInputs, now: datetime) -> dict[str, Any]:
    """The old ``_coverage_summary()`` over ``coverage_view`` at the request clock, computed per request (decision a:
    no process cache, so never the old ``refreshing`` copy)."""
    try:
        if inputs.coverage is None:
            raise ValueError("the Deal Flow registry could not be read")
        rep = coverage_view(copy.deepcopy(inputs.coverage), now)
    except Exception:  # coverage needs no network, but a broken file must not break health
        return {"available": False, "error": "temporarily unavailable"}
    prio = (
        "munich",
        "münchen",
        "karlsruhe",
        "stuttgart",
        "heilbronn",
        "berlin",
        "zurich",
        "zürich",
        "lausanne",
        "paris",
        "london",
        "cambridge",
        "oxford",
        "copenhagen",
        "helsinki",
    )
    priority = sorted(
        (e for e in rep["ecosystems"] if str(e.get("city") or "").lower() in prio),
        key=lambda e: prio.index(str(e.get("city") or "").lower()),
    )
    fams = [f[0] for f in rep["families"]]
    return {
        "available": True,
        "counts": rep["counts"],
        "priority": [
            {
                "city": e["city"],
                "overall": e["overall"],
                "families": {f: ((e.get("families") or {}).get(f) or {}).get("state") for f in fams},
            }
            for e in priority[:15]
        ],
        "family_labels": dict(rep["families"]),
        "all": [  # every ecosystem (compact) — reused by the Map's ground-sourcing view
            {
                "city": e["city"],
                "country": e.get("country", ""),
                "families": {f: ((e.get("families") or {}).get(f) or {}).get("state") for f in fams},
            }
            for e in rep["ecosystems"]
        ],
    }


# ---------------------------------------------------------------------------------------------------- spend + providers
def spend_summary(inputs: HealthInputs, now: datetime) -> dict[str, Any]:
    """What ``system()`` read of the old ``budget.summary(cfg)``: ``ledger.spend`` over every ledger line (today, this
    ISO week, this month: ``budget.windows`` on the Berlin clock; each sum rounded to 6), ``budget.limits`` and the
    paid switch (decision f: ``PZ_AI_PAID`` whenever paid calls are off)."""
    day0, week0, month0 = budget.windows(now)
    out = {"day": 0.0, "week": 0.0, "month": 0.0, "all_time": 0.0}
    for e in inputs.ledger:
        v = float(e.get("usd") or 0.0)
        if not v:
            continue
        out["all_time"] += v
        try:
            t = datetime.strptime(str(e.get("ts")), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=budget.BERLIN)
        except ValueError:
            continue
        out["day"] += v if t >= day0 else 0.0
        out["week"] += v if t >= week0 else 0.0
        out["month"] += v if t >= month0 else 0.0
    return {
        "spend": {k: round(v, 6) for k, v in out.items()},
        "limits": budget.limits(inputs.inference_config).as_dict(),
        "kill_switch": None if inputs.paid else icfg.PAID_ENV,
    }


def providers(inputs: HealthInputs) -> list[dict[str, Any]]:
    """The old ``_providers()``. Decision (f): ``key`` says only whether the key variable is set."""
    cfg = inputs.inference_config
    out = []
    for role, r in (cfg.get("roles") or {}).items():
        prov = (cfg.get("providers") or {}).get(r.get("provider") or "", {})
        env = prov.get("key_env") or ""
        enabled = r.get("enabled", True) is not False and bool(r.get("provider"))
        out.append(
            {
                "role": role,
                "provider": r.get("provider") or "—",
                "model": r.get("model") or "—",
                "enabled": enabled,
                "key": bool(env and inputs.keys.get(env, False)) if enabled else None,
            }
        )
    return out


# ---------------------------------------------------------------------------------------------------- watch + news
def watch_counts(inputs: HealthInputs) -> tuple[int, int]:
    """Of the old ``watch.view()``: ``len(companies)`` and the open triggers of the watched companies (``watched()``:
    the inbox candidates whose decision is ``watch`` plus the active manual targets; ``triggers()`` with their
    current status). The page checks' failures are the watch sensors' (not ported, decision d)."""
    d = copy.deepcopy(inputs.watch_targets) or {}
    d.setdefault("targets", {})
    targets = d["targets"]
    trig = watch_triggers(copy.deepcopy(inputs.watch_events))
    watched: dict[str, dict[str, Any]] = {}
    for c in records(copy.deepcopy(inputs.candidates), ("id",)):
        if c.get("decision") == "watch" and c.get("name"):
            watched[norm_company(c["name"]) or c["id"]] = {"name": c["name"], "candidate_id": c["id"]}
    for k, t in targets.items():
        if t.get("active", True):
            watched.setdefault(k, {"name": t.get("name") or k, "candidate_id": t.get("candidate_id") or ""})
    opened = [sum(1 for x in trig if x["entity_key"] == key and x["status"] == "new") for key in watched]
    return len(watched), sum(opened)


def news_sources_health(news: NewsInputs) -> dict[str, Any]:
    """The old ``news_sources.health()`` (cache only)."""
    snap = news_sources.cached(news.source_metrics)
    w = (snap.get("windows") or {}).get(DEFAULT_WINDOW) or {}
    st = news_sources._state(news)
    srcs = [r for r in (w.get("sources") or {}).values() if r["kind"] != "external"]
    tech = Counter(r["technical"].get("state") for r in srcs)
    try:
        net = [c for c in news_sources._network(news)["candidates"].values() if c.get("family") == "news_publication"]
    except Exception:
        net = []
    return {
        "evaluated_at": snap.get("at"),
        "benchmark_events": w.get("benchmark_events"),
        "feeds_healthy": tech.get("HEALTHY", 0),
        "feeds_failing": [r["name"] for r in srcs if r["technical"].get("state") in ("FAILING", "BLOCKED")],
        "degraded": [n for n, s in st.items() if s.get("state") == "DEGRADED"],
        "probation": [c["name"] for c in net if c["state"] == "PROBATION"],
        "candidates": [c["name"] for c in net if c["state"] in ("DISCOVERED", "VALIDATING")],
        "sources": len(srcs),
    }


def news_health(inputs: HealthInputs) -> dict[str, Any]:
    """The old ``news.health()``."""
    news = copy.deepcopy(inputs.news)
    runs = news_core._rows(news.runs_log)
    last = runs[-1] if runs else None
    d = news_core.load(news.events or {})
    pending = 0
    for e in records(d["events"]):
        try:
            pending += int(e.get("materiality") == "HIGH" and not e.get("backcast") and news_core._relevant(e))
        except Exception:  # one unreadable story never breaks News health
            continue
    try:
        src = news_sources_health(news)
    except Exception:  # never breaks health (detail in the log)
        src = {"error": "temporarily unavailable"}
    return {
        "sources": src,
        "last_run": last,
        "events": len(d["events"]),
        "backcasts_pending": pending,
        "usd_total": round(sum(float(r.get("usd") or 0) for r in runs), 4),
    }


# ---------------------------------------------------------------------------------------------------- the jobs
def active_jobs() -> list[dict[str, Any]]:
    """``JOBS`` without the retired Scout jobs (decision c), in the old order."""
    return [j for j in JOBS if j["id"] not in RETIRED_JOBS]


def _last_scan(inputs: HealthInputs) -> datetime | None:
    scans = (inputs.scan_history or {}).get("scans") or []
    return max((t for t in (_ts(s.get("scan_finished") or s.get("run_id")) for s in scans) if t), default=None)


def _last_event_scan(inputs: HealthInputs) -> datetime | None:
    return _ts((inputs.event_health or {}).get("scan_time"))


def _last_news(inputs: HealthInputs) -> datetime | None:
    """Any completed news refresh counts (a manual refresh this morning means no second fetch at catch-up)."""
    done = [r for r in news_core._rows(inputs.news.runs_log) if r.get("status", "ok") in ("ok", "partial")]
    return max((t for t in (_ts(r.get("completed_at") or r.get("at")) for r in done) if t), default=None)


LAST = {"_last_scan": _last_scan, "_last_event_scan": _last_event_scan, "_last_news": _last_news}


def _jobs_state(inputs: HealthInputs) -> Any:
    return copy.deepcopy(inputs.job_state) or {}


def _interval(job: dict[str, Any], config: Any) -> float:
    over = (config.get("catch_up") or {}).get("intervals_h") or {}
    try:
        return float(over.get(job["id"], job["interval_h"]))
    except (TypeError, ValueError):
        return float(job["interval_h"])


def plan(inputs: HealthInputs, now: datetime, runner: Runner | None = RUNNER) -> list[dict[str, Any]]:
    """The old ``scheduler.plan(now)`` over the imported job state. Decision (e): without a runner nothing is running,
    so a job recorded as ``running`` is ``interrupted`` (the old ``recover_on_start`` at startup)."""
    st = _jobs_state(inputs)
    config = copy.deepcopy(inputs.config)
    out = []
    for job in active_jobs():
        s = st.get(job["id"]) if isinstance(st.get(job["id"]), dict) else {}  # a malformed record = never run
        last_ok = _ts(s.get("last_ok"))
        if job["last"]:
            try:
                ext = LAST[job["last"]](inputs)
            except Exception:
                ext = None
            last_ok = max((x for x in (last_ok, ext) if x), default=None)
        if s.get("state") != "running" or runner is None:  # decision (e): no runner is alive
            running = False
        elif s.get("pid"):  # the owning process decides: alive = running, gone = interrupted
            running = runner.pid_alive(s["pid"])
        else:  # records written before pids were stored
            running = (_ts(s.get("started")) or now) > now - timedelta(hours=STALE_RUNNING_H)
        due_at = last_ok + timedelta(hours=_interval(job, config)) if last_ok else None
        out.append(
            {
                "id": job["id"],
                "label": job["label"],
                "interval_h": _interval(job, config),
                "last_ok": last_ok.isoformat(timespec="seconds") if last_ok else None,
                "next_due": due_at.isoformat(timespec="seconds") if due_at else "now",
                "overdue": not running and (due_at is None or due_at <= now),
                "state": "interrupted"
                if s.get("state") == "running" and not running
                else s.get("state") or "never_run",
                "last_note": s.get("note") or "",
                "outcome": s.get("outcome")
                or (classify(s.get("note") or "", s.get("state") != "failed") if s.get("note") else None),
                "outcome_label": OUTCOMES.get(s.get("outcome") or "", ""),
                "source": s.get("source") or "",
                "seconds": s.get("seconds"),
                "fails_in_row": int(s.get("fails_in_row") or 0),
                "error": s.get("error") or "",
            }
        )
    return out


def failing_jobs(inputs: HealthInputs) -> list[dict[str, Any]]:
    """Jobs whose last REPEATED_FAILURES or more runs failed — they must not stay quiet."""
    st = _jobs_state(inputs)
    out = []
    for j in active_jobs():
        s = st.get(j["id"]) if isinstance(st.get(j["id"]), dict) else {}
        n = int(s.get("fails_in_row") or 0)
        if n >= REPEATED_FAILURES:
            out.append(
                {"id": j["id"], "label": j["label"], "fails_in_row": n, "error": s.get("error") or s.get("note") or ""}
            )
    return out


def last_job_report(inputs: HealthInputs) -> str:
    """Timestamp of the newest scheduled-job run (the last ``runs.jsonl`` line), '' when none was ever recorded."""
    return str(inputs.runs[-1].get("at") or "") if inputs.runs else ""


def status_of(
    verdict: str, issues: list[dict[str, str]], last_report: str, now: datetime, runner: Runner | None
) -> dict[str, Any]:
    """The old ``overall_status`` (cut verbatim). Decision (k): without a runner its two job-report sentences say
    that the runner is not ported, and the snapshot's last report when there is one."""
    st = overall_status(verdict, issues, last_report, now)
    if runner is not None:
        return st
    age_h = st["report_age_h"]
    if st["key"] == "unknown":
        t = _ts(last_report) if age_h is not None else None
        st["sentence"] = NO_RUNNER_UNKNOWN.format(at=t.strftime("%Y-%m-%d %H:%M")) if t else NO_RUNNER_NO_REPORT
    elif st["key"] in ("action", "degraded") and age_h is not None and age_h > STALE_JOB_REPORT_H:
        old = f" No background job has reported for {age_h:.0f} h."
        assert st["sentence"].endswith(old)
        st["sentence"] = st["sentence"][: -len(old)] + NO_RUNNER_SUFFIX
    return st


# ---------------------------------------------------------------------------------------------------- GET /api/system_health
def system_view(inputs: HealthInputs, now: datetime, runner: Runner | None = RUNNER) -> dict[str, Any]:
    """One answer to 'Is Project Zero healthy?' with the reasons — and what to do about each. ``now``: the request
    instant as naive Berlin wall time. ``runner``: the background-job runner (``None`` until 032c, decision k)."""
    issues: list[dict[str, str]] = []

    def issue(level: str, what: str, do: str, group: str = "") -> None:
        """group (who handles it): need = only you can act · auto = Project Zero retries / recovers it · ext = a third
        party outside PZ's control · info = no impact on your work. Default: a warning needs you, the rest is info."""
        issues.append(
            {"level": level, "what": what, "do": do, "group": group or ("need" if level == "warn" else "info")}
        )

    src = source_health(inputs, now)
    down = [r for r in src["sources"] if r["state"] in ("FAILING", "NEVER_SUCCESSFUL")]
    ext = [r for r in down if (r.get("repair") or {}).get("external")]
    if len(down) > len(ext):  # a Project Zero side problem (parser / code): Mohamed may need to look
        issue(
            "warn",
            f"{len(down) - len(ext)} source(s) failing for a reason Project Zero can fix (parser / address)",
            RULE1_DO,  # decision (c): the repair research job is retired
        )
    if ext:  # external ≠ Project Zero failure: blocked / changed upstream, handled safely, nothing lost
        issue(
            "info",
            f"{len(ext)} source(s) unavailable for external reasons ("
            + ", ".join(str(r["name"]).split(" (")[0] for r in ext[:3])
            + ") — handled safely, not bypassed",
            "Nothing to do; the other sources keep working. Sources health below shows each cause.",
            "ext",
        )
    scans = (copy.deepcopy(inputs.scan_history) or {}).get("scans") or []
    last_scan = max((s.get("scan_finished") or s.get("run_id") or "" for s in scans), default="")
    age = _days(last_scan, now)
    if age is None or age > 10:
        what = "no Deal Flow scan in over 10 days" if age else "no Deal Flow scan yet"
        if runner is not None:
            issue("warn", what, "Run Find New Candidates (or let catch-up run it).")
        else:
            issue("info", what, NO_RUNNER_DO[3], "info")
    pending = pending_map(copy.deepcopy(inputs.auto_runs), copy.deepcopy(inputs.proposals), dict(inputs.aliases))
    if pending:
        what = f"{len(pending)} candidate(s) waiting for machine triage — preserved, nothing was lost"
        if runner is not None:
            nxt = inputs.triage_next_try
            issue(
                "info",
                what,
                "Retried automatically"
                + (f" (next try {nxt[11:16]})" if nxt else "")
                + "; Deal Flow → “Retry now” tries immediately. Nothing to do unless the provider stays down.",
                "auto",
            )
        else:
            issue("info", what, NO_RUNNER_DO[4], "info")
    rq = copy.deepcopy(inputs.research_questions) or {}
    research_open = Counter(q.get("status") for q in rq.values())
    companies, open_triggers = watch_counts(inputs)  # rule 5 (the page checks) is the watch sensors' (decision d)
    jobs = plan(inputs, now, runner)
    overdue = [p for p in jobs if p["overdue"]]
    if overdue:  # the background task runs them at its next trigger (hourly / logon / unlock): handled automatically
        what = f"{len(overdue)} background job(s) overdue: " + ", ".join(p["label"].split(" (")[0] for p in overdue[:4])
        if runner is not None:
            issue(
                "info",
                what,
                "They run at the next background trigger (hourly, at logon or unlock); “Run overdue now” starts them immediately.",
                "auto",
            )
        else:
            issue("info", what, NO_RUNNER_DO[6], "info")
    keeps = failing_jobs(inputs)
    if keeps:  # repeated failures are never quiet: a job that failed twice in a row needs a look
        what = "background job keeps failing: " + "; ".join(
            f"{k['label']} ({k['fails_in_row']} runs in a row — {str(k['error'])[:120]})" for k in keeps
        )
        if runner is not None:
            issue("warn", what, "Open Background jobs below for the error; the job retries automatically when due.")
        else:
            issue("info", what, NO_RUNNER_DO[7], "info")
    once = [p for p in jobs if p["state"] in ("failed", "interrupted") and p["id"] not in {k["id"] for k in keeps}]
    if once:
        what = "background job(s) failed or were interrupted: " + ", ".join(p["label"] for p in once)
        if runner is not None:
            issue("warn", what, "See Background jobs below; they run again when due.")
        else:
            issue("info", what, NO_RUNNER_DO[8], "info")
    blocked = [p for p in jobs if p.get("outcome") == "budget_blocked"]
    if blocked:
        what = "background job blocked by a budget limit: " + ", ".join(p["label"] for p in blocked)
        if runner is not None:
            issue(
                "warn", what, "Work is kept for retry; caps are never overridden. Review spend under Models and budget."
            )
        else:
            issue("info", what, NO_RUNNER_DO[9], "info")
    partial = [p for p in jobs if p.get("outcome") == "partial"]
    if partial:
        what = "background job(s) only partially completed: " + ", ".join(p["label"] for p in partial)
        if runner is not None:
            issue("info", what, "The rest is kept for retry; see the job note under Background jobs.", "auto")
        else:
            issue("info", what, NO_RUNNER_DO[10], "info")
    waiting = [p for p in jobs if p.get("outcome") == "waiting_external"]
    if waiting:
        what = "waiting for an external dependency: " + ", ".join(
            f"{p['label']} ({str(p['last_note'])[:60]})" for p in waiting
        )
        if runner is not None:
            issue("info", what, "Nothing to do in Project Zero unless it persists.", "ext")
        else:
            issue("info", what, NO_RUNNER_DO[11], "info")
    # rule 12 (a hung job-runner lock) reads the runner's pid lock (decision d)
    spend = spend_summary(inputs, now)
    lim = spend["limits"]
    if spend["spend"]["month"] >= 0.8 * lim["monthly_usd"]:
        issue(
            "warn",
            f"AI spend this month ${spend['spend']['month']:.2f} of ${lim['monthly_usd']:.2f}",
            "Caps stop paid calls automatically; nothing is overridden.",
        )
    provs = providers(inputs)
    if any(p["enabled"] and p["key"] is False for p in provs if p["role"] in ("CHEAP", "STANDARD")):
        issue(
            "warn",
            "an AI provider key is missing for machine triage / analysis",
            "Set the API key (see Models below); triage waits as TRIAGE PENDING meanwhile.",
        )
    if spend.get("kill_switch"):
        issue(
            "info",
            f"paid AI is switched off ({spend['kill_switch']})",
            PAID_OFF_DO,  # declared (f): the old advice "Unset it" no longer turns paid calls on
        )
    # rules 16 / 17 (the search bridge and the Scout 00 transport) are retired (decision c)
    snaps = read_jsonl(inputs.validation.snapshots_log)
    try:
        _ents, data_issues = validation_build(copy.deepcopy(inputs.validation), now.date())
    except Exception:
        data_issues = ["validation data could not be read"]
    if data_issues:
        issue("info", f"{len(data_issues)} data warning(s) in Validation", "See Validation → Data warnings.")
    try:
        nh = news_health(inputs)
    except Exception:  # News failure never breaks health (detail in the log)
        nh = {"error": "temporarily unavailable"}
    # rules 19-22 (the source network, the stale interface, the self-check, the skipped records) read absent
    # subsystems (decision d)
    lr = nh.get("last_run") or {}
    if lr.get("sources_failed"):
        issue(
            "info",
            f"{len(lr['sources_failed'])} news feed(s) failed in the last refresh",
            "News retries tomorrow; sourcing is unaffected.",
            "ext",
        )
    # exception-based: only an item that needs Mohamed ("warn") makes the verdict ask for attention; informational /
    # external items that say "nothing to do" are FYI. A DEGRADED subsystem is named as such.
    warns = [i for i in issues if i["level"] == "warn"]
    degraded = [i for i in warns if i["what"].startswith("DEGRADED:")]
    actionable = [i for i in warns if i not in degraded]
    verdict = (
        "UNHEALTHY"
        if len(actionable) >= 3
        else "DEGRADED"
        if degraded
        else "NEEDS ATTENTION"
        if actionable
        else "FYI — EXTERNAL LIMITATIONS"
        if issues
        else "HEALTHY"
    )
    return {
        "at": now.isoformat(timespec="seconds"),
        "verdict": verdict,
        "status": status_of(verdict, issues, last_job_report(inputs), now, runner),
        "issues": issues,
        "sources": src,
        "coverage": coverage_summary(inputs, now),
        "triage_pending": len(pending),
        "research": dict(research_open),
        "watch": {
            "companies": companies,
            "open_triggers": open_triggers,
            "failing_checks": deferred(WATCH_CHECKS_DEFERRED),
        },
        "jobs": jobs,
        "overdue": len(overdue),
        "job_runner": {
            "lock": deferred(LOCK_DEFERRED),
            "runners": copy.deepcopy(inputs.runners),
            "outcomes": dict(OUTCOMES),
        },
        "spend": {
            "day": spend["spend"]["day"],
            "week": spend["spend"]["week"],
            "month": spend["spend"]["month"],
            "limits": {k: lim[k] for k in ("daily_usd", "weekly_usd", "monthly_usd") if k in lim},
            "kill_switch": spend.get("kill_switch"),
        },
        "providers": provs,
        "last_scan": last_scan,
        "news": nh,
        "build": deferred(BUILD_DEFERRED),
        "selfcheck": deferred(SELFCHECK_DEFERRED),
        "source_discovery": deferred(SOURCE_DISCOVERY_DEFERRED),
        "validation": {
            "snapshots": len(snaps),
            "last_snapshot": snaps[-1]["date"] if snaps else None,
            "data_issues": len(data_issues),
        },
    }


# ---------------------------------------------------------------------------------------------------- the overview
def job_history(inputs: HealthInputs, now: datetime, days: int = HISTORY_DAYS) -> dict[str, Any]:
    rows = copy.deepcopy(inputs.runs)
    since = (now - timedelta(days=days)).isoformat(timespec="seconds")
    runs = [
        {"at": r.get("at"), "job": r.get("job"), "label": r.get("label") or r.get("job"), "state": run_state(r),
         "seconds": r.get("seconds"), "note": str(r.get("note") or "")[:400], "source": r.get("source") or ""}
        for r in rows
        if isinstance(r.get("at"), str) and r["at"] >= since and r.get("job")
    ]  # fmt: skip
    first_outcome = next((r["at"] for r in rows if r.get("outcome") and isinstance(r.get("at"), str)), None)
    return {"days": days, "runs": runs, "outcomes_recorded_since": first_outcome}


def models(inputs: HealthInputs, now: datetime, days: int = HISTORY_DAYS) -> dict[str, Any]:
    """Every model Project Zero actually called (the ledger), with 7-day success, latency, errors and cost.
    Daily spend per model covers the last `days` days. This is the GENERAL model budget only."""
    c7 = (now - timedelta(days=7)).isoformat(timespec="seconds")
    since = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    agg: dict[str, dict[str, Any]] = {}
    by_day: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in copy.deepcopy(inputs.ledger):
        name = str(r.get("model") or "unknown")
        ts = str(r.get("ts") or "")
        m = agg.setdefault(name, {"model": name, "provider": r.get("provider") or "", "roles": set(), "calls": 0, "ok": 0, "errors": 0,
                                  "cache_hits": 0, "blocked": 0, "usd": 0.0, "lat": [], "last_ok": "", "last_error": "",
                                  "error_kinds": Counter(), "calls_7d": 0, "ok_7d": 0})  # fmt: skip
        if r.get("role"):
            m["roles"].add(str(r["role"]))
        m["calls"] += 1
        o = r.get("outcome")
        if o == "ok":
            m["ok"] += 1
            m["last_ok"] = max(m["last_ok"], ts)
            if isinstance(r.get("latency_ms"), (int, float)) and ts >= c7:
                m["lat"].append(r["latency_ms"])
        elif o == "cache_hit":
            m["cache_hits"] += 1
        elif o == "blocked":
            m["blocked"] += 1
        else:
            m["errors"] += 1
            m["last_error"] = max(m["last_error"], ts)
            m["error_kinds"][str(r.get("error_kind") or "unknown")] += 1
        if ts >= c7 and o in ("ok", "error"):
            m["calls_7d"] += 1
            m["ok_7d"] += o == "ok"
        usd = float(r.get("usd") or 0)
        m["usd"] += usd
        if ts[:10] >= since and usd:
            by_day[ts[:10]][name] += usd
    rows = []
    for m in agg.values():
        lat = sorted(m.pop("lat"))
        rows.append({**m, "roles": sorted(m["roles"]), "usd": round(m["usd"], 6), "error_kinds": dict(m["error_kinds"]),
                     "p50_ms_7d": lat[len(lat) // 2] if lat else None})  # fmt: skip
    rows.sort(key=lambda x: (-x["calls_7d"], -x["calls"]))
    return {
        "rows": rows,
        "spend_by_day": {d: {k: round(v, 6) for k, v in ms.items()} for d, ms in sorted(by_day.items())},
    }


def pipeline(inputs: HealthInputs) -> dict[str, Any]:
    """The old ``pipeline()``. Decision (c): the retired Scout Intake ``intake`` count is gone."""
    qr = inputs.queue_routing if isinstance(inputs.queue_routing, dict) else {}  # the old ``_load``
    conv = [x for x in (inputs.signals or []) if isinstance(x, dict)]
    return {
        "inbox": dict(Counter(str(d or "") for d in inputs.inbox_decisions))  # Codex H-309: the merged Deal Flow
        if inputs.inbox_decisions is not None
        else dict(Counter(str(c.get("decision") or "") for c in inputs.candidates or [] if isinstance(c, dict))),
        "routing": {"counts": copy.deepcopy(qr.get("counts") or {}), "at": qr.get("at")},
        "conviction": dict(Counter(str(x.get("status") or "") for x in conv)),
        "manager_sent": sum(1 for x in conv if x.get("sent_to_omar")),
    }


def overview_view(inputs: HealthInputs, now: datetime) -> dict[str, Any]:
    """The old ``GET /api/system_health_overview`` body. Decisions (c) and (d): the Scout keys are gone; backups,
    integrity and releases are 032b's."""
    return {
        "at": now.isoformat(timespec="seconds"),
        "jobs": job_history(inputs, now),
        "models": models(inputs, now),
        "pipeline": pipeline(inputs),
        "backups": deferred(BACKUPS_DEFERRED),
        "integrity": deferred(INTEGRITY_DEFERRED),
        "releases": deferred(RELEASES_DEFERRED),
    }
