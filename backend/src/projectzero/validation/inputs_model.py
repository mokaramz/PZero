"""What Validation is computed from (review 027a): ONE explicit, frozen ``ValidationInputs``, and the pure adapter that
builds it from old-format documents the way the old loaders did (``inputs_from_docs``; the goldens use it). The
database adapter must produce the same values, in the same ORDER, from the stores.

Every field names the old call it replaces. The old ``services/validation.py`` read each store itself, inside
``build``, ``source_alpha``, ``calibration``, ``_headline``, ``scout_summary``, ``_ai_cost``, ``_snapshot``,
``_routing`` (``compressor.metrics``), ``_verification_calibration`` and the Scout packet; every JSON document was
read TOLERANTLY (``storage.load_json(..., tolerant=True)``: a missing or unreadable file is the default) and every
JSONL log through ``storage.read_text`` (missing or undecodable: ``""``) then line by line (a line that is not JSON
or not an object is skipped). Each field below is the value those calls RETURNED.

The append-only logs are kept as their RAW TEXT (universal newlines, as ``read_text`` returned it): the order of
their lines is semantic (``_live`` over every row, the "last 30" windows, the snapshot "is the last row today"
check, ``log[-1]``), and the in-memory daily snapshot (decision a) is appended to that text exactly as the old
``storage.append_line`` appended to the file. Order matters wherever the old code iterated: the inbox candidates (file
order: the first-seen ties, the entity order of every ``Counter`` and table), the Conviction records (file order),
the founder calls (``calls`` key order), the Scout Intake items (stored order) and ``cycles`` (KEY order: the latest
cycle), the news events (archive KEY order: the earliest-observation tie), the triage decisions (line order: the last
line per candidate wins, ``calibration.latest`` is in first-appearance order) and ``sources.json`` (list order: a
duplicate id's last row wins).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from projectzero.dealflow.ranking.service import is_legacy_inbox_record, ranking_input
from projectzero.dealflow.scan.records import is_scan_record
from projectzero.network.view import berlin_now

DECISION_LOG = "triage_decisions.jsonl"
VERIFICATION_LOG = "verification_decisions.jsonl"
INFERENCE_LEDGER = "inference_ledger.jsonl"


@dataclass(frozen=True)
class ValidationInputs:
    """Validation's inputs, as the old calls returned them. Never mutated by Validation (decision a)."""

    # old ``storage.load_json("inbox.json", {"candidates": []}, tolerant=True).get("candidates")`` (``build`` and
    # ``_source_learning``): the Deal Flow candidate records in FILE order (``compat.records(..., ("id",))`` is applied
    # by Validation). Decision (f): a candidate the new intake created carries ``first_seen`` = the Berlin calendar
    # date of its ``first_seen_at`` and the intake ``discovery_tier`` of its ranking input (``candidate_record``)
    inbox: Any = None
    # old ``storage.load_json("triage_proposals.json", {"proposals": {}}, tolerant=True).get("proposals", {})``: the
    # CURRENT machine proposal per candidate id ``{candidate_id: {status, proposal, capital_stage, themes, ...}}``,
    # keyed by the OLD candidate ids (lookup only; order irrelevant)
    proposals: Any = field(default_factory=dict)
    # old ``triage_review.decisions()``: the raw text of ``triage_decisions.jsonl`` (line order; the last line per
    # ``candidate_id`` wins; read by ``build``, ``calibration``, ``source_alpha`` and ``compressor.metrics``). The
    # database adapter: the archived lines, then the ``triage_decisions`` rows by ``seq`` (review 035a)
    decisions_log: str = ""
    # review 035a (decision e): old candidate id -> survivor (the ``candidate`` merge aliases). The latest decision
    # line is chosen per survivor; a line keeps its recorded id. Empty (the old files): every id is its own survivor
    candidate_aliases: dict[str, str] = field(default_factory=dict)
    # old ``storage.load_json("real_data.json", {"signals": []}, tolerant=True).get("signals")`` (``_pipeline_rows``):
    # the Conviction records in FILE order, dropped ones included, with the STORED ``imq`` snapshot
    signals: Any = None
    # old ``storage.load_json("founder_calls.json", {}, tolerant=True) or {}``: the founder-calls document ``{calls:
    # {id: call}, companies: {id: company}}``; the ``calls`` KEY order is the order the calls are read (the last call
    # of a company wins)
    founder_calls: Any = field(default_factory=dict)
    # old ``(storage.load_json("scout_intake.json", {}, tolerant=True) or {}).get("items")``: the archived Scout Intake
    # items in STORED order ...
    scout_items: Any = None
    # ... and ``.get("cycles")`` of the same document as stored: its KEY order is the cycle order (``scout_summary``:
    # the page's "latest cycle" is the last one); read from the byte-exact archive, never through JSONB
    scout_cycles: Any = None
    # old ``storage.load_json("sources.json", {"sources": []}, tolerant=True).get("sources", [])`` (``_sources``): the
    # Deal Flow source records as STORED, in list order; only ``id`` / ``name`` are read
    sources: Any = field(default_factory=list)
    # old ``news.load()`` (``news.observations``): ``storage.load_json("news/events.json", {}, tolerant=True) or {}``,
    # the archived News document; its ``events`` KEY order decides the earliest-observation tie (decision b)
    news: Any = field(default_factory=dict)
    # old ``source_network.load()`` (``lifecycle_map``): ``storage.load_json("sources/network.json", {},
    # tolerant=True) or {}``, the archived source-network document (``candidates`` in key order)
    network: Any = field(default_factory=dict)
    # old ``compressor.load()`` (``_routing``): ``storage.load_json("queue_routing.json", {}, tolerant=True) or {}``,
    # ``{routes: {candidate_id: route}, left_queue: {candidate_id: route}, ...}`` keyed by the OLD candidate ids
    queue_routing: Any = field(default_factory=dict)
    # old ``_read_jsonl(OUTCOMES)``: the raw text of ``validation/outcomes.jsonl`` (line order)
    outcomes_log: str = ""
    # old ``_read_jsonl(AUDITS)``: the raw text of ``validation/audits.jsonl`` (line order)
    audits_log: str = ""
    # old ``_read_jsonl(SNAPSHOTS)`` BEFORE the view's ``_snapshot`` append: the raw text of
    # ``validation/snapshots.jsonl`` (line order; today's point is appended to it in memory, decision a)
    snapshots_log: str = ""
    # old ``_read_jsonl(SCOUT_LOG)``: the raw text of ``validation/scout_feedback.jsonl`` (line order; the last row is
    # ``scout.last_packet``)
    scout_log: str = ""
    # old ``verification.decisions()``: the raw text of ``verification_decisions.jsonl`` (line order)
    verification_log: str = ""
    # old ``_ai_cost``: the JSON values of the ``inference_ledger.jsonl`` lines in line order (a line that is not JSON
    # skipped); each is read as ``{ts, usd}`` with ``ts`` the naive Berlin wall time ``%Y-%m-%dT%H:%M:%S`` (the
    # database adapter: ``model_ledger.at`` in Europe/Berlin, formatted so, and its ``usd``)
    inference_ledger: list[Any] = field(default_factory=list)
    # review 028a (additive): what the old ``news.view()`` / ``news.learnings()`` / ``news_sources.scout_lines()``
    # read for Validation's News panel (``_news_metrics``) and the packet's News sections: a ``news.NewsInputs``
    # WITHOUT entities (``news.base_from_docs``: the events archive, the actions / runs logs, the metric cache, the
    # scan history, the curated cases, ...). Validation completes it with the entities it built itself (decision b:
    # one entity build per request). ``None`` (a hand-built ``ValidationInputs``): an empty News store
    news_inputs: Any = None


MISSING = object()


def _doc(docs: Mapping[str, Any], name: str, default: Any) -> Any:
    """The old tolerant ``storage.load_json(name, default)``: a missing document is (a copy of) the default."""
    v = docs.get(name, MISSING)
    return copy.deepcopy(default) if v is MISSING else v


def text(raw: Any) -> str:
    """The old ``storage.read_text``: ``""`` when missing or undecodable; universal newlines (text mode)."""
    if raw is None:
        return ""
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = bytes(raw).decode("utf-8")
        except UnicodeDecodeError:
            return ""
    if not isinstance(raw, str):
        return ""
    return raw.replace("\r\n", "\n").replace("\r", "\n")


def json_values(raw: str) -> list[Any]:
    """The JSON value of every line of ``raw`` that parses (the old ``_ai_cost`` loop, before its ``r.get``)."""
    out: list[Any] = []
    for line in raw.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def inputs_from_docs(
    docs: Mapping[str, Any], today: Any = None, aliases: Mapping[str, str] | None = None
) -> ValidationInputs:
    """``ValidationInputs`` from old-format documents ``{path: parsed JSON}`` (the JSONL logs: their raw text, ``str``
    or ``bytes``), read as the old loaders read them, tolerance included. ``today`` is accepted for symmetry with the
    other ports (the inputs do not depend on the clock). Pure: ``docs`` is never modified."""
    from projectzero.news.inputs_model import base_from_docs  # local: News imports Validation

    intake = _doc(docs, "scout_intake.json", {}) or {}
    return ValidationInputs(
        inbox=(_doc(docs, "inbox.json", {"candidates": []}) or {}).get("candidates"),
        proposals=(_doc(docs, "triage_proposals.json", {"proposals": {}}) or {}).get("proposals", {}),
        decisions_log=text(docs.get(DECISION_LOG)),
        signals=(_doc(docs, "real_data.json", {"signals": []}) or {}).get("signals"),
        founder_calls=_doc(docs, "founder_calls.json", {}) or {},
        scout_items=intake.get("items"),
        scout_cycles=intake.get("cycles"),
        sources=(_doc(docs, "sources.json", {"sources": []}) or {}).get("sources", []),
        news=_doc(docs, "news/events.json", {}) or {},
        network=_doc(docs, "sources/network.json", {}) or {},
        queue_routing=_doc(docs, "queue_routing.json", {}) or {},
        outcomes_log=text(docs.get("validation/outcomes.jsonl")),
        audits_log=text(docs.get("validation/audits.jsonl")),
        snapshots_log=text(docs.get("validation/snapshots.jsonl")),
        scout_log=text(docs.get("validation/scout_feedback.jsonl")),
        verification_log=text(docs.get(VERIFICATION_LOG)),
        inference_ledger=json_values(text(docs.get(INFERENCE_LEDGER))),
        news_inputs=base_from_docs(docs),
        candidate_aliases=dict(aliases or {}),
    )


def candidate_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """Decision (f): the inbox record Validation reads for one stored candidate row (``candidates``: ``legacy``,
    ``attrs``, ``status``, ``first_seen_at``, ...), for the database adapter.

    * An IMPORTED candidate (``legacy`` is an old inbox record) keeps the legacy rules: the old record as the ranking
      reads it (``ranking.service.ranking_input``: today's status as ``decision``, today's notes), so ``first_seen`` /
      ``detected_on``, ``discovery_tier``, ``also_seen``, ``all_source_ids`` and ``quality_source_id`` are the old ones.
    * A candidate the NEW intake created has no old ``first_seen``: it is the BERLIN calendar date of the row's
      ``first_seen_at`` (``""`` without one). Its ``discovery_tier`` is the intake's own tier from the same ranking
      input (the tagging record: ``manual`` or ``pre_company``, kept distinct; an untagged partial record has none),
      and its provenance is the ranking input's (the tagging record's ``source_id`` / ``all_source_ids`` /
      ``quality_source_id`` / ``also_seen``; a partial record only ``source_id``).
    """
    c, _kind = ranking_input(row)
    if is_legacy_inbox_record(row.get("legacy")) or is_scan_record((row.get("attrs") or {}).get("scan_record")):
        return c  # imported, or made by the Deal Flow scan (review 034a): the old record's own first_seen / tier
    seen = row.get("first_seen_at")
    c["first_seen"] = berlin_now(seen).date().isoformat() if isinstance(seen, datetime) else ""
    return c
