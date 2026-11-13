# ruff: noqa: E501
# (the synthetic worlds: one record per line; the old issue texts are matched verbatim)
"""System health parity: the pure port against the OLD code as oracle, with a FIXED clock and no write (review 032a).

    python -m projectzero.ops.parity_health goldens   # (re)generates golden_v1/oracle_health.json (needs the old repo)
    python -m projectzero.ops.parity_health check     # the stored golden against the new code (no oracle)
    python -m projectzero.ops.parity_health real      # (not yet: the real snapshot through both routes, see ``real``)

The oracle (``scripts/oracle/health_oracle.py``) runs the old ``health.system()`` and ``health_overview.overview()``
once per world over a scratch data folder holding the world's documents, the clock frozen at the world's ``clock``
(naive Berlin wall time), the world's paid switch and key presence in the environment, the retired Scout services
and the absent subsystems stubbed, and every write blocked (the folder is checked unchanged). The new side is the
PURE port (``health.inputs_from_docs`` -> ``health.system_view`` / ``overview_view``) over the same documents at
the same clock. Every answer is compared value by value AND as serialized text (key order), after ``normalise``;
the inputs and the documents are checked unchanged.

Declared differences, ALL applied by ``normalise`` (old payload -> the expected new one):

* **(c) retired Scout parts:** ``sources[].repair.bridge_job`` dropped and rule 1's advice without the repair
  research job (``NEW_DO[1]``, with or without a runner: Codex H-306); the overview's ``search_bridge``,
  ``scout00``, ``native`` and ``pipeline.intake`` dropped. Rules 16 / 17 never fire (the oracle's Scout services
  answer no notice; ``normalise`` refuses an old answer that holds one), and the four Scout jobs are removed from
  the old ``JOBS`` in the oracle (they are never planned on either side).
* **(d) absent subsystems:** ``selfcheck``, ``build``, ``source_discovery``, ``job_runner.lock``,
  ``watch.failing_checks`` and the overview's ``backups``, ``integrity`` and ``releases`` become
  ``{"deferred": reason}``. Rules 5, 12, 19, 20, 21 and 22 are omitted: the worlds never trigger them, and
  ``normalise`` refuses an old answer that holds one.
* **(e) the jobs are the imported snapshot:** no runner is alive, so an imported ``running`` is ``interrupted``
  (the oracle's ``pid_alive`` answers ``False``: the old plan says the same); ``normalise`` refuses an old job still
  ``running`` (a pid-less record younger than 2 h, which the worlds do not hold).
* **(f) the paid switch:** a world's ``paid: false`` runs the old side with ``PZ_AI_PAID=off`` (the new default,
  ``PZ_AI_PAID`` not ``on``), ``paid: true`` with the switch unset (the new ``PZ_AI_PAID=on``); ``kill_switch`` is
  then the same on both sides. ``providers`` drops the old RESEARCH row (029a decision h: no RESEARCH role).
* **(g) the ledger role:** the worlds' ledger lines carry their old ``role``, as the imported rows do (the generated
  ``role`` column is ``detail->>'role'``): nothing to normalise here; the real parity checks it.
* **(k) no runner (revision 2):** rules 3, 4 and 6-11 take the new advice and group (``NEW_DO``, restated from the plan;
  level ``info``), then the verdict and the status are re-derived from the normalised issues by the OLD rules
  (``expected_verdict`` / ``expected_status``, written here independently of ``health.core`` and checked against
  every old answer first), with the two job-report sentences reworded.

``runner_check`` also compares ``system_view(..., runner=<a stub runner>)`` with the old payload normalised WITHOUT
(k): the old texts and groups come back exactly (032c's switch).

The worlds hold INVENTED names only (see ``WORLDS``). Exit 1 on any difference.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT
from projectzero.dealflow.ranking.names import norm_company
from projectzero.health import UNREADABLE, inputs_from_docs, overview_view, system_view
from projectzero.health import core as health_core
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js

ORACLE = REPO_ROOT / "scripts" / "oracle" / "health_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_health.json"
CLOCK = "2026-11-13T09:00:00"  # a Friday: the ISO week starts 2026-11-09, the month 2026-11-01
KEY_ENV = "DEEPINFRA_API_KEY"


# ------------------------------------------------------------------ the synthetic worlds (invented names only)
# fmt: off
def dumps(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True)  # the old appended lines


def jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(dumps(r) + "\n" for r in rows)


def src(sid: str, name: str, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"id": sid, "name": name, "url": f"https://{sid}.example.org/list", "kind": "watcher",
                            "parser": "page_diff", "geo": ["DE"], "sectors": ["ai_sw"], "stage": "pre_company",
                            "reliability": "medium", "freshness": "weekly", "enabled": True, "last_scan": "2026-11-10 06:00",
                            "last_ok": "2026-11-10 06:00", "last_result_count": 2, "failures_in_row": 0,
                            "yield": {"kept": 0, "research": 0, "rejected": 0}, "country": "Germany",
                            "geo_scope": "country"}
    return base | kw


def cand(cid: str, name: str, sid: str, decision: str = "new", tier: str = "grant", seen: str = "2026-11-02", **kw: Any) -> dict[str, Any]:
    """An inbox record as every real Deal Flow record carries it (``decision``, ``discovery_tier``, ``source_id``)."""
    return {"id": cid, "name": name, "description": f"{name}: invented industrial software", "decision": decision,
            "source": sid, "source_id": sid, "discovery_tier": tier, "first_seen": seen, "country": "DE", **kw}


def report(sid: str, status: str = "ok", note: str = "", count: int = 1, key: str = "source_id") -> dict[str, Any]:
    return {key: sid, "status": status, "note": note, "count": count}


def scan(finished: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    return {"run_id": finished[:10] + "T05:30:00", "scan_started": finished[:10] + "T05:30:00", "scan_finished": finished,
            "new": 2, "baseline": 0, "sources": sources}


def job(state: str, **kw: Any) -> dict[str, Any]:
    return {"state": state, "source": "background", **kw}


def run(at: str, job_id: str, label: str, outcome: str | None = "completed", ok: bool = True, note: str = "done", **kw: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"job": job_id, "label": label, "ok": ok, "note": note, "seconds": 1.5, "at": at,
                           "source": "background", **kw}
    if outcome is not None:
        row["outcome"] = outcome
    return row


def call(ts: str, model: str, outcome: str = "ok", usd: float = 0.0012, role: str = "CHEAP", **kw: Any) -> dict[str, Any]:
    return {"ts": ts, "call_id": f"call-{ts[5:16].replace(':', '').replace('-', '').replace('T', '')}-{model[-4:]}",
            "purpose": "triage", "role": role, "provider": "deepinfra", "model": model, "outcome": outcome,
            "usd": usd, "input_tokens": 1200, "output_tokens": 160, "cached": outcome == "cache_hit",
            "entity_id": None, "run_id": None, **kw}


FLASH = "deepseek-ai/DeepSeek-V4-Flash"
PRO = "deepseek-ai/DeepSeek-V4-Pro"
REGISTRY_DOCS = {"committee.json": {"second_pass": []}, "bridge_jobs.json": {"jobs": {}}, "people.json": {"people": []},
                 "events.json": {"events": [], "leads": []}, "native_scout.json": {"signals": []}}


def required(**docs: Any) -> dict[str, Any]:
    """Every file a real legacy folder holds (the importer refuses a folder without one), here empty."""
    base: dict[str, Any] = {
        "inbox.json": {"candidates": [], "last_run": "2026-11-10T06:12:40"},
        "real_data.json": {"week": "2026-W46", "signals": []},
        "sources.json": {"sources": []},
        "scout_intake.json": {"cycles": {}, "items": []},
        "triage_proposals.json": {"version": 1, "proposals": {}},
        "queue_routing.json": {"routes": {}},
        "schedule/jobs.json": {},
        "inference_ledger.jsonl": "",
        "schedule/runs.jsonl": "",
        **copy.deepcopy(REGISTRY_DOCS),
    }
    base.update(docs)
    return base


def trigger(tid: str, name: str, observed: str, **kw: Any) -> dict[str, Any]:
    return {"id": tid, "kind": "trigger", "name": name, "entity_key": norm_company(name), "predicate": "page_changed",
            "label": "official page changed", "first_observed": observed, "evidence": "invented evidence",
            "source_kind": "official_page", "url": f"https://{tid}.example.org", "high_value": False,
            "dedupe_key": f"dk-{tid}", **kw}


def news_event(eid: str, company: str, materiality: str, geo: list[str], themes: list[str], backcast: list[Any] | None = None) -> dict[str, Any]:
    """A stored News event as the old refresh wrote it (the shape ``oracle_news.json`` uses)."""
    headline = f"{company} raises an invented seed round"
    source = {"publisher": "Invented Wire A", "url": f"https://news.invented.example/{eid}", "published": "2026-11-05",
              "headline": headline, "text_sha": f"sha-{eid}", "independence": "independent"}
    return {"event_id": eid, "company": company, "entity_key": norm_company(company) or "", "company_from": "headline",
            "headline": headline, "summary": "", "event_type": "funding", "round": "seed", "amount_m": 4.0,
            "event_date": "2026-11-05", "geo": geo, "themes": themes, "noise": False, "sources": [source],
            "ingested_at": "2026-11-05T08:00:00", "backcast": backcast or [], "card": None, "materiality": materiality,
            "materiality_why": ["rule"]}


def news_docs(failed: list[str]) -> dict[str, Any]:
    runs: list[dict[str, Any]] = [
        {"at": "2026-11-11T06:00:00", "completed_at": "2026-11-11T06:01:02", "status": "ok", "trigger": "scheduled",
         "new": 2, "merged": 1, "sources_ok": 9, "sources_failed": [], "usd": 0.0041},
        {"at": "2026-11-12T06:00:00", "completed_at": "2026-11-12T06:01:30", "status": "partial" if failed else "ok",
         "trigger": "scheduled", "new": 3, "merged": 0, "sources_ok": 9 - len(failed), "sources_failed": failed,
         "usd": 0.00825},
    ]
    events = {
        "ev-1": news_event("ev-1", "Invented Kelpie Robotics", "HIGH", ["DE"], ["robotics"]),
        "ev-2": news_event("ev-2", "Invented Marlow Grid", "HIGH", ["DE"], ["climate"], backcast=[{"date": "2026-06", "precision": "month", "text": "an invented grant", "family": "grants", "url": "https://evidence.invented.example/grants", "kind": "known_early_signal"}]),
        "ev-3": news_event("ev-3", "Invented Ostler Bio", "HIGH", ["US"], ["ai"]),
        "ev-4": news_event("ev-4", "Invented Pennant Labs", "MEDIUM", ["FR"], ["ai"]),
        "ev-5": news_event("ev-5", "Invented Quayside AI", "HIGH", ["CH", "EU"], ["enterprise", "fintech"]),
    }
    metrics = {"at": "2026-11-12T06:05:00", "today": "2026-11-12", "windows": {"90": {"benchmark_events": 7, "sources": {
        "Invented Wire A": {"name": "Invented Wire A", "kind": "feed", "technical": {"state": "HEALTHY"}},
        "Invented Wire B": {"name": "Invented Wire B", "kind": "feed", "technical": {"state": "FAILING"}},
        "Invented Wire C": {"name": "Invented Wire C", "kind": "feed", "technical": {"state": "BLOCKED"}},
        "Invented Ticker": {"name": "Invented Ticker", "kind": "deal_flow_reuse", "technical": {"state": "UNKNOWN"}},
        "Invented Gazette": {"name": "Invented Gazette", "kind": "external", "technical": {"state": "NOT FETCHED"}},
    }}}}
    return {
        "news/runs.jsonl": jsonl(runs),
        "news/events.json": {"events": events, "seeded": []},
        "news/source_metrics.json": metrics,
        "news/source_state.json": {"Invented Wire B": {"state": "DEGRADED", "since": "2026-11-10"},
                                   "Invented Wire A": {"state": "ESTABLISHED", "since": "2026-09-01"}},
        "sources/network.json": {"candidates": {
            "nc-1": {"url": "https://harbour-gazette.invented.example/", "name": "Invented Harbour Gazette", "family": "news_publication", "state": "PROBATION"},
            "nc-2": {"url": "https://valley-post.invented.example/", "name": "Invented Valley Post", "family": "news_publication", "state": "DISCOVERED"},
            "nc-3": {"url": "https://alpine-daily.invented.example/", "name": "Invented Alpine Daily", "family": "news_publication", "state": "VALIDATING"},
            "nc-4": {"url": "https://grant-list.invented.example/", "name": "Invented Grant List", "family": "grants", "state": "PROBATION"},
        }},
    }


def ledger_main() -> list[dict[str, Any]]:
    """Calls across the 30-day window and its edges (since 2026-10-14; the 7-day cut 2026-11-06T09:00:00)."""
    return [
        call("2026-10-01T10:00:00", FLASH, usd=1.5),  # all time only
        call("2026-10-14T08:00:00", PRO, role="STANDARD", usd=0.75, latency_ms=4100),  # the first day in the window
        call("2026-10-20T11:00:00", FLASH, outcome="error", usd=0.0, error_kind="rate_limited"),
        call("2026-11-01T00:00:00", PRO, role="STANDARD", usd=6.25, latency_ms=5200),  # the month starts
        call("2026-11-03T12:00:00", FLASH, usd=4.0, latency_ms=900),
        call("2026-11-06T09:00:00", FLASH, usd=0.5, latency_ms=700),  # exactly 7 days back: in the 7-day figures
        call("2026-11-06T08:59:59", FLASH, usd=0.25, latency_ms=650),
        call("2026-11-08T23:59:59", PRO, role="STANDARD", usd=3.0, latency_ms=6100),  # the Sunday before the week
        call("2026-11-09T00:00:00", PRO, role="STANDARD", usd=2.5, latency_ms=4800),  # the week starts
        call("2026-11-10T10:00:00", FLASH, outcome="cache_hit", usd=0.0),
        call("2026-11-11T10:00:00", FLASH, outcome="blocked", usd=0.0),
        call("2026-11-12T10:00:00", FLASH, outcome="error", usd=0.002, error_kind="timeout"),
        call("2026-11-12T23:59:59", FLASH, usd=0.4, latency_ms=800),
        call("2026-11-13T00:00:00", FLASH, usd=1.2, latency_ms=1000),  # today starts
        call("2026-11-13T08:40:00", PRO, role="STANDARD", usd=2.0, latency_ms=5600),
        call("2026-11-13T08:41:00", "Qwen/Qwen3.5-9B", role="", usd=0.0, outcome="disabled"),
        {**call("2026-11-13T08:42:00", "", usd=0.0, outcome="error", error_kind=None), "model": None},
    ]  # month: 6.25 + 4 + 0.5 + 0.25 + 3 + 2.5 + 0.002 + 0.4 + 1.2 + 2 = 20.102


ALL_JOBS = ("watch_checks", "deal_flow_scan", "event_scan", "validation_snapshot", "news_refresh", "triage_retry",
            "news_weekly_review", "source_network", "triage_compression", "case_refresh", "news_source_review")


def fresh_jobs() -> dict[str, Any]:
    """Every job done recently enough that none is due at 2026-11-13 09:00."""
    last = {"triage_retry": "2026-11-13T08:30:00", "triage_compression": "2026-11-13T06:00:00"}
    return {j: job("ok", started=last.get(j, "2026-11-13T05:00:00"), finished=last.get(j, "2026-11-13T05:00:00"),
                   last_ok=last.get(j, "2026-11-13T05:00:00"), note="done", outcome="completed", seconds=2.0, error="",
                   fails_in_row=0, pid=7001) for j in ALL_JOBS}


def unrun_jobs() -> dict[str, Any]:
    """The imported jobs of the revision-2 worlds: overdue, failing twice, interrupted, budget-blocked, partial and
    waiting for an external dependency, plus a retired Scout job's record (never planned)."""
    return {
        "watch_checks": job("ok", started="2026-11-10T07:00:00", finished="2026-11-10T07:00:20", last_ok="2026-11-10T07:00:20",
                            note="1 new trigger(s) · 3 page(s) checked · 0 failure(s)", outcome="completed", seconds=20.0,
                            error="", fails_in_row=0, pid=7002),
        "event_scan": job("failed", started="2026-11-10T08:00:00", finished="2026-11-10T08:00:40", last_ok="2026-11-01T08:00:00",
                          note="failed: TimeoutError: the invented event feed timed out", outcome="failed", seconds=40.0,
                          error="TimeoutError: the invented event feed timed out", fails_in_row=2, pid=7003),
        "validation_snapshot": job("running", started="2026-11-10T21:55:00", last_ok="2026-11-09T22:00:00", note="",
                                   outcome="completed", seconds=1.0, error="", fails_in_row=0, pid=7004),
        "news_refresh": job("ok", started="2026-11-10T06:00:00", finished="2026-11-10T06:01:00", last_ok="2026-11-10T06:01:00",
                            note="PARTIAL · 3 new event(s) · 0 updated · 1 already known · 8 feed(s) ok · 1 failed · $0.0040",
                            outcome="partial", seconds=60.0, error="", fails_in_row=0, pid=7005),
        "news_weekly_review": job("ok", started="2026-11-09T05:00:00", finished="2026-11-09T05:00:03", last_ok="2026-11-02T05:00:00",
                                  note="skipped: the week budget limit is reached", outcome="budget_blocked", seconds=3.0,
                                  error="", fails_in_row=0, pid=7006),
        "source_network": job("ok", started="2026-11-10T09:00:00", finished="2026-11-10T09:00:02", last_ok="2026-11-10T09:00:02",
                              note="relay unavailable — awaiting the invented provider's answer", seconds=2.0, error="",
                              fails_in_row=0, pid=7007),
        "triage_compression": job("failed", started="2026-11-10T03:00:00", finished="2026-11-10T03:00:01",
                                  last_ok="2026-11-09T21:00:00", note="failed: ValueError: an invented route", outcome="failed",
                                  seconds=1.0, error="", fails_in_row=1, pid=7008),
        "news_source_review": job("ok", started="2026-10-20T05:00:00", finished="2026-10-20T05:00:09", last_ok="2026-10-20T05:00:09",
                                  note="0 material events · 0 lifecycle change(s) · 0 publication candidate(s) handed to the source network",
                                  outcome="no_findings", seconds=9.0, error="", fails_in_row=0, pid=7009),
        "scout00_inbox": job("failed", started="2026-11-01T05:00:00", note="failed: retired", outcome="failed",
                             error="RuntimeError: retired", fails_in_row=5, pid=7010),
    }


def unrun_runs() -> list[dict[str, Any]]:
    return [
        run("2026-11-10T06:01:00", "news_refresh", "News refresh", "partial", note="PARTIAL · 3 new event(s)"),
        run("2026-11-10T07:00:20", "watch_checks", "WATCH checks", note="1 new trigger(s)"),
        run("2026-11-10T08:00:40", "event_scan", "Event source scan", "failed", ok=False,
            note="failed: TimeoutError: the invented event feed timed out", error="TimeoutError: the invented event feed timed out"),
        run("2026-11-10T22:00:00", "*", "Job runner", "skipped",
            note="skipped — another run is in progress (app, pid 7004, since 2026-11-10T21:55:00)", seconds=0.0),
    ]


def failing_source() -> list[dict[str, Any]]:
    return [src("s-lab-listing", "Invented Lab Listing", failures_in_row=3, last_ok="2026-10-01 06:00"),
            src("s-founder-wire", "Invented Founder Wire")]


def unrun_world(with_source: bool) -> dict[str, Any]:
    sources = failing_source() if with_source else [src("s-founder-wire", "Invented Founder Wire")]
    reports = [report("s-lab-listing", "failed", "fetched but no entries matched the parser")] if with_source else []
    return required(**{
        "sources.json": {"sources": sources},
        "scan_history.json": {"scans": [scan("2026-11-10T06:12:40", [*reports, report("s-founder-wire")])]},
        "schedule/jobs.json": unrun_jobs(),
        "schedule/runs.jsonl": jsonl(unrun_runs()),
        "schedule/runner.json": {"background": {"at": "2026-11-10T22:00:00", "outcome": "skipped", "note": "skipped — another run is in progress"}},
        "event_health.json": {"scan_time": "2026-11-01 08:00", "totals": {}, "sources": []},
        "inference_ledger.jsonl": jsonl([call("2026-11-10T10:00:00", FLASH, usd=0.25, latency_ms=900)]),
    })


def main_docs() -> dict[str, Any]:
    sources = [
        src("s-policy-feed", "Invented Policy Feed", failures_in_row=3, last_ok="2026-10-20 06:00"),
        src("s-lab-listing", "Invented Lab Listing", failures_in_row=4, last_ok="2026-10-01 06:00"),
        src("s-grant-desk", "Invented Grant Desk", failures_in_row=2, last_ok=None),
        src("s-old-register", "Invented Old Register", last_ok="2026-10-01 06:00", last_scan="2026-11-10 06:00"),
        src("s-seed-wire", "Invented Seed Wire", failures_in_row=1, last_ok="2026-11-09 06:00"),
        src("s-new-board", "Invented New Board", last_scan=None, last_ok=None, last_result_count=None),
        src("s-founder-wire", "Invented Founder Wire", last_ok="2026-11-12 06:00"),
        src("s-retired-list", "Invented Retired List", enabled=False),
        src("s-cert-feed", "Invented Cert Feed", failures_in_row=5, last_ok="2026-09-01 06:00"),
        src("s-moved-page", "Invented Moved Page", failures_in_row=1, last_ok="2026-11-08 06:00"),
        src("s-busy-api", "Invented Busy API", failures_in_row=3, last_ok="2026-10-28 06:00"),
        src("s-flaky-host", "Invented Flaky Host", failures_in_row=2, last_ok="2026-11-07 06:00"),
        src("s-changed-feed", "Invented Changed Feed (Retired RSS)", failures_in_row=6, last_ok="2026-08-01 06:00"),
        src("s-odd-source", "Invented Odd Source", failures_in_row=1, last_ok="", last_scan="2026-11-10 06:00"),
        src("s-silent-list", "Invented Silent List", failures_in_row=3, last_ok="2026-10-10 06:00"),
        src("s-quiet-week", "Invented Quiet Week", last_ok="2026-10-23 06:00", last_result_count=0),  # 21 days: not stale
    ]
    reports = [
        report("s-policy-feed", "failed", "HTTP Error 403: Forbidden"),
        report("Invented Lab Listing", "failed", "fetched but no entries matched the parser", key="source"),
        report("s-grant-desk", "failed", "<urlopen error [Errno 11001] getaddrinfo failed>"),
        report("s-old-register", "ok", "", 0),
        report("s-seed-wire", "failed", "The read operation timed out"),
        report("s-cert-feed", "failed", "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"),
        report("s-moved-page", "failed", "HTTP Error 404: Not Found"),
        report("s-busy-api", "failed", "HTTP Error 429: Too Many Requests"),
        report("s-flaky-host", "failed", "HTTP Error 502: Bad Gateway"),
        report("s-changed-feed", "failed", "the publisher no longer offers this feed (external change)"),
        report("s-odd-source", "failed", "an invented, unexplained answer"),
        report("s-founder-wire", "ok", "", 7),
    ]
    wire = [cand(f"c-{i:03d}", f"Invented Wire Co {i}", "s-founder-wire", tier="pre_company" if i % 3 == 0 else "grant",
                 seen=f"2026-11-{i:02d}", noise=i % 4 == 0, all_source_ids=["s-founder-wire"]) for i in range(1, 13)]
    candidates = [
        *wire,
        cand("c-101", "Invented Lab Spinout", "s-lab-listing", all_source_ids=["s-lab-listing", "s-founder-wire"], seen="2026-10-02"),
        cand("c-102", "Invented Watch Co", "s-seed-wire", decision="watch", seen="2026-10-12"),
        cand("c-103", "Invented Second Watch", "s-seed-wire", decision="watch"),
        cand("c-104", "Invented Future Date", "s-seed-wire", seen="2026-12-01"),  # a Validation data warning
        cand("c-105", "Invented Pending One", "s-old-register"),
        cand("c-106", "Invented Pending Two", "s-old-register"),
        cand("c-107", "Invented Proposed", "s-old-register"),
        cand("c-108", "Invented Kept Co", "s-old-register", decision="kept"),
        cand("c-109", "Invented Rejected Co", "s-old-register", decision="rejected", noise=True),
    ]
    signals = [
        {"company": "Invented Arclight Systems", "status": "new", "scores": {}, "sent_to_omar": "2026-11-10"},
        {"company": "Invented Brindle Works", "status": "contacted", "scores": {}},
        {"company": "Invented Corvid Labs", "status": "new", "scores": {}, "sent_to_omar": ""},
        {"company": "Invented Dalby Air", "status": "dropped", "scores": {}, "sent_to_omar": "2026-10-01"},
        {"company": "Invented Ember Rail", "scores": {}},
    ]
    jobs = {
        "watch_checks": job("ok", started="2026-11-13T07:00:00", finished="2026-11-13T07:00:30", last_ok="2026-11-13T07:00:30",
                            note="2 new trigger(s) · 3 page(s) checked · 0 failure(s)", outcome="completed", seconds=30.0,
                            error="", fails_in_row=0, pid=7101),
        "deal_flow_scan": job("ok", started="2026-11-03T05:30:00", finished="2026-11-03T06:00:00", last_ok="2026-11-03T06:00:00",
                              note="4 genuinely new · 0 baseline", outcome="completed", seconds=1800.0, error="", fails_in_row=0, pid=7102),
        **{k: v for k, v in unrun_jobs().items() if k in ("event_scan", "validation_snapshot", "news_refresh", "news_weekly_review",
                                                         "source_network", "triage_compression", "news_source_review", "scout00_inbox")},
        "triage_retry": job("ok", started="2026-11-13T08:30:00", finished="2026-11-13T08:30:05", last_ok="2026-11-13T08:30:05",
                            note="2 retried · 0 left", seconds=5.0, error="", fails_in_row=0, pid=7103),
        "native_scout": job("running", started="2026-11-13T08:55:00", pid=7104, note=""),
    }
    runs = [
        run("2026-10-01T05:00:00", "deal_flow_scan", "Deal Flow scan", None, note="3 genuinely new · 0 baseline"),  # before the window
        run("2026-10-14T09:00:00", "watch_checks", "WATCH checks", None, note="0 new trigger(s)"),  # the window's first second
        run("2026-10-20T05:00:09", "news_source_review", "News source comparison (monthly)", None, ok=False, note="failed: OSError"),
        run("2026-10-25T05:00:00", "watch_checks", "", "no_findings", note="0 new trigger(s)"),
        {**run("2026-10-26T05:00:00", "", "Unnamed", "completed"), "job": ""},  # no job: never listed
        run("2026-11-03T06:00:00", "deal_flow_scan", "Deal Flow scan", note="4 genuinely new · 0 baseline", seconds=1800.0),
        run("2026-11-09T05:00:03", "news_weekly_review", "Weekly learning review", "budget_blocked",
            note="skipped: the week budget limit is reached"),
        run("2026-11-10T03:00:01", "triage_compression", "Triage queue compression (human attention budget)", "failed",
            ok=False, note="failed: ValueError: an invented route", error="ValueError: an invented route"),
        run("2026-11-10T09:00:02", "source_network", "New-source discovery & probation", "waiting_external",
            note="relay unavailable — awaiting the invented provider's answer"),
        run("2026-11-12T22:00:00", "*", "Job runner", "skipped", note="skipped — another run is in progress (app, pid 7004)", seconds=0.0),
        run("2026-11-13T07:00:30", "watch_checks", "WATCH checks", "completed", note="2 new trigger(s) · " + "x" * 420),
        run("2026-11-13T08:30:05", "triage_retry", "Machine triage retry (after a provider outage)", "completed", note="2 retried · 0 left"),
    ]
    return required(**{
        "sources.json": {"sources": sources},
        "scan_history.json": {"scans": [scan("2026-11-03T06:00:00", [report("s-founder-wire")]), scan("2026-11-10T06:12:40", reports)]},
        "inbox.json": {"candidates": candidates, "last_run": "2026-11-10T06:12:40"},
        "triage_proposals.json": {"version": 1, "proposals": {
            "c-107": {"status": "proposed", "proposal": "KEEP", "proposed_at": "2026-11-10T07:00:00"},
            "c-106": {"status": "failed", "error_kind": "invalid_json", "error": "the reply was not JSON"}}},
        "shadow_triage/auto_runs.json": {"runs": [
            {"started": "2026-11-03T06:00:05", "finished": "2026-11-03T06:02:00", "state": "partial", "selected": 3,
             "pending": [{"id": "c-107", "reason": "provider overloaded"}], "failed": []},
            {"started": "2026-11-10T06:13:00", "finished": "2026-11-10T06:15:00", "state": "partial", "selected": 4,
             "pending": [{"id": "c-105", "reason": "provider overloaded (engine_overloaded)"}],
             "failed": [{"id": "c-106", "reason": "the reply was not JSON"}]},
        ]},
        "shadow_triage/retry_state.json": {
            "c-105": {"attempts": 1, "category": "RETRYABLE", "reason": "provider overloaded", "next_eligible": "2026-11-10T06:30:00"},
            "c-106": {"attempts": 6, "category": "NON_RETRYABLE", "reason": "the reply was not JSON", "next_eligible": None}},
        "research_questions.json": {"questions": {"q-1": {"status": "open", "text": "Is the invented pilot paid?"},
                                                  "q-2": {"status": "answered"}, "q-3": {"status": "open"}, "q-4": {}}},
        "watch/targets.json": {"targets": {
            norm_company("Invented Manual Target"): {"name": "Invented Manual Target", "urls": ["https://target.example.org/news"],
                                                    "checks": {"https://target.example.org/news": {"failures_in_row": 1}}, "active": True},
            norm_company("Invented Watch Co"): {"name": "Invented Watch Co", "urls": [], "checks": {}},
            norm_company("Invented Paused Target"): {"name": "Invented Paused Target", "active": False}}},
        "watch/triggers.jsonl": jsonl([
            trigger("t-1", "Invented Watch Co", "2026-11-11T07:00:00"),
            trigger("t-2", "Invented Watch Co", "2026-11-12T07:00:00"),
            trigger("t-3", "Invented Manual Target", "2026-11-12T07:00:00"),
            trigger("t-4", "Invented Unwatched Co", "2026-11-12T07:00:00"),
            {"kind": "status", "trigger_id": "t-2", "status": "dismissed", "at": "2026-11-12T08:00:00"},
        ]),
        "schedule/jobs.json": jobs,
        "config.json": {"catch_up": {"intervals_h": {"deal_flow_scan": 72, "news_refresh": "daily"}}},
        "event_health.json": {"scan_time": "2026-11-12 05:00", "totals": {}, "sources": []},
        "schedule/runs.jsonl": jsonl(runs),
        "schedule/runner.json": {"app": {"at": "2026-11-12T22:00:00", "outcome": "skipped", "note": "skipped — another run is in progress"},
                                 "background": {"at": "2026-11-13T08:30:00", "started": "2026-11-13T08:30:00",
                                                "finished": "2026-11-13T08:30:05", "outcome": "ok", "ran": 1, "failed": 0}},
        "inference_ledger.jsonl": jsonl(ledger_main()),
        "validation/snapshots.jsonl": jsonl([{"date": "2026-11-10", "candidates": 20}, {"date": "2026-11-11", "candidates": 21},
                                             {"date": "2026-11-12", "candidates": 21}]),
        **news_docs(["Invented Wire B: HTTP 500", "Invented Wire C: HTTP 403"]),
        "real_data.json": {"week": "2026-W46", "signals": signals},
        "queue_routing.json": {"at": "2026-11-12T23:05:10", "counts": {"NEEDS_MOHAMED": 2, "CASE_PREPARING": 1, "MACHINE_WATCH": 3},
                               "routes": {"c-105": {"state": "NEEDS_MOHAMED", "priority": 1}}},
        "scout_intake.json": {"cycles": {}, "items": [{"id": "si-1", "status": "promoted", "name": "Invented Scout Lead"},
                                                      {"id": "si-2", "status": "pending", "name": "Invented Scout Two"}]},
        "search_bridge_production.json": {"requests": [{"at": "2026-11-12T10:00:00", "ok": True}], "by_day": {"2026-11-12": 0.05}},
        "native_scout.json": {"signals": [], "runs": [{"at": "2026-11-12T10:00:00", "hypotheses": 2, "counts": {"INVESTIGATE": 1}}]},
    })


def attention_docs() -> dict[str, Any]:
    """NEEDS ATTENTION with a fresh report: one Project Zero side failing source and the month spend exactly at 80 %."""
    return required(**{
        "sources.json": {"sources": failing_source()},
        "scan_history.json": {"scans": [scan("2026-11-12T06:00:00", [report("s-lab-listing", "failed", "XML parse error at line 1"),
                                                                     report("s-founder-wire")])]},
        "schedule/jobs.json": fresh_jobs(),
        "schedule/runs.jsonl": jsonl([run("2026-11-13T08:30:05", "triage_retry", "Machine triage retry (after a provider outage)")]),
        "inference_ledger.jsonl": jsonl([call("2026-11-02T10:00:00", PRO, role="STANDARD", usd=12.5, latency_ms=5000),
                                         call("2026-11-10T10:00:00", PRO, role="STANDARD", usd=7.5, latency_ms=5100)]),  # 20.00
        **news_docs([]),
    })


def limited_docs() -> dict[str, Any]:
    """FYI with a fresh report: external limitations and notes only; the last scan 11 days ago (old: a warning)."""
    return required(**{
        "sources.json": {"sources": [src("s-policy-feed", "Invented Policy Feed", failures_in_row=4, last_ok="2026-10-01 06:00"),
                                     src("s-founder-wire", "Invented Founder Wire", last_ok="2026-11-02 06:00")]},
        "scan_history.json": {"scans": [scan("2026-11-02T08:59:00", [report("s-policy-feed", "failed", "HTTP Error 401: Unauthorized"),
                                                                     report("s-founder-wire")])]},
        "inbox.json": {"candidates": [cand("c-1", "Invented Waiting Co", "s-founder-wire"),
                                      cand("c-2", "Invented Ahead Co", "s-founder-wire", seen="2026-11-20")]},
        "shadow_triage/auto_runs.json": {"runs": [{"started": "2026-11-02T09:00:00", "finished": "2026-11-02T09:01:00",
                                                   "state": "partial", "pending": [{"id": "c-1", "reason": "provider overloaded"}],
                                                   "failed": []}]},
        "shadow_triage/retry_state.json": {"c-1": {"attempts": 2, "category": "RETRYABLE", "next_eligible": "2026-11-13T09:15:00"}},
        "schedule/jobs.json": fresh_jobs(),
        "schedule/runs.jsonl": jsonl([run("2026-11-13T03:00:01", "triage_compression", "Triage queue compression (human attention budget)")]),
        **news_docs(["Invented Wire B: HTTP 500"]),
    })


def healthy_docs() -> dict[str, Any]:
    """HEALTHY: no issue at all (the last scan 10 days and some hours ago is not 'over 10 days')."""
    return required(**{
        "sources.json": {"sources": [src("s-founder-wire", "Invented Founder Wire", last_ok="2026-11-03 06:00"),
                                     src("s-retired-list", "Invented Retired List", enabled=False),
                                     src("s-new-board", "Invented New Board", last_scan=None, last_ok=None)]},
        "scan_history.json": {"scans": [scan("2026-11-03T06:00:00", [report("s-founder-wire")])]},
        "inbox.json": {"candidates": [cand("c-1", "Invented Calm Co", "s-founder-wire", decision="kept")]},
        "schedule/jobs.json": fresh_jobs(),
        "schedule/runs.jsonl": jsonl([run("2026-11-13T08:30:05", "triage_retry", "Machine triage retry (after a provider outage)")]),
        "inference_ledger.jsonl": jsonl([call("2026-11-05T10:00:00", FLASH, usd=3.2, latency_ms=800)]),
        "validation/snapshots.jsonl": jsonl([{"date": "2026-11-12", "candidates": 1}]),
        "news/runs.jsonl": jsonl([{"at": "2026-11-12T06:00:00", "completed_at": "2026-11-12T06:01:00", "status": "ok",
                                   "sources_ok": 9, "sources_failed": [], "usd": 0.002}]),
    })


def empty_docs() -> dict[str, Any]:
    return required()


# name -> (documents, clock, paid, key present)
WORLDS: dict[str, tuple[Callable[[], dict[str, Any]], str, bool, bool]] = {
    "main": (main_docs, CLOCK, False, False),
    "attention": (attention_docs, CLOCK, True, True),
    "limited": (limited_docs, CLOCK, False, True),
    "healthy": (healthy_docs, CLOCK, True, True),
    "jobs_unrun": (lambda: unrun_world(True), CLOCK, True, True),
    "jobs_only": (lambda: unrun_world(False), CLOCK, True, True),
    "empty": (empty_docs, CLOCK, False, True),
}
# fmt: on


# ------------------------------------------------------------------ the oracle
def files_of(docs: dict[str, Any]) -> dict[str, bytes]:
    return {
        k: (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=2)).encode("utf-8")
        for k, v in docs.items()
    }


def oracle_over(worlds: dict[str, tuple[dict[str, bytes], str, bool, bool]]) -> dict[str, Any]:
    """The old reads once per world, over a scratch data folder holding the world's files byte for byte."""
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-health-oracle-") as tmp:
        data = Path(tmp) / "data"
        for name, (files, _clock, _paid, _key) in worlds.items():
            folder = data / name
            folder.mkdir(parents=True)
            for rel, raw in files.items():
                target = (folder / rel).resolve()
                if folder.resolve() not in target.parents:
                    raise SystemExit(f"refusing a path outside the scratch folder: {rel}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
        srcf, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
        inp = {"worlds": [{"name": n, "clock": c, "paid": p, "key": k} for n, (_f, c, p, k) in worlds.items()]}
        srcf.write_bytes(json.dumps(inp, ensure_ascii=False).encode("utf-8"))
        env = {k: v for k, v in os.environ.items() if k != "SUPABASE_DB_URL" and not k.endswith(("_API_KEY", "_TOKEN"))}
        env.pop("PZ_AI_PAID", None)
        env.update({"PZ_DATA": str(data), "PZ_TESTING": "1", "PYTHONPATH": str(OLD_REPO / "backend" / "src")})
        res = subprocess.run([str(python), str(ORACLE), str(srcf), str(dst)], env=env, capture_output=True, text=True)
        if res.returncode != 0:
            raise SystemExit(f"oracle failed:\n{res.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_bytes().decode("utf-8"))
        return out


# ------------------------------------------------------------------ the declared differences
RETIRED_RULES = ("the search bridge", "Scout 00")  # rules 16 / 17 would carry the stubs' notice; they answer none
OMITTED = (  # rules 5, 12, 19, 20, 21, 22: their texts' fixed parts
    "WATCH page check(s) keep failing",
    "the job runner has been busy for ",
    " new source(s) degraded",
    "The interface is older than the code",
    "DEGRADED: ",
    " stored record(s) could not be interpreted — skipped safely",
)


# decision (k): revision 2's table (``032a-health-plan.md``), restated here so the new texts are checked, not copied
NEW_DO = {
    1: "Open Sources health below: each has a diagnosis.",  # (c), with or without a runner
    3: "Finding new candidates arrives with the scan port; the last scan is the imported one.",
    4: "Preserved, nothing was lost. The machine-triage retry arrives with the background-job runner.",
    6: "The background-job runner is not ported yet: these jobs do not run, and Run overdue now is unavailable until it is.",
    7: "Recorded in the imported job history; nothing retries it until the runner is ported. Open Background jobs below for the error.",
    8: "Recorded in the imported job history; nothing runs it again until the runner is ported.",
    9: "Recorded in the imported job history; caps are never overridden, and nothing retries it until the runner is ported. Review spend under Models and budget.",
    10: "Recorded in the imported job history; the rest is not retried until the runner is ported.",
    11: "Recorded in the imported job history; nothing checks it again until the runner is ported.",
}
NEW_UNKNOWN = "The background-job runner is not ported yet: no job has run since the imported snapshot (last report {at}). The job figures below are that snapshot."
NEW_NO_REPORT = "The background-job runner is not ported yet: the imported snapshot holds no job report. The job figures below are that snapshot."  # H-306
NEW_SUFFIX = " The background-job runner is not ported yet; the job figures are the imported snapshot."


def rule_of(i: dict[str, str]) -> int | None:
    """Which old rule wrote this issue (by its fixed text), for the reworded rules 1, 3, 4 and 6-11."""
    what = i["what"]
    if what.endswith(" source(s) failing for a reason Project Zero can fix (parser / address)"):
        return 1
    if what in ("no Deal Flow scan in over 10 days", "no Deal Flow scan yet"):
        return 3
    if what.endswith(" candidate(s) waiting for machine triage — preserved, nothing was lost"):
        return 4
    for n, start in ((6, None), (7, "background job keeps failing: "), (8, "background job(s) failed or were interrupted: "),
                     (9, "background job blocked by a budget limit: "), (10, "background job(s) only partially completed: "),
                     (11, "waiting for an external dependency: ")):  # fmt: skip
        if start is None and " background job(s) overdue: " in what:
            return n
        if start is not None and what.startswith(start):
            return n
    return None


def expected_verdict(issues: list[dict[str, str]]) -> str:
    """The old verdict rule, restated: 3+ actionable warnings, a DEGRADED part, any actionable warning, any issue."""
    warns = [i for i in issues if i["level"] == "warn"]
    degraded = [i for i in warns if i["what"].startswith("DEGRADED:")]
    actionable = len(warns) - len(degraded)
    if actionable >= 3:
        return "UNHEALTHY"
    if degraded:
        return "DEGRADED"
    if actionable:
        return "NEEDS ATTENTION"
    return "FYI — EXTERNAL LIMITATIONS" if issues else "HEALTHY"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def expected_status(verdict: str, issues: list[dict[str, str]], old: dict[str, Any], *, runner: bool) -> dict[str, Any]:
    """The old status rule, restated over ``issues``; ``old`` gives the report and its age (the same clock). Without a
    runner (decision k) the two job-report sentences are the new ones."""
    n = {g: sum(1 for i in issues if i.get("group") == g) for g in ("need", "auto", "ext", "info")}
    age, report_ = old["report_age_h"], old["last_job_report"]
    stale = age is not None and age > 6
    if verdict in ("NEEDS ATTENTION", "UNHEALTHY"):
        key, label = "action", "Action required"
        sentence = f"{plural(n['need'], 'item')} need{'s' if n['need'] == 1 else ''} you — see Needs your action."
    elif verdict == "DEGRADED":
        key, label = "degraded", "Degraded"
        sentence = "A part of Project Zero is degraded; everything else keeps working. Details under Needs your action."
    elif age is None or stale:
        key, label = "unknown", "Status unknown"
        if runner:
            sentence = (
                "No background job has reported yet"
                if age is None
                else f"No background job has reported for {age:.0f} h"
            ) + " — the figures below may be stale. Is the computer asleep or the background task disabled?"
        elif age is None:
            sentence = NEW_NO_REPORT
        else:  # the report's minute, as written in the old line
            at = report_.replace("T", " ")[:16]
            sentence = NEW_UNKNOWN.format(at=at)
    elif n["auto"] or n["ext"] or n["info"]:
        key, label = "limited", "Operational with limitations"
        parts = ([plural(n["ext"], "external limitation")] if n["ext"] else []) + \
            ([f"{plural(n['auto'], 'item')} handled automatically"] if n["auto"] else []) + \
            ([plural(n["info"], "note")] if n["info"] else [])  # fmt: skip
        sentence = "Project Zero is running normally and nothing needs you. " + " · ".join(parts).capitalize() + "."
    else:
        key, label, sentence = "ok", "Operational", "Project Zero is running normally and nothing needs you."
    if key in ("action", "degraded") and stale:
        sentence += f" No background job has reported for {age:.0f} h." if runner else NEW_SUFFIX
    return {
        "key": key,
        "label": label,
        "sentence": sentence,
        "groups": n,
        "last_job_report": report_,
        "report_age_h": age,
    }


def normalise_system(body: dict[str, Any], *, runner: bool = False) -> dict[str, Any]:
    """The old ``system()`` payload -> the expected new one (declared c, d, e, f, k; g needs nothing here)."""
    old = copy.deepcopy(body)
    for i in old["issues"]:
        if any(x in i["what"] for x in OMITTED):
            raise ValueError(f"an omitted rule fired in the oracle (the world must not trigger it): {i['what']}")
        if any(x in i["what"] or x in i["do"] for x in RETIRED_RULES):
            raise ValueError(f"a retired Scout notice reached the issues: {i['what']}")
    if any(j["state"] == "running" for j in old["jobs"]):
        raise ValueError("an old job is still running (decision e needs a pid-less record younger than 2 h)")
    # the restated rules reproduce the old answer before anything is changed
    assert expected_verdict(old["issues"]) == old["verdict"], "expected_verdict differs from the old verdict"
    assert expected_status(old["verdict"], old["issues"], old["status"], runner=True) == old["status"], (
        "expected_status"
    )
    issues = []
    for i in old["issues"]:
        rule = rule_of(i)
        if rule == 1:  # (c): the repair research job is retired
            i = {**i, "do": NEW_DO[1]}
        elif i["what"].startswith("paid AI is switched off ("):  # (f): the new switch's advice (rule 15)
            assert i["do"] == "Intentional? Unset it to resume machine triage.", i["do"]
            i = {**i, "do": health_core.PAID_OFF_DO}
        elif rule is not None and not runner:  # (k)
            i = {"level": "info", "what": i["what"], "do": NEW_DO[rule], "group": "info"}
        issues.append(i)
    verdict = expected_verdict(issues)
    out: dict[str, Any] = {}
    for k, v in old.items():
        if k == "verdict":
            v = verdict
        elif k == "status":
            v = expected_status(verdict, issues, old["status"], runner=runner)
        elif k == "issues":
            v = issues
        elif k == "sources":  # (c)
            for row in v["sources"]:
                if "repair" in row:
                    row["repair"].pop("bridge_job", None)
        elif k == "watch":  # (d)
            v = {**v, "failing_checks": health_core.deferred(health_core.WATCH_CHECKS_DEFERRED)}
        elif k == "job_runner":  # (d)
            v = {**v, "lock": health_core.deferred(health_core.LOCK_DEFERRED)}
        elif k == "providers":  # (f) / 029a decision h
            v = [p for p in v if p["role"] != "RESEARCH"]
        elif k == "build":
            v = health_core.deferred(health_core.BUILD_DEFERRED)
        elif k == "selfcheck":
            v = health_core.deferred(health_core.SELFCHECK_DEFERRED)
        elif k == "source_discovery":
            v = health_core.deferred(health_core.SOURCE_DISCOVERY_DEFERRED)
        out[k] = v
    return out


def normalise_overview(body: dict[str, Any]) -> dict[str, Any]:
    """The old ``overview()`` payload -> the expected new one (declared c, d)."""
    out: dict[str, Any] = {}
    for k, v in copy.deepcopy(body).items():
        if k in ("search_bridge", "scout00", "native"):  # (c)
            continue
        if k == "pipeline":  # (c)
            v.pop("intake")
        elif k == "backups":  # (d)
            v = health_core.deferred(health_core.BACKUPS_DEFERRED)
        elif k == "integrity":
            v = health_core.deferred(health_core.INTEGRITY_DEFERRED)
        elif k == "releases":
            v = health_core.deferred(health_core.RELEASES_DEFERRED)
        out[k] = v
    return out


def normalise(expected: dict[str, Any], *, runner: bool = False) -> dict[str, Any]:
    """The ONE place the declared differences are applied: the old answers of a world -> the expected new ones."""
    out: dict[str, Any] = {}
    for route, fn in (("system", lambda b: normalise_system(b, runner=runner)), ("overview", normalise_overview)):
        old = expected[route]
        out[route] = {"ok": fn(old["ok"])} if "ok" in old else {"raises": old["raises"].split(":")[0]}
    return out


# ------------------------------------------------------------------ the new side
class StubRunner:
    """A runner whose recorded processes are all gone (the oracle's ``pid_alive``): 032c's switch, for the check."""

    def pid_alive(self, pid: Any) -> bool:
        return False


def as_read(docs: dict[str, Any]) -> dict[str, Any]:
    """The documents as the readers see them: a JSON document given as raw TEXT (a file that does not parse) is
    ``UNREADABLE``; the JSONL logs are their text."""
    return {k: UNREADABLE if isinstance(v, str) and not k.endswith(".jsonl") else v for k, v in docs.items()}


def _answer(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return {"ok": js(fn())}
    except Exception as exc:  # the old route would have answered 500
        return {"raises": type(exc).__name__}


def new_side(
    docs: dict[str, Any], clock: str, paid: bool, key: bool, runner: Any = None
) -> tuple[dict[str, Any], list[str]]:
    """The new answers and the purity invariants."""
    now = datetime.fromisoformat(clock)
    docs_before = copy.deepcopy(docs)
    problems: list[str] = []
    inputs = inputs_from_docs(as_read(docs), now.date(), now, paid=paid, keys={KEY_ENV: key})
    inputs_before = copy.deepcopy(inputs)
    got = {
        "system": _answer(lambda: system_view(inputs, now, runner)),
        "overview": _answer(lambda: overview_view(inputs, now)),
    }
    if inputs != inputs_before:
        problems.append("/inputs: health changed its inputs")
    if docs != docs_before:
        problems.append("/docs: inputs_from_docs changed the documents")
    return got, problems


def _text(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def compare_world(name: str, w: dict[str, Any], *, runner: bool = False) -> list[str]:
    expected = w["expected"]
    problems: list[str] = []
    for k in ("changed", "blocked"):
        if expected.get(k):
            problems.append(f"/{name}/{k}: the OLD read wrote {expected[k]}")
    try:
        want = js(normalise(expected, runner=runner))
    except (ValueError, AssertionError) as exc:
        return [*problems, f"/{name}: {exc}"]
    got, invariants = new_side(w["docs"], w["clock"], w["paid"], w["key"], StubRunner() if runner else None)
    problems += [f"/{name}{p}" for p in invariants]
    for route in ("system", "overview"):
        problems += [f"/{name}/{route}{p}" for p in diff(want[route], got[route])]
        if _text(want[route]) != _text(got[route]):
            problems.append(f"/{name}/{route}: the serialized answer differs (key order)")
    return problems


def compare_goldens(golden: dict[str, Any], *, runner: bool = False) -> list[str]:
    problems: list[str] = []
    for name, w in golden["worlds"].items():
        problems += compare_world(name, w, runner=runner)
    return problems


def summary(golden: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, w in golden["worlds"].items():
        e = w["expected"]
        body = e["system"].get("ok") or {}
        st = body.get("status") or {}
        new = js(normalise(e))["system"].get("ok") or {}
        out[name] = {
            "old": [body.get("verdict"), st.get("key"), st.get("groups"), len(body.get("issues") or [])],
            "new": [
                new.get("verdict"),
                (new.get("status") or {}).get("key"),
                (new.get("status") or {}).get("sentence"),
            ],
            "jobs": {j["id"]: [j["state"], j["outcome"], j["overdue"]] for j in body.get("jobs") or []},
            "sources": (body.get("sources") or {}).get("counts"),
            "coverage": (body.get("coverage") or {}).get("available"),
            "held": e.get("held"),
            "skipped": e.get("skipped"),
            "raises": [e[r].get("raises") for r in ("system", "overview")],
        }
    return out


def read_golden(path: Path = GOLDEN) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(path.read_bytes().decode("utf-8"))
    return out


def write_goldens() -> int:
    worlds = {name: (fn(), clock, paid, key) for name, (fn, clock, paid, key) in WORLDS.items()}
    oracle = oracle_over({n: (files_of(d), c, p, k) for n, (d, c, p, k) in worlds.items()})
    by_name = {w.pop("name"): w for w in oracle["worlds"]}
    golden = {
        "provenance": oracle["meta"],
        "worlds": {
            n: {"clock": c, "paid": p, "key": k, "docs": d, "expected": by_name[n]}
            for n, (d, c, p, k) in worlds.items()
        },
    }
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    # NOT sort_keys: the documents' insertion order is part of the input (and of what the oracle recorded)
    GOLDEN.write_bytes((json.dumps(golden, ensure_ascii=False, indent=None) + "\n").encode("utf-8"))
    return report_(read_golden(), "HEALTH GOLDENS")


def report_(golden: dict[str, Any], label: str) -> int:
    problems = compare_goldens(golden)
    with_runner = compare_goldens(golden, runner=True)
    print(json.dumps({"golden": str(GOLDEN), "bytes": GOLDEN.stat().st_size, "old": golden["provenance"],
                      "summary": summary(golden)}, indent=1, ensure_ascii=False))  # fmt: skip
    for p in problems[:60]:
        print("  DIFF", p)
    for p in with_runner[:60]:
        print("  DIFF (runner)", p)
    print(
        f"{label} RUNNER SWITCH MATCH (0 differences)"
        if not with_runner
        else f"{label} RUNNER SWITCH DIFFER ({len(with_runner)})"
    )
    print(f"{label} MATCH (0 differences)" if not problems else f"{label} DIFFER ({len(problems)})")
    return 1 if problems or with_runner else 0


def real() -> int:  # pragma: no cover - for the main session: needs the hosted database, the reader and the routes
    """The real snapshot imported by the production importer into a throw-away schema, through
    ``GET /api/system_health`` and ``GET /api/system_health_overview`` at the pinned ``CLOCK``, against the OLD reads
    over a byte-exact copy at the same clock (the same paid switch and key presence on both sides, read from this
    environment), then ``normalise`` and the value / text comparison as in ``compare_world``. Every table is checked
    unchanged by the reads. Aggregates only are printed (no name, no key)."""
    import secrets as _secrets

    from fastapi.testclient import TestClient
    from psycopg import sql as _sql

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.core.inference import config as _icfg
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot
    from projectzero.ops.parity_founder_calls import utc_instant
    from projectzero.ops.parity_validation import _fingerprint

    load_dotenv()
    settings = Settings.from_env()
    paid = _icfg.paid_enabled(os.environ)
    key = bool(str(os.environ.get(KEY_ENV) or "").strip())
    snapshot_ = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    files = {f.path: f.raw for f in snapshot_.files()}
    old = oracle_over({"real": (files, CLOCK, paid, key)})["worlds"][0]
    problems = [f"/old/{k}: the OLD read wrote {old[k]}" for k in ("changed", "blocked") if old.get(k)]
    schema = f"pz_rehearse_{_secrets.token_hex(4)}"
    report_: dict[str, Any] = {}
    inbox_delta: dict[str, int] = {}
    admin = connect(settings.db_url, autocommit=True)
    try:
        admin.execute(_scratch_sql(schema).encode())
        conn = connect(settings.db_url)
        try:
            applied = apply_plan(build_plan(snapshot_), schema=schema, conn=conn)
            assert applied.get("applied"), applied
        finally:
            conn.close()
        with transaction(settings.db_url) as c:
            before = _fingerprint(c, schema)
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: utc_instant(CLOCK)
        got: dict[str, Any] = {}
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            for route, path in (("system", "/api/system_health"), ("overview", "/api/system_health_overview")):
                r = client.get(path)
                got[route] = {"ok": js(r.json())} if r.status_code == 200 else {"raises": str(r.status_code)}
            listed = Counter(
                str(c.get("decision") or "") for c in client.get("/api/deal-flow/inbox").json()["candidates"]
            )
        with transaction(settings.db_url) as c:
            after = _fingerprint(c, schema)
        try:
            want = js(normalise(old))
            # declared (l), Codex H-309: the "You: review" counts are the Deal Flow inbox's (its own route, same data):
            # the merged candidates, absorbed records once, the Scout-only candidates the merge brought in
            old_inbox = want["overview"]["ok"]["pipeline"]["inbox"]
            want["overview"]["ok"]["pipeline"]["inbox"] = dict(listed)
            inbox_delta = {k: listed.get(k, 0) - old_inbox.get(k, 0) for k in sorted({*listed, *old_inbox})}
        except (ValueError, AssertionError) as exc:
            want = {}
            problems.append(f"/normalise: {exc}")
        for route in ("system", "overview") if want else ():
            problems += [f"/{route}{p}" for p in diff(want[route], got[route])]
            if _text(want[route]) != _text(got[route]):
                problems.append(f"/{route}: the serialized answer differs (key order)")
        changed = sorted(t for t in before if before[t] != after.get(t))
        if changed:
            problems.append(f"/stored: a health read changed {changed}")
        body = got["system"].get("ok") or {}
        ov = got["overview"].get("ok") or {}
        report_ = {"clock": CLOCK, "paid": paid, "key_set": key, "verdict": body.get("verdict"),
                   "status": (body.get("status") or {}).get("key"), "issues": len(body.get("issues") or []),
                   "jobs": len(body.get("jobs") or []), "overdue": body.get("overdue"),
                   "sources": len((body.get("sources") or {}).get("sources") or []),
                   "runs_30d": len((ov.get("jobs") or {}).get("runs") or []),
                   "model_rows": len((ov.get("models") or {}).get("rows") or []),
                   "tables_checked": len(before), "declared_inbox_delta": inbox_delta}  # fmt: skip
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    report_["differences"] = len(problems)
    print(json.dumps(report_, indent=2, default=str, ensure_ascii=False))
    for line in problems[:60]:
        print("  DIFF", line[:400])
    print("HEALTH REAL PARITY PASSED" if not problems else "HEALTH REAL PARITY FAILED")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else "check"
    if mode == "goldens":
        return write_goldens()
    if mode == "check":
        return report_(read_golden(), "HEALTH CHECK")
    if mode == "real":
        return real()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
