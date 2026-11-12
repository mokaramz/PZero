"""What News & Learning is computed from (review 028a): ONE explicit, frozen ``NewsInputs``, and the pure adapter that
builds it from old-format documents the way the old loaders did (``inputs_from_docs``; the goldens use it). The
database adapter must produce the same values, in the same ORDER, from the stores.

Every field names the old call it replaces. The old ``services/news.py`` and ``services/news_sources.py`` read each
store themselves: every JSON document TOLERANTLY (``storage.load_json(..., tolerant=True)``: a missing or unreadable
file is the default) and every JSONL log through ``storage.read_text`` (missing or undecodable: ``""``) then line by
line. The documents are kept as they were READ (``load()``'s ``setdefault`` is applied by the logic, so a non-object
fails where it failed); the logs as their RAW TEXT (line order is semantic: the last decision per event wins, the
last run, the last ``ok`` run, the technical attempts).

Order matters wherever the old code iterated: the ``events`` map of ``news/events.json`` is read in its archived KEY
order (it decides every merge, every tie of the two stable sorts, the earliest observation, the theme groups and the
first benchmark per company); each event's ``sources`` list order (``sources[0]`` is the publisher); the curated case
files in sorted file-name order.

Decision (b): the Validation entities are built ONCE per request and passed in (``entities``); News never re-enters
the Validation view. ``source_alpha`` (the old ``validation.source_alpha(validation.entities(today))`` behind
``news_sources._deal_flow_alpha``) is computed from the same entities and the same Validation inputs.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

from projectzero.news.catalog import (
    ACTIONS,
    COOLDOWN,
    DISAGREE,
    EVENTS,
    EXTRA_FEEDS,
    HISTORY,
    LOG,
    RUNS,
    SNAPSHOT,
    STATE,
)

# the curated learning cases shipped with Project Zero (the old ``SEED_CASES``), copied byte for byte by
# ``scripts/gen_news_catalog.py``
SEED_CASES = Path(__file__).resolve().parents[1] / "resources" / "news_cases"
CASES_KEY = "resources/news_cases/"  # in ``docs``: ``{file name: text}``, or ``None`` for a missing folder
SCAN_HISTORY = "scan_history.json"
NETWORK = "sources/network.json"
OUTCOMES = "validation/outcomes.jsonl"
AUDITS = "validation/audits.jsonl"

Cases = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class NewsInputs:
    """News' inputs, as the old calls returned them. Never mutated by News (decision a: the seeding is in memory)."""

    # old ``storage.load_json("news/events.json", {}, tolerant=True) or {}`` (``news.load()`` before its two
    # ``setdefault``): the archived events document ``{events: {event_id: event}, seeded: [case id]}``, read from the
    # byte-exact archive (``events`` KEY order and each event's key order as stored, never through JSONB)
    events: Any = field(default_factory=dict)
    # old ``storage.read_text("news/actions.jsonl")``: the outcome decisions, miss audits and backcast additions (line
    # order: the last line per event wins)
    actions_log: str = ""
    # old ``storage.read_text("news/runs.jsonl")``: one line per refresh run (line order: ``last_run``, ``last`` /
    # ``last_ok``, the technical attempts and failure streak)
    runs_log: str = ""
    # old ``storage.read_text("news/disagreements.jsonl")``: the first observation of each disagreement (line order);
    # read only by the source evaluation (028c), kept here so the reader is complete
    disagreements_log: str = ""
    # old ``storage.read_text("news/source_log.jsonl")``: degradations, recoveries, nominations (line order); read only
    # by the source evaluation (028c)
    source_log: str = ""
    # old ``news_sources.cached()``: ``storage.load_json("news/source_metrics.json", {}, tolerant=True) or {}``, the
    # metric cache ``{at, today, windows: {"30"|"90"|"180"|"all": compute(...)}}`` (story source notes, Scout lines,
    # the sources view's ``evaluated_at``)
    source_metrics: Any = field(default_factory=dict)
    # old ``news_sources._state()``: ``storage.load_json("news/source_state.json", {}, tolerant=True) or {}``, the
    # lifecycle per monitored source ``{name: {state, since, reasons, history}}``
    source_state: Any = field(default_factory=dict)
    # old ``news_sources.extra_feeds()`` document: ``storage.load_json("news/feeds_extra.json", {}, tolerant=True) or
    # {}`` (``feeds`` in list order: the publications added through the source network)
    feeds_extra: Any = field(default_factory=dict)
    # old ``_pz_start()``: ``storage.load_json("scan_history.json", {"scans": []}, tolerant=True) or {}``
    scan_history: Any = field(default_factory=lambda: {"scans": []})
    # old ``source_network.load()`` before its ``setdefault``: ``storage.load_json("sources/network.json", {},
    # tolerant=True) or {}`` (``candidates`` in key order: the sources view's ``news_publication`` candidates)
    network: Any = field(default_factory=dict)
    # old ``validation._sources()`` input: ``sources.json`` ``sources`` as STORED (list order; ``id`` / ``name``)
    sources: Any = field(default_factory=list)
    # old ``validation._read_jsonl(OUTCOMES)``: the raw text of ``validation/outcomes.jsonl`` (line order; the
    # sources view's independent benchmark reads the LIVE rows)
    outcomes_log: str = ""
    # old ``validation._read_jsonl(AUDITS)``: the raw text of ``validation/audits.jsonl`` (line order); News' miss
    # audits live there (Validation's News panel reads them from its own inputs; kept here for the 028b writes)
    audits_log: str = ""
    # old ``sorted(SEED_CASES.glob("*.json"))`` read with ``f.read_text(encoding="utf-8")``: ``(file name, text)`` in
    # sorted name order (each text is parsed where the old ``seed_cases`` parsed it: a bad file raises there);
    # ``None``: the folder does not exist (``SEED_CASES.exists()`` is false: nothing is seeded)
    cases: Cases | None = ()
    # old ``validation.entities(today)``: the Validation entity model, built ONCE per request (decision b)
    entities: dict[str, dict[str, Any]] | None = None
    # old ``validation.source_alpha(validation.entities(today))`` (``_deal_flow_alpha``); ``None``: not computed (the
    # old ``try`` failed: the Deal Flow row is ``{}``)
    source_alpha: list[dict[str, Any]] | None = None
    # review 028c (the refresh run and the source evaluation; read by nothing else): old
    # ``storage.read_text("news/source_history.jsonl")``, the monthly source snapshots (line order: the last line
    # decides whether a new one is due) ...
    source_history_log: str = ""
    # ... and old ``storage.load_json("news/feed_cooldown.json", {}, tolerant=True) or {}``: ``{feed name: until}``
    # for the feeds that answered 429 (key order kept: the run pops and adds keys)
    feed_cooldown: Any = field(default_factory=dict)


MISSING = object()


def _doc(docs: Mapping[str, Any], name: str, default: Any) -> Any:
    """The old tolerant ``storage.load_json(name, default)``: a missing document is (a copy of) the default."""
    v = docs.get(name, MISSING)
    return copy.deepcopy(default) if v is MISSING else v


def packaged_cases() -> Cases | None:
    """The shipped curated cases, as the old ``seed_cases`` listed and read them."""
    if not SEED_CASES.exists():
        return None
    return tuple((p.name, p.read_text(encoding="utf-8")) for p in sorted(SEED_CASES.glob("*.json")))


def _cases(docs: Mapping[str, Any]) -> Cases | None:
    v = docs.get(CASES_KEY, MISSING)
    if v is MISSING:
        return packaged_cases()
    if v is None:
        return None
    return tuple((name, v[name]) for name in sorted(v))


def base_from_docs(docs: Mapping[str, Any]) -> NewsInputs:
    """``NewsInputs`` WITHOUT the Validation entities (``entities`` / ``source_alpha`` are ``None``): what Validation
    carries (``ValidationInputs.news_inputs``) and completes with the entities it built itself. Pure."""
    from projectzero.validation.inputs_model import text  # the old ``storage.read_text``

    return NewsInputs(
        events=_doc(docs, EVENTS, {}) or {},
        actions_log=text(docs.get(ACTIONS)),
        runs_log=text(docs.get(RUNS)),
        disagreements_log=text(docs.get(DISAGREE)),
        source_log=text(docs.get(LOG)),
        source_metrics=_doc(docs, SNAPSHOT, {}) or {},
        source_state=_doc(docs, STATE, {}) or {},
        feeds_extra=_doc(docs, EXTRA_FEEDS, {}) or {},
        scan_history=_doc(docs, SCAN_HISTORY, {"scans": []}) or {},
        network=_doc(docs, NETWORK, {}) or {},
        sources=(_doc(docs, "sources.json", {"sources": []}) or {}).get("sources", []),
        outcomes_log=text(docs.get(OUTCOMES)),
        audits_log=text(docs.get(AUDITS)),
        cases=_cases(docs),
        source_history_log=text(docs.get(HISTORY)),
        feed_cooldown=_doc(docs, COOLDOWN, {}) or {},
    )


def with_entities(base: NewsInputs, entities: dict[str, dict[str, Any]], validation_inputs: Any = None) -> NewsInputs:
    """Decision (b): ``base`` with the request's ONE Validation entity build; with the Validation inputs it was built
    from, also the Deal Flow source-alpha rows of the sources view (old ``_deal_flow_alpha``, inside its ``try``)."""
    alpha = None
    if validation_inputs is not None:
        from projectzero.validation.core import source_alpha

        try:
            alpha = source_alpha(entities, validation_inputs)
        except Exception:  # the old ``try``: source alpha unavailable for news sources
            alpha = None
    return replace(base, entities=entities, source_alpha=alpha)


def inputs_from_docs(docs: Mapping[str, Any], today: date, *, entities: dict[str, Any] | None = None) -> NewsInputs:
    """``NewsInputs`` from old-format documents ``{path: parsed JSON}`` (the JSONL logs: their raw text, ``str`` or
    ``bytes``; the curated cases under ``CASES_KEY``, default: the packaged ones), read as the old loaders read them.
    ``entities``: the request's Validation entities when the caller already built them (decision b); otherwise they
    are built once here from the same documents (``validation.inputs_from_docs`` -> ``validation.entities``). Pure:
    ``docs`` is never modified."""
    from projectzero.validation.core import entities as build_entities
    from projectzero.validation.inputs_model import inputs_from_docs as validation_inputs

    v = validation_inputs(docs, today)
    ents = entities if entities is not None else build_entities(v, today)
    return with_entities(v.news_inputs, ents, v)
