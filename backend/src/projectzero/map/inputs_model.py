"""What the Map is computed from (review 025): ONE explicit, frozen ``MapInputs``, and the pure adapter that builds it
from old-format documents the way the old loaders did (``inputs_from_docs``; the goldens use it). The database adapter
(``map/inputs.py``) must produce the same values, in the same ORDER, from the stores.

Every field names the old call it replaces. The old code read each store itself, inside ``services/geo_intel.py``
(``_collect``, ``_home``) and ``api/routers/home.py`` (``map_view``); a store that could not be read emptied only its
layer (``_rows``) -- that tolerance lives in the adapter, so each field below is the value the old call RETURNED.

Order matters wherever the old code iterated: the inbox candidates (file order), the Conviction records (file order),
the scout items (stored order), the news events (the archive's KEY order: it decides ``detail.news``, the per-city
unit order, ``search`` and the ``Counter`` ties), the people listing and the events listing (their own sorted order),
the institutions (ORGS, then ``ecosystems.json``) and the source-network candidates (archive key order: it decides
``source_candidates[:6]``). The coverage lists are in the old registry / report order.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from projectzero.dealflow.sources.normalize import load_registry
from projectzero.ecosystems import cities, coverage
from projectzero.ecosystems.inputs import CoverageInputs
from projectzero.events import engine
from projectzero.map.network import check_candidates
from projectzero.network import view as people_view
from projectzero.watch import log as watch_log


@dataclass(frozen=True)
class MapInputs:
    """The Map's inputs, as the old calls returned them. Never mutated by the Map (decision a)."""

    # old ``storage.load_json("inbox.json", {"candidates": []}, tolerant=True).get("candidates")``: the Deal Flow
    # candidate records in FILE order (a list; ``compat.records(..., ("id",))`` is applied by the Map)
    inbox: Any = None
    # old ``shadow_triage.load_proposals()["proposals"]``: the CURRENT machine proposal per candidate id
    # ``{candidate_id: {proposal, entity_type, capital_stage, ...}}`` (lookup only; order irrelevant)
    proposals: Mapping[str, Any] = field(default_factory=dict)
    # old ``storage.load_json("sources.json", {"sources": []}, tolerant=True).get("sources", [])``: the Deal Flow source
    # records as STORED (not normalized); only ``id`` and ``stage`` are read
    sources: list[Any] = field(default_factory=list)
    # old ``coverage.declared_sources()`` (``[]`` when it raised): ``[{id, families, ...}]``; only ``id`` / ``families``
    declared_sources: list[dict[str, Any]] = field(default_factory=list)
    # old ``coverage.ecosystems()`` (``[]`` when it raised): the coverage registry rows ``[{city, country, aliases,
    # ...}]`` in registry order (radar regions, ecosystems.json cities, defaults, coverage_registry.json)
    coverage_ecosystems: list[dict[str, Any]] = field(default_factory=list)
    # old ``health.coverage_summary().get("all") or []``: ``[{city, country, families: {family: state | None}}]``
    # in the coverage report order (the ported ``coverage_view(...)["ecosystems"]`` projected: ``coverage_all``)
    coverage_all: list[dict[str, Any]] = field(default_factory=list)
    # old ``real_data.json`` ``signals`` (geo: tolerant ``.get("signals", [])``; pins: ``load_signals_doc()``
    # ``["signals"]``): the Conviction records in FILE order, dropped ones included (the Map skips them)
    signals: Any = None
    # old ``scout_intake.load()["items"]`` through ``_rows`` (``[]`` when unreadable): the archived Scout Intake items
    # in STORED order
    scout_items: list[Any] = field(default_factory=list)
    # old ``news.load()["events"]`` (``{}`` when unreadable): the canonical news events as an ORDERED dict keyed by
    # event id, in the archive's key order (a non-dict value is read by ``_rows`` exactly as the old code did)
    news_events: Any = None
    # old ``people.listing()`` (``[]`` when it raised): the person listing (derived fields, due first, then stalest)
    people: list[dict[str, Any]] = field(default_factory=list)
    # old ``events.listing()[0]`` (``[]`` when it raised): the canonical events with ``sc`` / ``past`` / ``when``,
    # in the listing order (not past first, then start, then score)
    events: list[dict[str, Any]] = field(default_factory=list)
    # old ``watch.open_triggers()`` (``[]`` when it raised): the open WATCH triggers (only ``name`` / ``key`` read)
    watch_open: list[dict[str, Any]] = field(default_factory=list)
    # old ``ecosys._registry()[1]``: the institutions, the 24 static ``ORGS`` then the ``ecosystems.json`` ones
    institutions: list[dict[str, Any]] = field(default_factory=list)
    # ``network.check_candidates(<sources/network.json>)``: the USABLE source-network candidates in archive key order
    # (every state; the Map keeps DISCOVERED / VALIDATING / PROBATION / DEGRADED) ...
    network: list[dict[str, Any]] = field(default_factory=list)
    # ... and the problems (each one record left out; the intelligence / detail ``note`` names them)
    network_problems: list[str] = field(default_factory=list)
    # old ``config.json`` ``home_base`` value as stored (``None`` when absent): both readers fall back to Karlsruhe
    home_base: Any = None
    # decision d: Scout Intake is merged into Deal Flow, so a Scout 00 card links to ``/scout-intake?item=<id>``, which
    # the page opens in Deal Flow (the old Scout Intake id resolves there). ``False``: the old bare ``/scout-intake``
    # (the goldens compare the old answer)
    scout_links: bool = False


MISSING = object()


def _doc(docs: Mapping[str, Any], name: str, default: Any) -> Any:
    """The old ``storage.load_json(name, default)``: a missing document is (a copy of) the default."""
    v = docs.get(name, MISSING)
    return copy.deepcopy(default) if v is MISSING else v


def _rows(fn: Any) -> list[Any]:
    """The old ``geo_intel._rows``: the records of one layer; an unreadable store empties only that layer."""
    try:
        v = fn()
    except Exception:
        return []
    return list(v.values()) if isinstance(v, dict) else list(v or [])


def coverage_inputs(docs: Mapping[str, Any]) -> tuple[CoverageInputs, bool]:
    """``CoverageInputs`` from the old files (as ``ops.parity_ecosystems.inputs_of``) and whether the Deal Flow
    registry could be read (the old ``connectors.load_registry()``: when it raised, so did ``declared_sources`` and
    the coverage report, but not the ecosystem registry). A missing ``sources.json`` reads as an empty registry: the
    old code SEEDED the default registry then (and wrote it), which the database, whose source table always exists,
    never does."""
    src = _doc(docs, "sources.json", {"sources": []})
    try:
        registry, ok = load_registry(src)["sources"], True
    except Exception:
        registry, ok = [], False
    cov = CoverageInputs(
        sources=registry,
        event_health=docs.get("event_health.json"),
        radar_regions=docs.get("radar_regions.json"),
        radar_sources=docs.get("radar_sources.json"),
        radar_health=docs.get("radar_health.json"),
        inbox=(docs.get("inbox.json") or {"candidates": []}).get("candidates"),
        signals=(docs.get("real_data.json") or {"signals": []}).get("signals", []),
        people=(docs.get("people.json") or {"people": []}).get("people"),
        events=(docs.get("events.json") or {"events": []}).get("events", []),
        coverage_sources=docs.get("coverage_sources.json"),
        coverage_adopted=docs.get("coverage_adopted.json"),
        coverage_registry=docs.get("coverage_registry.json"),
        coverage_candidates=docs.get("coverage_candidates.json"),
        ecosystems_doc=docs.get("ecosystems.json"),
    )
    return cov, ok


def coverage_all(cov: CoverageInputs, today: date) -> list[dict[str, Any]]:
    """The old ``health._coverage_summary()["all"]`` over the ported ``coverage_view`` (``[]`` when it raised)."""
    try:
        rep = coverage.coverage_view(cov, datetime(today.year, today.month, today.day, 12, 0))
    except Exception:
        return []
    fams = [f[0] for f in rep["families"]]
    return [
        {
            "city": e["city"],
            "country": e.get("country", ""),
            "families": {f: ((e.get("families") or {}).get(f) or {}).get("state") for f in fams},
        }
        for e in rep["ecosystems"]
    ]


def _events_listing(docs: Mapping[str, Any], today: date) -> list[dict[str, Any]]:
    d = _doc(docs, "events.json", {"events": [], "leads": []})
    srcs = (_doc(docs, "event_sources.json", {}) or {}).get("sources") or []
    src_city = {s.get("id"): s.get("city", "") for s in srcs if isinstance(s, dict)}
    return engine.listing(d["events"], today, src_city)


def _scout_items(docs: Mapping[str, Any]) -> Any:
    """The old ``scout_intake.load()["items"]`` (non-tolerant load, then ``setdefault``; raised for a non-object)."""
    return _with_defaults(_doc(docs, "scout_intake.json", {}), ("cycles", {}), ("items", []), ("events", []))["items"]


def _watch_open(docs: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The old ``watch.open_triggers()`` over ``watch/triggers.jsonl``: its text (one JSON object per line), or the
    dict lines the ONE trigger reader overlaid (``watch.log.load_events``, review 037a)."""
    return watch_log.open_triggers(watch_log.events_of(docs.get("watch/triggers.jsonl")))


Coverage = tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]


def coverage_of(cov: CoverageInputs, today: date, sources_ok: bool = True) -> Coverage:
    """(``coverage_ecosystems``, ``declared_sources``, ``coverage_all``) over the coverage inputs, each ``[]`` when its
    old call raised (``declared_sources`` and the report also when the Deal Flow registry could not be read)."""
    try:
        registry = coverage.ecosystems(cov)
    except Exception:
        registry = []
    try:
        declared = coverage.declared_sources(cov, registry, today) if sources_ok else []
    except Exception:
        declared = []
    return registry, declared, coverage_all(cov, today) if sources_ok else []


def inputs_from_docs(docs: Mapping[str, Any], today: date, *, cover: Coverage | None = None) -> MapInputs:
    """``MapInputs`` from old-format documents ``{path: parsed JSON}`` (``watch/triggers.jsonl``: its text), read as
    the old loaders read them, tolerance included. ``today`` (the Berlin day) is the clock of the listings and the
    coverage windows. ``cover``: the coverage already computed (``coverage_of``) by a caller that holds the coverage
    inputs (the database adapter); otherwise it is computed from ``docs``. Pure: ``docs`` is never modified."""
    inbox = (_doc(docs, "inbox.json", {"candidates": []}) or {}).get("candidates")
    tp = _doc(docs, "triage_proposals.json", None)
    props = tp.get("proposals", {}) if isinstance(tp, dict) else {}
    srcs = (_doc(docs, "sources.json", {"sources": []}) or {}).get("sources", [])
    if cover is None:
        cov, sources_ok = coverage_inputs(docs)
        cover = coverage_of(cov, today, sources_ok)
    registry, declared, cov_all = cover

    try:  # the old ``news.load()``: tolerant, ``or {}``, then ``setdefault``; a non-object top level raised
        news_events = _with_defaults(_doc(docs, "news/events.json", {}) or {}, ("events", {}), ("seeded", []))["events"]
    except Exception:
        news_events = {}
    network, problems = check_candidates(docs.get("sources/network.json"))
    config = _doc(docs, "config.json", {})
    return MapInputs(
        inbox=inbox,
        proposals=props if isinstance(props, dict) else {},
        sources=srcs if isinstance(srcs, list) else [],
        declared_sources=declared,
        coverage_ecosystems=registry,
        coverage_all=cov_all,
        signals=(_doc(docs, "real_data.json", {"signals": []}) or {}).get("signals", []),
        scout_items=_rows(lambda: _scout_items(docs)),
        news_events=news_events,
        people=_rows(lambda: people_view.listing(_doc(docs, "people.json", {"people": []}).get("people"), today)),
        events=_rows(lambda: _events_listing(docs, today)),
        watch_open=_rows(lambda: _watch_open(docs)),
        institutions=cities.registry(docs.get("ecosystems.json"))[1],
        network=network,
        network_problems=problems,
        home_base=config.get("home_base") if isinstance(config, dict) else None,
    )


def _with_defaults(d: Any, *defaults: tuple[str, Any]) -> dict[str, Any]:
    """``d.setdefault(k, v)`` for each default, on a shallow COPY (the old load then setdefault; raises as it did
    when ``d`` is not an object)."""
    if not isinstance(d, dict):
        raise TypeError(type(d).__name__)
    out = dict(d)
    for k, v in defaults:
        out.setdefault(k, v)
    return out
