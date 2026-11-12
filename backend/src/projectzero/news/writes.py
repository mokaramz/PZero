"""The News writes (review 028b): the old ``services/news.py`` ``decide_outcome``, ``audit_miss`` and
``add_backcast_signal`` at revision 6c739b9, ported line for line as PURE functions over the 028a ``NewsInputs``
(plus the 027b ``ValidationInputs`` where the old code called ``services/validation``). Nothing here reads a store or
writes one: each write returns a ``NewsWritten`` and the caller stores it (ONE transaction) or refuses.

* ``NewsWritten.answer``: exactly what the old route answered with 200 (``{ok: true, **row}``, ``{ok: true,
  already: true, **previous}``, ``{ok: true, audit}``, ``{ok: true, signal}``).
* ``NewsWritten.action_line``: the exact line the old code appended to ``news/actions.jsonl`` (without its line end:
  the old ``storage.append_line`` added ``"\\n"``; its ``"\\n" -> " "`` never applies to a JSON dump), or ``None``.
  Decision (c), the three old encodings byte for byte: ``outcome_decision`` sorted keys, ``ensure_ascii=False``;
  ``miss_audit`` the default ``json.dumps`` (insertion order, ASCII escapes); ``backcast_signal`` insertion order,
  ``ensure_ascii=False``.
* ``NewsWritten.validation_appends``: the ``(log, line)`` pairs of ``validation.writes`` (027b), appended BEFORE the
  action line in the old code (decision a: the store commits both together).
* ``NewsWritten.event``: for a backcast, ``(event_id, record)``: the WHOLE updated event as the old ``_save``
  wrote it and the next ``load()`` read it back (a JSON round trip: its key order is the stored order, a new
  ``backcast`` key last); ``None`` otherwise. The old ``_save`` rewrote the whole document; every other event, and
  the ``seeded`` list, are unchanged by a backcast (the two ``load()`` ``setdefault`` keys aside, which every read
  applies anyway).

Refusals raise ``NewsError`` (a ``ValueError``) with the old texts; the Validation refusals inside a confirm or an
audit raise 027b's ``ValidationError`` (also a ``ValueError``). The old route turned any ``ValueError`` into 400 and
anything else into 500. Nothing is appended either way. The check orders are the old ones (decision b):

* ``decide_outcome``: the decision, the event lookup, "already confirmed" (once the LATEST ``outcome_decision`` line
  of the event is a confirm, ANY valid decision answers it again and appends nothing), then, for a confirm, the kind;
* ``add_backcast_signal``: the date, the URL, then the event lookup;
* ``audit_miss``: the event lookup (with a company), then 027b's ``audit`` (its frozen miss context is built before
  ``why_missed`` is checked).

What each write reads (the caller loads it FRESH inside the write transaction, after the locks and
``ensure_seeded``, so the write sees the seeded curated cases):

* ``decide_outcome``: ``inputs.events`` (the seeded document) and ``inputs.actions_log`` (the last decision per
  event); a confirm calls ``validation.writes.outcome``, which reads no store (``validation`` may be ``None``: an
  empty ``ValidationInputs`` is passed); ``today`` (the future check), ``now`` (``at``, ``recorded_at``, the id),
  ``new_hex`` (one call, for the ``oc-`` id);
* ``audit_miss``: ``inputs.events``, ``inputs.scan_history`` (``_pz_start``) and the WHOLE fresh ``validation``
  inputs (027b ``audit`` freezes the miss context over ``validation.entities``, which read the events document too:
  ``validation.news`` must be the same seeded document); ``today``, ``now``, ``new_hex`` (one call, ``au-``);
* ``add_backcast_signal``: ``inputs.events`` only, and ``now`` (``added_at``); ``today``, ``new_hex`` and
  ``validation`` are accepted for one uniform signature and not read.

``ensure_seeded`` is the old GET-time seeding (the old view's guard, then ``seed_cases``; 028a decision a) for the
store: the document after seeding and the per-event changes to write. ``with_events`` and ``applied`` give the
inputs after a seeding and after a write, as the old files would have read back (the parity and the tests).
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any, NamedTuple

from projectzero.news.catalog import OUTCOME_KIND, SENSOR_FOR
from projectzero.news.core import _decisions, _pz_start, backcast_summary, load, seed_cases
from projectzero.news.inputs_model import NewsInputs
from projectzero.validation import writes as validation_writes
from projectzero.validation.core import ts
from projectzero.validation.inputs_model import ValidationInputs
from projectzero.validation.writes import NewHex

_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


class NewsError(ValueError):
    """An old News refusal (the route: 400 ``{ok: false, error}``)."""


@dataclass(frozen=True)
class NewsWritten:
    """One News write: the old 200 answer, the action line, the Validation lines and the updated event."""

    answer: dict[str, Any]
    action_line: str | None = None
    validation_appends: list[tuple[str, str]] = field(default_factory=list)
    event: tuple[str, dict[str, Any]] | None = None


class SeedChange(NamedTuple):
    """One event the seeding added (``before`` is ``None``) or updated (a curated case's research refresh)."""

    event_id: str
    before: Any
    after: dict[str, Any]


def _text(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


# ------------------------------------------------------------------------------------------------------- seeding
def ensure_seeded(events_doc: Any, cases: Any, now: datetime) -> tuple[Any, list[SeedChange]]:
    """The old GET-time seeding for the store: the old view's guard (the case folder exists and fewer case ids are
    recorded as ``seeded`` than case files exist), then 028a's ``core.seed_cases``. Returns ``(document, changes)``:
    the document every read and the write must then see (unchanged when nothing was seeded), and each event the
    seeding added or updated, in document order, with its stored record before (``None``: new) and after. When
    ``changes`` is non-empty the store writes each ``after`` record, a new event at the end of the archive order, and
    the document's other top-level keys (``seeded``, extended in case order). A case file that is not JSON raises
    (``json.JSONDecodeError``) as the old seeding did. Pure: ``events_doc`` is never modified."""
    if cases is None or len(load(events_doc)["seeded"]) >= len(cases):
        return events_doc, []
    doc, added = seed_cases(events_doc, cases, now)
    if not added:
        return events_doc, []
    before = load(events_doc)["events"]
    changes = [
        SeedChange(eid, before.get(eid), rec)
        for eid, rec in doc["events"].items()
        if eid not in before or _text(before[eid]) != _text(rec)
    ]
    return doc, changes


def with_events(inputs: NewsInputs, validation: ValidationInputs, doc: Any) -> tuple[NewsInputs, ValidationInputs]:
    """Both inputs reading the events document ``doc`` (after a seeding or a backcast): ``NewsInputs.events``,
    ``ValidationInputs.news`` (the observations) and ``ValidationInputs.news_inputs``."""
    base = validation.news_inputs if validation.news_inputs is not None else NewsInputs()
    return replace(inputs, events=doc), replace(validation, news=doc, news_inputs=replace(base, events=doc))


def _append(log: str, line: str) -> str:
    return log + line.replace("\n", " ") + "\n"  # the old ``storage.append_line``


def applied(
    inputs: NewsInputs, validation: ValidationInputs, written: NewsWritten
) -> tuple[NewsInputs, ValidationInputs]:
    """The inputs after ``written`` was stored, as the old files would have read back: the action line appended to
    ``actions_log``, the Validation lines to their logs (``validation.writes.appended``, mirrored in the News copies
    of the outcome / audit logs), the backcast record in place in the events document."""
    news = inputs
    if written.event is not None:
        eid, record = written.event
        d = load(inputs.events)
        news, validation = with_events(news, validation, {**d, "events": {**d["events"], eid: record}})
    validation = validation_writes.appended(validation, written.validation_appends)
    for log, line in written.validation_appends:
        if log == validation_writes.OUTCOMES:
            news = replace(news, outcomes_log=_append(news.outcomes_log, line))
        elif log == validation_writes.AUDITS:
            news = replace(news, audits_log=_append(news.audits_log, line))
    if written.action_line is not None:
        news = replace(news, actions_log=_append(news.actions_log, written.action_line))
    base = validation.news_inputs if validation.news_inputs is not None else NewsInputs()
    shared = replace(
        base,
        events=news.events,
        actions_log=news.actions_log,
        outcomes_log=news.outcomes_log,
        audits_log=news.audits_log,
    )
    return news, replace(validation, news_inputs=shared)


# -------------------------------------------------------------------------------------------------------- writes
def decide_outcome(
    inputs: NewsInputs,
    body: dict[str, Any],
    *,
    today: date,
    now: datetime,
    new_hex: NewHex,
    validation: ValidationInputs | None = None,
) -> NewsWritten:
    """Mohamed's answer to an outcome proposal. Only CONFIRM writes the trusted Validation outcome ledger."""
    eid, decision = str(body.get("event_id") or ""), body.get("decision")
    if decision not in ("confirm", "reject", "not_enough"):
        raise NewsError("decision must be confirm, reject or not_enough")
    e = load(inputs.events)["events"].get(eid)
    if not e:
        raise NewsError("no such news event")
    kind = OUTCOME_KIND.get(e["event_type"])
    prev = _decisions(inputs.actions_log).get(eid)
    if prev and prev.get("decision") == "confirm":  # a double click never records a second outcome
        return NewsWritten({"ok": True, "already": True, **prev})
    row: dict[str, Any] = {"kind": "outcome_decision", "event_id": eid, "decision": decision, "at": ts(now)}
    appends: list[tuple[str, str]] = []
    if decision == "confirm":
        if not kind or not e.get("company"):
            raise NewsError("this news event cannot become an outcome")
        url = next((s["url"] for s in e["sources"] if s["independence"] != "syndicated"), e["sources"][0]["url"])
        out = validation_writes.outcome(
            validation if validation is not None else ValidationInputs(),
            {
                "company": e["company"],
                "kind": kind,
                "event_date": e["event_date"],
                "evidence_url": url,
                "note": f"confirmed from News: {e['headline'][:200]}",
            },
            today=today,
            now=now,
            new_hex=new_hex,
        )
        row["outcome_id"] = out.answer["entry"]["id"]
        appends = out.appends
    return NewsWritten({"ok": True, **row}, json.dumps(row, ensure_ascii=False, sort_keys=True), appends)


def audit_miss(
    inputs: NewsInputs,
    body: dict[str, Any],
    *,
    today: date,
    now: datetime,
    new_hex: NewHex,
    validation: ValidationInputs | None = None,
) -> NewsWritten:
    """One click from a news event to a Validation miss audit, prefilled with what News already knows."""
    if validation is None:
        raise TypeError("audit_miss needs the current Validation inputs (the frozen miss context)")
    eid = str(body.get("event_id") or "")
    e = load(inputs.events)["events"].get(eid)
    if not e or not e.get("company"):
        raise NewsError("no such news event with a named company")
    bc = backcast_summary(e, _pz_start(inputs.scan_history)) or {}
    first = bc.get("earliest_plausible_signal") or {}
    out = validation_writes.audit(
        validation,
        {
            "type": "miss",
            "company": e["company"],
            "why_missed": body.get("why_missed") or "other",
            "preventable": body.get("preventable") or "unclear",
            "earliest_signal": body.get("earliest_signal") or first.get("text") or "",
            "earliest_signal_date": body.get("earliest_signal_date") or first.get("date") or "",
            "signal_source": body.get("signal_source") or first.get("url") or "",
            "should_have_found": body.get("should_have_found") or (bc.get("best_sensor") if first else ""),
            "improvement": body.get("improvement") or "",
            "outcome_date": e["event_date"],
            "note": f"from News: {e['headline'][:200]} ({e['sources'][0]['url']})",
        },
        today=today,
        now=now,
        new_hex=new_hex,
    )
    row = out.answer["entry"]
    line = json.dumps({"kind": "miss_audit", "event_id": eid, "audit_id": row["id"], "at": ts(now)})
    return NewsWritten({"ok": True, "audit": row}, line, out.appends)


def add_backcast_signal(
    inputs: NewsInputs,
    body: dict[str, Any],
    *,
    today: date,
    now: datetime,
    new_hex: NewHex,
    validation: ValidationInputs | None = None,
) -> NewsWritten:
    """Mohamed (or pasted research) adds a dated, sourced precursor signal. Never generated by a model."""
    eid = str(body.get("event_id") or "")
    sig_date = str(body.get("date") or "")[:10]
    url = str(body.get("url") or "").strip()
    if not _DATE.match(sig_date):
        raise NewsError("date as YYYY, YYYY-MM or YYYY-MM-DD")
    if not url.startswith(("http://", "https://")):
        raise NewsError("a source URL is required — a backcast signal is evidence, not a guess")
    kind = body.get("kind") if body.get("kind") in ("known_early_signal", "in_retrospect") else "known_early_signal"
    fam = body.get("family") if body.get("family") in SENSOR_FOR else "ecosystem"
    d = load(inputs.events)
    e = d["events"].get(eid)
    if not e:
        raise NewsError("no such news event")
    e = copy.deepcopy(e)  # the inputs are never modified
    sig = {
        "date": sig_date,
        "precision": {4: "year", 7: "month"}.get(len(sig_date), "day"),
        "text": str(body.get("text") or "")[:300],
        "family": fam,
        "url": url,
        "kind": kind,
        "added_by": "mohamed",
        "added_at": ts(now),
    }
    e.setdefault("backcast", []).append(sig)
    record = json.loads(json.dumps(e, ensure_ascii=False))  # the old ``_save`` then ``load``
    line = json.dumps({"kind": "backcast_signal", "event_id": eid, "signal": sig}, ensure_ascii=False)
    return NewsWritten({"ok": True, "signal": sig}, line, [], (eid, record))
