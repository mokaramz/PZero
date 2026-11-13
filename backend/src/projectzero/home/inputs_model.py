"""What the Investment Desk is computed from (review 031a): ONE explicit, frozen ``HomeInputs``, and the pure adapter
that builds it from old-format documents the way the old loaders did (``inputs_from_docs``; the goldens use it). The
database adapter (``home/inputs.py``) must produce the same values, in the same ORDER, from ONE repeatable-read
snapshot (decision c).

Every field names the old call it replaces and the NEW reader that produces it. The old ``ecosys.home()`` read the
events and the people twice (``where_should_i_go(21)`` loaded both again); each is read ONCE here, and nothing is
written (decision a).

Order matters wherever the old code iterated:

* ``signals``: the stored ``real_data.json`` order (then creation order): ``max`` keeps the FIRST of equal scores
  (the best opportunity), and the Omar list's stable sort keeps it for equal ``sent_to_omar`` dates;
* ``people``: file order (``people.listing``'s sort is stable: ``due`` and ``watch`` are cut to 6 in that order; the
  Where-should-I-go contacts are listed in it);
* ``events``: the stored ``events.json`` order (the listing's sort and the ranking's sort are stable);
* ``candidates``: the OLD INBOX order: the first 3 new candidates are ``latest_signals``.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from projectzero.conviction import inputs as conviction_inputs
from projectzero.conviction.operator import OperatorInputs
from projectzero.conviction.records import records
from projectzero.events.store import EventsData
from projectzero.network import view as network_view
from projectzero.today.inputs_model import conviction_docs

UNREADABLE = conviction_inputs.UNREADABLE  # a document that exists but does not parse (the old load raised)


@dataclass(frozen=True)
class HomeInputs:
    """The desk's inputs, as the old calls returned them. Never mutated by the desk (the view works on copies)."""

    # old ``ecosys._load_signals()``: ``compat.records(load_json("real_data.json", {})["signals"], ("company",))``,
    # ``[]`` when that raised (missing / unreadable file, no ``signals``): the STORED Conviction records (not the
    # enriched pipeline view), in stored order. NEW reader: ``[record_of(r) for r in ConvictionStore(conn,
    # schema).entry_rows()]`` (``conviction.store``); the view applies ``records(..., ("company",))`` itself
    signals: list[dict[str, Any]] = field(default_factory=list)
    # old ``people.listing()``'s document: ``load_json("people.json", {"people": []})["people"]`` (``ppl.listing()``
    # in ``home`` and again inside ``where_should_i_go``), in file order; the listing is computed by the view at the
    # request's ``today``. NEW reader: ``network.store.load_people(conn, schema)``
    people: list[dict[str, Any]] = field(default_factory=list)
    # the documents the old ``case_prep.operator_status`` loaded itself (``_load()["cases"]``, the founder calls and
    # evaluations behind ``calls_for``, ``watch/triggers.jsonl`` for the re-open evidence, ``config.json`` ``outreach``
    # for the contact state). NEW reader: ``conviction.inputs.inputs_from(load_documents(conn, schema),
    # people).operator`` (the same as ``conviction.inputs.load_inputs(conn, schema).operator``, without reading the
    # people twice)
    operator: OperatorInputs = field(default_factory=OperatorInputs)
    # old ``events.listing()`` (read twice: ``where_should_i_go(21)`` and ``progress.events_planned``): the event
    # records in stored order and ``event_sources.json`` (each source's city); the listing is computed by the view at
    # the request's ``today`` (decision b). NEW reader: ``events.store.load(conn, schema, today, people=False)`` (its
    # ``pins`` are the persisted free-text dates; the desk's people come from ``people`` above)
    events: EventsData = field(default_factory=lambda: EventsData([], []))
    # old ``compat.records(load_json("inbox.json", {"candidates": []}).get("candidates"), ("id",))``: the Deal Flow
    # candidates in the OLD INBOX order, each with ``id``, ``name``, ``source`` (the source NAME) and ``decision``; the
    # view keeps ``decision == "new"``. NEW reader: ``[{**ranking_input(r)[0], "id": r["id"]} for r in
    # dealflow.inbox_view.candidate_rows(conn, schema)]`` (``dealflow.ranking.service.ranking_input``, exactly as
    # ``inbox_view`` builds its candidates): ``decision`` is ``STATUS_TO_DECISION[status]`` (``new`` -> ``new``);
    # ``source`` is the imported inbox record's ``source`` (a legacy Deal Flow candidate), else the current tagging
    # record's ``source`` (``tagging.make_core``: the primary source's ``name``; a new-intake candidate), else
    # ``", ".join(origins)``
    candidates: list[dict[str, Any]] = field(default_factory=list)


MISSING = object()


def _doc(docs: Mapping[str, Any], name: str, default: Any) -> Any:
    """The old non-tolerant ``storage.load_json(name, default)``: missing is (a copy of) the default; a document that
    does not parse raises (the old route answered 500)."""
    v = docs.get(name, MISSING)
    if v is UNREADABLE:
        raise ValueError(f"{name} could not be read")
    return copy.deepcopy(default) if v is MISSING else v


def load_signals(docs: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The old ``ecosys._load_signals()``: every failure reads as no startups."""
    try:
        doc = _doc(docs, "real_data.json", {})
        return records(doc["signals"], ("company",))
    except Exception:  # v1: a missing/unreadable pipeline simply shows no startups
        return []


def events_data(docs: Mapping[str, Any]) -> EventsData:
    """The old ``events.listing()`` inputs: ``load_json("events.json", {"events": [], "leads": []})["events"]`` (not
    tolerant: a document without ``events`` raised) and the tolerant ``event_sources.json``. No pins: the old code at
    the same clock read the same words."""
    d = _doc(docs, "events.json", {"events": [], "leads": []})
    sources = docs.get("event_sources.json", MISSING)
    documents = {} if sources is MISSING or sources is UNREADABLE else {"event_sources.json": sources}
    return EventsData(events=list(d["events"]), leads=list(d.get("leads", []) or []), documents=documents)


def inputs_from_docs(docs: Mapping[str, Any], today: date, now: datetime) -> HomeInputs:
    """``HomeInputs`` from old-format documents ``{path: parsed JSON}`` (the JSONL logs: their raw text, ``str`` or
    ``bytes``; ``UNREADABLE``: a file that does not parse), read as the old loaders read them. ``now`` is the request
    instant as naive Berlin wall time, ``today`` its date (decision b); no input depends on the clock. Pure: ``docs``
    is never modified (every reader works on copies). Raises where the old ``home()`` raised (an unreadable people,
    events or inbox document)."""
    del today, now  # the inputs are the stored state; the view applies the clock
    docs = {k: v if v is UNREADABLE else copy.deepcopy(v) for k, v in docs.items()}  # the sentinel stays itself
    people = network_view.records(_doc(docs, "people.json", {"people": []}).get("people"))
    operator = conviction_inputs.inputs_from(conviction_docs(docs), people).operator
    inbox = _doc(docs, "inbox.json", {"candidates": []})
    return HomeInputs(
        signals=load_signals(docs),
        people=people,
        operator=operator,
        events=events_data(docs),
        candidates=records(inbox.get("candidates"), ("id",)),
    )
