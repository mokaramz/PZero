"""What Today is computed from (review 030a): ONE explicit, frozen ``TodayInputs``, and the pure adapter that builds it
from old-format documents the way the old loaders did (``inputs_from_docs``; the goldens use it). The database adapter
must produce the same values, in the same ORDER, from ONE repeatable-read snapshot (revision 2).

Every field names the old call it replaces. The old ``services/today.py`` read each store itself, often several
times: the Conviction pipeline three times (``_pipeline_actions``, ``case_prep.summary``, the human-outcome hold), the
compressor summary three times, the inbox four times. Decision (a): each is read ONCE here, and nothing is written
(the old pipeline read could save ``real_data.json``; the new one never does).

Order matters wherever the old code iterated:

* ``signals``: the stored ``real_data.json`` order (then creation order): it decides the Radar slot ties, ``gated``
  (Radar gated, then the ``unclear`` entries, then the portfolio-blocked ones), the ASK_OMAR subject / evidence (the
  first 6), the prepared-case rows, and the hold maps (a later record of the same company name wins);
* ``people``: file order (IMQ takes the FIRST matching person);
* ``events``: the stored ``events.json`` order (the listing's sort is stable);
* ``triage``: the OLD INBOX order (decision g / h: the old ``triage_review.view()`` iterated the inbox; the new triage
  view is built over candidates ordered by id, so the adapter re-keys it in inbox order): it decides the flagged
  names and evidence (the first 5);
* ``operator.watch_events``: line order (the last status line per trigger wins; one card per company in first-seen
  order);
* ``founder_calls``: as stored (call ties keep file order).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from projectzero.conviction import inputs as conviction_inputs
from projectzero.conviction import pipeline
from projectzero.conviction.operator import OperatorInputs
from projectzero.conviction.records import records
from projectzero.dealflow import workspaces
from projectzero.dealflow.triage import view as triage_view
from projectzero.events.store import EventsData
from projectzero.validation.inputs_model import text  # the old ``storage.read_text``

UNREADABLE = conviction_inputs.UNREADABLE  # a document that exists but does not parse (the old load raised)


@dataclass(frozen=True)
class TodayInputs:
    """Today's inputs, as the old calls returned them. Never mutated by Today (the view works on copies)."""

    # old ``pipeline.pipeline()["signals"]`` (ONE read, decision a): the enriched Conviction records (``slug``, ``sc``,
    # ``imq_eval``, ``op``, ...) in stored order, built at the request clock; NEW reader:
    # ``ConvictionStore.pipeline_view(now)["signals"]``. ``None``: the read raised (the old pipeline section, the
    # prepared-case section and the hold all failed with it)
    signals: list[dict[str, Any]] | None = field(default_factory=list)
    # old ``storage.load_json("people.json", {}, tolerant=True).get("people", []) or []`` (``plist``, for the bare
    # ``imq.evaluate(e, plist)`` of the Radar entries), in file order; NEW reader: ``network.store.load_people``
    people: list[dict[str, Any]] = field(default_factory=list)
    # the operator documents the old ``case_prep`` / ``watch`` / ``compressor`` loaded themselves; NEW reader:
    # ``conviction.inputs.load_inputs(...).operator``:
    # * ``cases``: ``case_prep/cases.json`` ``cases`` (slug -> prepared case; ``case_prep.summary`` / ``state_of``);
    # * ``founder_calls`` / ``evaluations``: the TOLERANT reads behind ``calls_for`` (the hold, ``fingerprint``) and the
    #   founder-call conversation filter;
    # * ``watch_events``: ``watch/triggers.jsonl``, one dict per line in line order (old ``watch.open_triggers()``
    #   over ``watch.triggers()``, and the hold's re-open evidence);
    # * ``config``: ``config.json`` (tolerant): ``outreach`` (the contact state) and ``attention_budget`` (the old
    #   ``compressor.settings()``)
    operator: OperatorInputs = field(default_factory=OperatorInputs)
    # old ``founder_calls.load()`` behind ``founder_calls.due_followups()``: the call store as stored (the defaults are
    # applied by ``founder_calls.core.loaded``; missing: the empty store); ``UNREADABLE``: the old load raised, the
    # calls section is "temporarily unavailable". NEW reader: ``FounderCallsStore(conn, schema).load()``
    founder_calls: Any = None
    # old ``events.listing()``: the event records in stored order, ``event_sources.json`` (each source's city) and the
    # pinned free-text dates; the listing itself is computed at the request's Berlin ``today`` (decision b). NEW
    # reader: ``events.store.load(conn, schema, today, people=False)``
    events: EventsData = field(default_factory=lambda: EventsData([], []))
    # old ``triage_review.view()["proposals"]``: ``{candidate id: triage summary}`` in the OLD INBOX order (the
    # summaries carry ``routing.queue``, ``display_proposal``, ``entity.display_name``, ``portfolio.status``). NEW
    # reader: ``dealflow.triage.view.triage_view(conn, schema)["proposals"]`` re-keyed in the inbox view order
    # (``dealflow.inbox_view.candidate_rows``). ``None``: the view raised (the triage section is unavailable)
    triage: dict[str, dict[str, Any]] | None = field(default_factory=dict)
    # old ``discovery.load_inbox()`` read twice: the ids of the candidates whose decision is ``new``
    # (``_triage_actions`` keeps only those; ``compressor.summary`` drops the routes of the others). NEW:
    # ``candidates.status = 'new'``
    # (survivor ids; ids are unique, so the old dict-by-id and set readings agree)
    live_ids: frozenset[str] = frozenset()
    # old ``compressor.load()``: ``storage.load_json("queue_routing.json", {}, tolerant=True) or {}`` (``at``,
    # ``elsewhere``, ``routes``: candidate id -> route). NEW: ``{**documents['queue_routing.json#rest'].body,
    # "routes": {survivor id: dealflow.triage.view.route_record(row)}}`` over ``candidate_routing`` (the imported
    # snapshot: no compression run is ported, decision f). The route order does not matter (every use sorts or counts)
    queue_routing: Any = field(default_factory=dict)


MISSING = object()


def _doc(docs: Mapping[str, Any], name: str, default: Any) -> Any:
    """The old ``storage.load_json(name, default)``: a missing document is (a copy of) the default."""
    v = docs.get(name, MISSING)
    return copy.deepcopy(default) if v is MISSING else v


def _tolerant(docs: Mapping[str, Any], name: str, default: Any) -> Any:
    """The old tolerant ``storage.load_json(name, default, tolerant=True)``: missing or unreadable is the default."""
    v = _doc(docs, name, default)
    return copy.deepcopy(default) if v is UNREADABLE else v


def _raw(v: Any) -> bytes:
    return v if isinstance(v, bytes) else str(v).encode("utf-8")


def conviction_docs(docs: Mapping[str, Any]) -> dict[str, Any]:
    """The documents ``conviction.inputs.inputs_from`` reads, as ``load_documents`` gives them (the JSONL logs as
    bytes)."""
    out: dict[str, Any] = {k: docs[k] for k in conviction_inputs.DOCS if k in docs}
    for k in conviction_inputs.JSONL:
        if k in docs:
            out[k] = _raw(docs[k])
    return out


def pipeline_signals(docs: Mapping[str, Any], inputs: pipeline.Inputs, now: datetime) -> list[dict[str, Any]]:
    """The old ``pipeline.pipeline()["signals"]`` (``real_data.json``: not tolerant), read without the IMQ save."""
    real = _doc(docs, "real_data.json", {"week": "", "signals": []})
    if real is UNREADABLE or not isinstance(real, dict):
        raise ValueError("real_data.json could not be read")
    rest = {k: v for k, v in real.items() if k != "signals"}
    stored: Any = real.get("signals")  # ``build`` keeps the dict records with a company (the old ``compat.records``)
    signals: list[dict[str, Any]] = pipeline.build(rest, stored, inputs, now)["signals"]
    return signals


def triage_inputs(docs: Mapping[str, Any]) -> triage_view.TriageInputs:
    """The old ``triage_review.view()`` inputs, read as the old modules read them (``parity_triage``'s offline
    reader over parsed documents): candidates in INBOX order."""
    inbox = _doc(docs, "inbox.json", {"candidates": []})
    proposals = _doc(docs, "triage_proposals.json", None)
    real = _tolerant(docs, "real_data.json", {}) or {}
    intake = _tolerant(docs, "scout_intake.json", {}) or {}
    log = docs.get(triage_view.DECISION_LOG)
    return triage_view.TriageInputs(
        candidates=records(inbox.get("candidates"), ("id",)),
        proposals=(proposals if isinstance(proposals, dict) else {}).get("proposals", {}),
        routes=(_tolerant(docs, "queue_routing.json", {}) or {}).get("routes") or {},
        decision_log=text(log),
        conviction_signals=real.get("signals", []) or [],
        scout_items=intake.get("items", {}) or {},
        acceptance=_tolerant(docs, triage_view.ACCEPTANCE_DOC, {}),
        auto_runs=_tolerant(docs, triage_view.AUTO_RUNS_DOC, {}),
        override=workspaces.parse_override(_tolerant(docs, "workspace_geos.json", {})),
    )


def events_data(docs: Mapping[str, Any]) -> EventsData:
    """The old ``events.listing()`` inputs: ``events.json`` events in stored order, ``event_sources.json`` (no pins:
    the old code at the same clock read the same words)."""
    doc = _tolerant(docs, "events.json", {}) or {}
    documents = {k: docs[k] for k in ("event_sources.json",) if k in docs and docs[k] is not UNREADABLE}
    return EventsData(events=[e for e in doc.get("events", []) if isinstance(e, dict)], leads=[], documents=documents)


def live_ids(docs: Mapping[str, Any]) -> frozenset[str]:
    """The old ``compressor.summary`` ``live`` set: inbox ids whose decision is ``new``."""
    inbox = _doc(docs, "inbox.json", {"candidates": []})
    return frozenset(c["id"] for c in records(inbox.get("candidates"), ("id",)) if c.get("decision") == "new")


def inputs_from_docs(docs: Mapping[str, Any], today: date, now: datetime) -> TodayInputs:
    """``TodayInputs`` from old-format documents ``{path: parsed JSON}`` (the JSONL logs: their raw text, ``str`` or
    ``bytes``; ``UNREADABLE``: a file that does not parse), read as the old loaders read them. ``now`` is the request
    instant as naive Berlin wall time, ``today`` its date (decision b: one clock); the pipeline is built at ``now``.
    Pure: ``docs`` is never modified (every reader works on copies)."""
    del today  # the inputs depend on the instant only through the pipeline build (``now``)
    docs = {k: v if v is UNREADABLE else copy.deepcopy(v) for k, v in docs.items()}  # the sentinel stays itself
    people = (_tolerant(docs, "people.json", {}) or {}).get("people", []) or []
    conviction = conviction_inputs.inputs_from(conviction_docs(docs), people)  # read once: pipeline + operator
    try:
        signals: list[dict[str, Any]] | None = pipeline_signals(docs, conviction, now)
    except Exception:  # the old pipeline read raised: every reader of it fails as before
        signals = None
    try:
        triage: dict[str, dict[str, Any]] | None = triage_view.build(triage_inputs(docs))["proposals"]
    except Exception:  # the old triage view raised: the triage section is unavailable
        triage = None
    try:
        live = live_ids(docs)
    except Exception:
        live = frozenset()
    fc = docs.get("founder_calls.json")
    return TodayInputs(
        signals=signals,
        people=people,
        operator=conviction.operator,
        founder_calls=fc,
        events=events_data(docs),
        triage=triage,
        live_ids=live,
        queue_routing=_tolerant(docs, "queue_routing.json", {}) or {},
    )
