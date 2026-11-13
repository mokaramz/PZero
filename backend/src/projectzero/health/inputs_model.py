"""What System health is computed from (review 032a): ONE explicit, frozen ``HealthInputs``, and the pure adapter that
builds it from old-format documents the way the old loaders did (``inputs_from_docs``; the goldens use it). The
database adapter (``health/inputs.py``, the main session's) must produce the same values, in the same ORDER, from ONE
``snapshot_transaction`` (REPEATABLE READ, READ ONLY) at the Berlin request clock (decision b).

Every field names the old file or call it replaces and the NEW reader that produces it. The old ``health.system()``
and ``health_overview.overview()`` read each store themselves, several of them twice (``scan_history.json`` three
times, ``inbox.json`` three times, ``schedule/jobs.json`` twice, ``config.json`` four times); each is read ONCE here,
and nothing is written (decision a: no coverage cache, no ledger cache).

Order matters wherever the old code iterated:

* ``sources``: the stored ``sources.json`` order (the source rows sort by state, then name: ties keep it);
* ``scan_history``: the ``scans`` list order (the LAST scan's per-source report gives each ``last_error``);
* ``candidates``: the OLD INBOX order (the ``Counter`` of decisions keeps first appearance: ``pipeline.inbox`` key
  order);
* ``runs``: line order (``last_job_report`` is the LAST line, the 30-day history keeps line order,
  ``outcomes_recorded_since`` is the FIRST line with an outcome);
* ``ledger``: line order (each model's ``provider`` is its FIRST line's, ``rows`` sort is stable, ``spend_by_day``
  inner key order is first appearance);
* ``signals``: the stored ``real_data.json`` order (the status ``Counter`` key order);
* ``watch_events``: line order (the last status line per trigger wins); ``job_state`` / ``research_questions`` /
  ``watch_targets`` key order does not matter (``plan`` iterates ``JOBS``; the rest are counted).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from projectzero.conviction.inputs import UNREADABLE
from projectzero.core.inference import config as icfg
from projectzero.ecosystems.inputs import CoverageInputs
from projectzero.map.inputs_model import coverage_inputs
from projectzero.news.inputs_model import NewsInputs, base_from_docs
from projectzero.validation.inputs_model import ValidationInputs, text
from projectzero.validation.inputs_model import inputs_from_docs as validation_inputs

RUNS = "schedule/runs.jsonl"
JOBS_FILE = "schedule/jobs.json"
RUNNER_FILE = "schedule/runner.json"
LEDGER = "inference_ledger.jsonl"
TRIGGERS = "watch/triggers.jsonl"
TARGETS = "watch/targets.json"
AUTO_RUNS = "shadow_triage/auto_runs.json"
RETRY_STATE = "shadow_triage/retry_state.json"
PROPOSALS = "triage_proposals.json"


@dataclass(frozen=True)
class HealthInputs:
    """System health's inputs, as the old calls returned them. Never mutated by health (``core`` works on copies)."""

    # ── health.source_health ──────────────────────────────────────────────────────────────────────────────────
    # old ``storage.load_json("sources.json", {"sources": []}, tolerant=True).get("sources", [])``: the Deal Flow
    # source records AS STORED (not normalized), in list order. NEW reader: ``dealflow.sources.store.SourcesStore(conn,
    # schema).stored()`` (``attrs.record`` once toggled, else the imported ``legacy`` record; archived order)
    sources: Any = field(default_factory=list)
    # old ``storage.load_json("scan_history.json", {"scans": []}, tolerant=True) or {}`` (``source_health``, the
    # ``last_scan`` and the ``deal_flow_scan`` job's ``_last_scan``). NEW reader: the byte-exact archive
    # ``legacy_documents['scan_history.json']`` (``utf-8-sig``), else ``documents['scan_history.json']``: exactly
    # ``validation.inputs.load_docs(conn, schema, now)['scan_history.json']`` (absent: ``{"scans": []}``). No scan
    # is ported: this is the imported last scan
    scan_history: Any = field(default_factory=lambda: {"scans": []})
    # old ``storage.load_json("inbox.json", {"candidates": []}, tolerant=True).get("candidates")`` (``source_health``
    # and ``watch.watched()`` through ``compat.records(..., ("id",))``; ``pipeline.inbox`` over every dict): the
    # Deal Flow candidate records in the OLD INBOX order. NEW reader: ``validation.inputs.load_docs(conn, schema,
    # now)['inbox.json']['candidates']`` (``inbox_records.old_inbox`` over the non-Scout candidate rows with
    # ``candidate_record``: the absorbed inbox records at their archived position, the survivor's current decision)
    candidates: Any = None
    # ── rule 4 (triage pending) ───────────────────────────────────────────────────────────────────────────────
    # old ``auto_triage._runs()``: ``storage.load_json("shadow_triage/auto_runs.json", {}, tolerant=True)`` (its
    # ``runs[-5:]``' ``pending`` / ``failed``). NEW reader: ``dealflow.triage.view.load(conn, schema).auto_runs``
    auto_runs: Any = field(default_factory=dict)
    # old ``shadow_triage.load_proposals()["proposals"]``: the CURRENT machine proposal per candidate id (only
    # ``status`` is read). NEW reader: ``dealflow.triage.view.load(conn, schema).proposals`` (keyed by survivor id)
    proposals: Any = field(default_factory=dict)
    # old ids -> survivor ids (none in the old app). NEW reader: ``dealflow.triage.view.load(conn, schema).aliases``
    aliases: Mapping[str, str] = field(default_factory=dict)
    # old ``auto_triage.status()["retry"]["next_try"]`` (the earliest ``next_eligible`` of
    # ``shadow_triage/retry_state.json``): read ONLY by the runner's rule-4 text (032c). NEW reader: none yet (the
    # triage retry is the runner's, 032c): ``None``
    triage_next_try: str | None = None
    # ── research / watch ──────────────────────────────────────────────────────────────────────────────────────
    # old ``(storage.load_json("research_questions.json", {"questions": {}}, tolerant=True) or {}).get("questions")
    # or {}``. NEW reader: ``documents['research_questions.json']['questions']``
    research_questions: Any = field(default_factory=dict)
    # old ``watch.load_targets()["targets"]``: ``storage.load_json("watch/targets.json", {}, tolerant=True) or {}``
    # (``setdefault("targets", {})``). NEW reader: ``documents['watch/targets.json']`` (the whole document)
    watch_targets: Any = field(default_factory=dict)
    # old ``watch._events()``: the dict lines of ``watch/triggers.jsonl`` in line order. NEW reader:
    # ``conviction.inputs.inputs_from(load_documents(conn, schema), people).operator.watch_events`` (the archived
    # ``legacy_documents['watch/triggers.jsonl']``, one dict per line)
    watch_events: list[dict[str, Any]] = field(default_factory=list)
    # ── the background jobs (decision e: the imported snapshot) ───────────────────────────────────────────────
    # old ``scheduler._jobs_state()``: ``storage.load_json("schedule/jobs.json", {}, tolerant=True) or {}``. NEW
    # reader: ``{row.job: row.detail for row in pz.job_state}`` (``detail`` is the old record whole)
    job_state: Any = field(default_factory=dict)
    # old ``storage.load_json("config.json", {}, tolerant=True)`` (``scheduler._interval``: ``catch_up.intervals_h``).
    # NEW reader: ``conviction.inputs.load_documents(conn, schema).get("config.json", {})`` (``UNREADABLE``: ``{}``)
    config: Any = field(default_factory=dict)
    # old ``storage.load_json("event_health.json", {}, tolerant=True) or {}`` (``_last_event_scan``: ``scan_time``).
    # NEW reader: ``documents['event_health.json']`` (written by the NEW Events scan: the Events health)
    event_health: Any = field(default_factory=dict)
    # old ``schedule/runs.jsonl`` read as dict lines (``health_overview._jsonl``; ``last_job_report`` reads the last
    # line's ``at``). NEW reader: ``[row.detail for row in pz.job_runs order by id]``: ``detail`` is the old line
    # whole (``started_at`` holds the old ``at``, the FINISH time; ``finished_at`` is NULL), in import order
    runs: list[dict[str, Any]] = field(default_factory=list)
    # old ``scheduler.status()["runners"]``: ``storage.load_json("schedule/runner.json", {}, tolerant=True) or {}``.
    # NEW reader: ``documents['schedule/runner.json']`` (absent: ``{}``)
    runners: Any = field(default_factory=dict)
    # ── spend, providers and models ───────────────────────────────────────────────────────────────────────────
    # old ``ledger.entries()``: every dict line of ``inference_ledger.jsonl`` in line order (``budget.summary``'s
    # spend and the overview's ``models``). NEW reader: ``pz.model_ledger order by id``, each row as the old line:
    # ``{**detail, "ts": berlin_now(at).strftime("%Y-%m-%dT%H:%M:%S"), "purpose", "provider", "model",
    # "entity_id": entity_ref, "usd": float(usd), "input_tokens": tokens_in, "output_tokens": tokens_out, "cached",
    # "outcome", "role": role}``; ``role`` is the generated column ``detail->>'role'``, so an imported row keeps the
    # old ledger's role (decision g), never ``"None"``; ``latency_ms`` / ``error_kind`` come from ``detail``
    ledger: list[dict[str, Any]] = field(default_factory=list)
    # old ``inference.config.load()`` (roles, providers, ``budget``). NEW reader: ``core.inference.config.load()``
    # (no ``config.json["inference"]`` override in the rewrite; RESEARCH and xAI dropped, 029a decision h)
    inference_config: Mapping[str, Any] = field(default_factory=icfg.load)
    # decision (f): whether paid calls may run. NEW reader: ``core.inference.config.paid_enabled(os.environ)``
    # (``PZ_AI_PAID`` exactly ``on``); the old ``kill_switch()`` was set when ``PZ_AI_PAID`` was ``off``
    paid: bool = False
    # decision (f): whether each provider key variable is set, never its value: ``{key_env name: bool}``. NEW
    # reader: ``{n: bool(str(os.environ.get(n) or "").strip()) for n in core.inference.config.KEY_ENVS}``
    keys: Mapping[str, bool] = field(default_factory=dict)
    # ── validation, news, coverage ────────────────────────────────────────────────────────────────────────────
    # old ``validation._read_jsonl(SNAPSHOTS)`` and ``validation.build()``: the Validation inputs (``snapshots_log``
    # and everything ``build`` joins). NEW reader: ``validation.inputs.load(conn, schema, now)``, i.e.
    # ``validation.inputs_model.inputs_from_docs(load_docs(conn, schema, now), berlin_today(now))``
    validation: ValidationInputs = field(default_factory=ValidationInputs)
    # old ``news.health()``'s stores: ``news/runs.jsonl`` (``last_run``, ``usd_total`` and the ``news_refresh`` job's
    # ``_last_news``), ``news/events.json``, the metric cache ``news/source_metrics.json``, ``news/source_state.json``
    # and ``sources/network.json``. NEW reader: the SAME ``validation.inputs.load(...)``'s ``news_inputs`` (the News
    # store, ``news_logs`` and ``news_documents``: ``news.inputs_model.base_from_docs``), read once
    news: NewsInputs = field(default_factory=NewsInputs)
    # old ``coverage.report()`` (``_coverage_summary``). NEW reader: ``ecosystems.store.EcosystemsStore(conn,
    # schema).snapshot(now).inputs`` for ``ecosystems.coverage.coverage_view``. ``None``: the Deal Flow registry could
    # not be read (the old report raised: the "temporarily unavailable" fallback)
    coverage: CoverageInputs | None = field(default_factory=CoverageInputs)
    # ── the overview's pipeline ───────────────────────────────────────────────────────────────────────────────
    # old ``health_overview._load("queue_routing.json", {})`` (``counts``, ``at``). NEW reader:
    # ``documents['queue_routing.json#rest']`` (the imported routing summary: no compression run is ported)
    queue_routing: Any = field(default_factory=dict)
    # old ``health_overview._load("real_data.json", {}).get("signals")``: the Conviction records in stored order.
    # NEW reader: ``[conviction.store.record_of(r) for r in ConvictionStore(conn, schema).entry_rows()]``
    signals: Any = None
    # the overview's ``pipeline.inbox`` (Codex H-309): the decision of every candidate the Deal Flow inbox lists, the
    # page the "You: review" node links to. The old app counted ``inbox.json``, which WAS that inbox; the merged Deal
    # Flow also lists the Scout-only candidates the merge brought in and the absorbed records' survivors once. NEW
    # reader: ``[ranking_input(r)[0]["decision"] for r in dealflow.inbox_view.candidate_rows(conn, schema)]`` (the
    # same population and decision the Deal Flow inbox view builds). ``None``: the old count over ``candidates``
    inbox_decisions: list[str] | None = None


MISSING = object()


def _tolerant(docs: Mapping[str, Any], name: str, default: Any) -> Any:
    """The old ``storage.load_json(name, default, tolerant=True)``: missing or unreadable is (a copy of) the default."""
    v = docs.get(name, MISSING)
    return copy.deepcopy(default) if v is MISSING or v is UNREADABLE else v


def dict_lines(raw: Any) -> list[dict[str, Any]]:
    """The old ``_jsonl`` / ``ledger.entries`` / ``watch._events``: every line of the log's text that parses to a JSON
    object, in line order (blank and torn lines skipped)."""
    out: list[dict[str, Any]] = []
    for line in text(raw).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def next_try(retry_state: Any) -> str | None:
    """The old ``auto_triage.status()["retry"]["next_try"]`` over the stored retry state (the legacy-run derivation
    ``_legacy_retryable`` is the runner's, 032c)."""
    rs = retry_state if isinstance(retry_state, dict) else {}
    return min(
        (r["next_eligible"] for r in rs.values() if isinstance(r, dict) and r.get("next_eligible")), default=None
    )


def inputs_from_docs(
    docs: Mapping[str, Any], today: date, now: datetime, *, paid: bool = False, keys: Mapping[str, bool] | None = None
) -> HealthInputs:
    """``HealthInputs`` from old-format documents ``{path: parsed JSON}`` (the JSONL logs: their raw text, ``str`` or
    ``bytes``; ``UNREADABLE``: a file that does not parse), read as the old loaders read them. ``now`` is the request
    instant as naive Berlin wall time, ``today`` its date (decision b); no input depends on the clock. ``paid`` and
    ``keys`` stand for the environment (decision f: presence only). Pure: ``docs`` is never modified."""
    del now  # the inputs are the stored state; the view applies the clock
    docs = {k: v if v is UNREADABLE else copy.deepcopy(v) for k, v in docs.items()}  # the sentinel stays itself
    readable = {k: v for k, v in docs.items() if v is not UNREADABLE}
    cov, sources_ok = coverage_inputs(readable)
    v = validation_inputs(readable, today)
    inbox = _tolerant(docs, "inbox.json", {"candidates": []}) or {}
    triage = _tolerant(docs, PROPOSALS, {"proposals": {}}) or {}
    real = _tolerant(docs, "real_data.json", {})
    return HealthInputs(
        sources=(_tolerant(docs, "sources.json", {"sources": []}) or {}).get("sources", []),
        scan_history=_tolerant(docs, "scan_history.json", {"scans": []}) or {},
        candidates=inbox.get("candidates"),
        auto_runs=_tolerant(docs, AUTO_RUNS, {}),
        proposals=triage.get("proposals", {}) if isinstance(triage, dict) else {},
        triage_next_try=next_try(_tolerant(docs, RETRY_STATE, {}) or {}),
        research_questions=(_tolerant(docs, "research_questions.json", {"questions": {}}) or {}).get("questions") or {},
        watch_targets=_tolerant(docs, TARGETS, {}) or {},
        watch_events=dict_lines(docs.get(TRIGGERS)),
        job_state=_tolerant(docs, JOBS_FILE, {}) or {},
        config=_tolerant(docs, "config.json", {}),
        event_health=_tolerant(docs, "event_health.json", {}) or {},
        runs=dict_lines(docs.get(RUNS)),
        runners=_tolerant(docs, RUNNER_FILE, {}) or {},
        ledger=dict_lines(docs.get(LEDGER)),
        inference_config=icfg.load(),
        paid=paid,
        keys=dict(keys or {}),
        validation=v,
        news=v.news_inputs if isinstance(v.news_inputs, NewsInputs) else base_from_docs(readable),
        coverage=cov if sources_ok else None,
        queue_routing=_tolerant(docs, "queue_routing.json", {}),
        signals=real.get("signals") if isinstance(real, dict) else None,  # the old ``_load``: not an object -> {}
    )
