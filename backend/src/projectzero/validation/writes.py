"""The Validation writes (review 027b): the old ``services/validation.py`` ``record_outcome``, ``record_audit`` (with
``_miss_context``), ``retract``, ``import_benchmark`` and ``scout_packet(mark=True)`` at revision 6c739b9, ported line
for line as PURE functions. Nothing here reads a store or writes one: each function takes the CURRENT
``ValidationInputs`` and returns a ``Written`` -- the old route's answer and the lines to append; the caller appends
them (one transaction, under the Validation lock) or refuses.

* ``Written.answer``: exactly what the old route answered with 200 -- ``{ok: true, entry}`` for an outcome, an audit
  and a retraction (the entry in INSERTION order; the stored line is sorted), the benchmark summary WITHOUT ``ok`` (the
  old route returned it bare), the packet for the mark.
* ``Written.appends``: ``[(log, line)]`` in append order, ``log`` one of ``outcomes`` / ``audits`` /
  ``scout_feedback`` (the ``validation_log.log`` values) and ``line`` the old ``json.dumps(row, ensure_ascii=False,
  sort_keys=True)`` exactly -- the Scout log's mark line keeps the old ``json.dumps(row, sort_keys=True)`` (ASCII
  escapes). The old ``storage.append_line`` added ``"\\n"`` (its ``"\\n" -> " "`` replacement never applies to a JSON
  dump); ``appended`` applies the lines to the inputs' log texts exactly so, for the parity and the tests.
* Refusals raise ``ValidationError`` with the old texts (the route: 400 ``{ok: false, error}``); a stale packet mark
  raises ``StalePacket`` (the route: 409, decision f). Either way nothing is appended.

The clock and the id seam (decision c). ``today`` is the request's Berlin day (the old ``date.today()``: the future
checks, the entity model); ``now`` the request instant, written as the old naive Berlin ``ledger.now_ts()``
(``%Y-%m-%dT%H:%M:%S``: ``recorded_at`` and the mark's ``at``). The old ids were ``prefix-`` + the first 10 hex of
``sha1("|".join(parts) + "|" + now_ts() + "|" + str(datetime.now().timestamp()))``; the port keeps the prefix, the
parts, the clock and the format and replaces only ``str(datetime.now().timestamp())`` with ``new_hex()`` (the route
passes ``app.state.new_hex`` or a random hex, so tests and the parity are reproducible). ``new_hex`` is called once per
id, at the old ``_id`` call, in the old order.

Declared fixes:

* (e) a benchmark CSV whose first data row has more fields than the header (the old ``None`` key broke ``c.lower()``)
  or that raises ``csv.Error`` was an old 500; both are now ``ValidationError("the CSV could not be read: ...")`` and
  nothing is appended;
* (f) the packet mark: the body is ``{cycle, generated, sha}`` from the packet the page displayed (``generated``: the
  packet's ``Generated`` time as its text prints it, ``generated_at``); the packet is rendered over the current inputs
  at that time and its sha must equal ``sha`` (else ``StalePacket``); the logged sha is the copied text's (the old
  mark regenerated the text with a new ``Generated`` and logged that sha). The answer is the rendered packet.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any

from projectzero.core.body import BadConfirm, confirmed
from projectzero.dealflow.triage.view import decisions as read_jsonl
from projectzero.validation.catalog import (
    _DATE_COLS,
    _NAME_COLS,
    BENCHMARK_KINDS,
    FP_CAUSES,
    KINDS,
    MISS_REASONS,
    REAL_WORLD_STRONG,
)
from projectzero.validation.core import TS_FORMAT, ValidationError, _date, _key, entities, miss_context, ts
from projectzero.validation.inputs_model import ValidationInputs
from projectzero.validation.packet import scout_packet

OUTCOMES = "outcomes"  # validation/outcomes.jsonl
AUDITS = "audits"  # validation/audits.jsonl
SCOUT_LOG = "scout_feedback"  # validation/scout_feedback.jsonl
LOG_FIELDS = {OUTCOMES: "outcomes_log", AUDITS: "audits_log", SCOUT_LOG: "scout_log"}
STALE_PACKET = "the packet changed since it was prepared — prepare it again"  # decision (f)
CSV_UNREADABLE = "the CSV could not be read: "  # decision (e)
GENERATED = re.compile(r"^Generated (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}) · ", re.M)

NewHex = Callable[[], str]


class StalePacket(Exception):  # the route's 409, not a ValidationError (400)
    """Decision (f): the packet rendered at ``generated`` over the current data is not the one the page showed."""

    def __init__(self) -> None:
        super().__init__(STALE_PACKET)


@dataclass(frozen=True)
class Written:
    """One write: the old route's 200 answer and the ``(log, line)`` pairs to append, in order."""

    answer: dict[str, Any]
    appends: list[tuple[str, str]]


def _line(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


def _id(prefix: str, *parts: Any, now: datetime, new_hex: NewHex) -> str:
    """The old ``_id``: ``str(datetime.now().timestamp())`` replaced by ``new_hex()`` (the seam)."""
    raw = "|".join(str(p) for p in parts) + "|" + ts(now) + "|" + new_hex()
    return prefix + "-" + hashlib.sha1(raw.encode()).hexdigest()[:10]


def appended(inputs: ValidationInputs, appends: Iterable[tuple[str, str]]) -> ValidationInputs:
    """The inputs after the lines were appended to their logs, as the old ``storage.append_line`` grew the files."""
    for log, line in appends:
        name = LOG_FIELDS[log]
        inputs = replace(inputs, **{name: getattr(inputs, name) + line.replace("\n", " ") + "\n"})
    return inputs


# ------------------------------------------------------------------------------------------------ outcome and audit
def outcome(inputs: ValidationInputs, body: dict[str, Any], *, today: date, now: datetime, new_hex: NewHex) -> Written:
    """The old ``record_outcome`` (``POST /api/validation_outcome``). It reads no store: ``inputs`` is taken for the
    uniform signature."""
    kind = str(body.get("kind") or "")
    if kind not in KINDS:
        raise ValidationError(f"unknown outcome kind {kind!r}")
    company = str(body.get("company") or "").strip()
    if not company:
        raise ValidationError("company required")
    event_date = _date(body.get("event_date"))
    if not event_date:
        raise ValidationError("event_date (YYYY-MM-DD) required — when it happened in the world, not when you noticed")
    if event_date > today.isoformat():
        raise ValidationError("event_date is in the future — record outcomes only once they have happened")
    url = str(body.get("evidence_url") or "").strip()
    if kind in REAL_WORLD_STRONG and not url.startswith(("http://", "https://")):
        raise ValidationError("a real-world outcome needs an evidence URL (never recorded from memory)")
    row = {
        "id": _id("oc", company, kind, now=now, new_hex=new_hex),
        "recorded_at": ts(now),
        "recorded_by": "mohamed",
        "company": company[:160],
        "entity_key": _key(company),
        "candidate_id": str(body.get("candidate_id") or "")[:80],
        "kind": kind,
        "event_date": event_date,
        "evidence_url": url[:500],
        "benchmark_system": str(body.get("benchmark_system") or "")[:60] if kind in BENCHMARK_KINDS else "",
        "note": str(body.get("note") or "")[:500],
        "supersedes": str(body.get("supersedes") or "") or None,
    }
    return Written({"ok": True, "entry": row}, [(OUTCOMES, _line(row))])


def audit(inputs: ValidationInputs, body: dict[str, Any], *, today: date, now: datetime, new_hex: NewHex) -> Written:
    """The old ``record_audit`` (``POST /api/validation_audit``). A miss freezes ``miss_context`` over the CURRENT
    entities, built BEFORE ``why_missed`` is validated (the old order; a refusal appends nothing either way)."""
    typ = body.get("type")
    company = str(body.get("company") or "").strip()
    if typ not in ("miss", "false_positive") or not company:
        raise ValidationError("type (miss | false_positive) and company required")
    row: dict[str, Any] = {
        "id": _id("au", typ, company, now=now, new_hex=new_hex),
        "type": typ,
        "recorded_at": ts(now),
        "company": company[:160],
        "entity_key": _key(company),
        "note": str(body.get("note") or "")[:800],
        "supersedes": str(body.get("supersedes") or "") or None,
    }
    if typ == "miss":
        row.update(miss_context(entities(inputs, today), row["entity_key"], _date(body.get("outcome_date"))))
        reason = body.get("why_missed")
        if reason not in MISS_REASONS:
            raise ValidationError(f"why_missed must be one of {', '.join(MISS_REASONS)}")
        row.update(
            earliest_signal=str(body.get("earliest_signal") or "")[:300],
            earliest_signal_date=_date(body.get("earliest_signal_date")),
            signal_source=str(body.get("signal_source") or "")[:300],
            should_have_found=str(body.get("should_have_found") or "")[:120],
            why_missed=reason,
            preventable=body.get("preventable") if body.get("preventable") in ("yes", "no", "unclear") else "unclear",
            improvement=str(body.get("improvement") or "")[:500],
        )
    else:
        causes = [c for c in body.get("causes") or [] if c in FP_CAUSES]
        if not causes:
            raise ValidationError(f"at least one cause from {', '.join(FP_CAUSES)}")
        row.update(causes=causes, lesson=str(body.get("lesson") or "")[:500])
    return Written({"ok": True, "entry": row}, [(AUDITS, _line(row))])


def retract(inputs: ValidationInputs, body: dict[str, Any], *, today: date, now: datetime, new_hex: NewHex) -> Written:
    """The old ``retract`` (``POST /api/validation_retract``): the id is searched in the CURRENT outcomes log, then the
    audits log (every parsed line, retractions included); the retraction goes to the log that holds it. ``today`` is
    unused (the old ``retract`` read no date)."""
    rid = str(body.get("id") or "")
    reason = str(body.get("reason") or "").strip()
    if len(reason) < 8:
        raise ValidationError("a retraction needs a reason (at least 8 characters)")
    for log, text in ((OUTCOMES, inputs.outcomes_log), (AUDITS, inputs.audits_log)):
        if any(r.get("id") == rid for r in read_jsonl(text)):
            row = {
                "id": _id("rx", rid, now=now, new_hex=new_hex),
                "retracts": rid,
                "recorded_at": ts(now),
                "reason": reason[:300],
            }
            return Written({"ok": True, "entry": row}, [(log, _line(row))])
    raise ValidationError("no such entry")


# ------------------------------------------------------------------------------------------- external benchmarks
def benchmark_import(
    inputs: ValidationInputs, body: dict[str, Any], *, today: date, now: datetime, new_hex: NewHex
) -> Written:
    """The old ``import_benchmark`` (``POST /api/validation_benchmark_import``): CSV text from an export Mohamed
    supplies -> append-only ``external_db_listing`` outcomes (preview unless ``confirm``; every usable row is appended,
    matched or not). Decision (e): an unreadable CSV is a ``ValidationError``, not a 500. Review 036a: a ``confirm``
    that is supplied but is not a JSON boolean is a ``ValidationError`` (400), so it never appends."""
    try:
        confirm = confirmed(body)
    except BadConfirm as exc:
        raise ValidationError(str(exc)) from None
    system = str(body.get("system") or "").strip()
    text = str(body.get("csv") or "")
    if not system or len(text) < 10:
        raise ValidationError("system name (e.g. Dealroom) and the CSV text are required")
    try:
        rows = list(csv.DictReader(io.StringIO(text)))
    except csv.Error as exc:  # decision (e): the old 500
        raise ValidationError(f"{CSV_UNREADABLE}{exc}") from exc
    if not rows:
        raise ValidationError("no rows in the CSV")
    if None in rows[0]:  # decision (e): the old ``None.lower()`` 500
        raise ValidationError(f"{CSV_UNREADABLE}the first row has more fields than the header")
    cols = {c.lower().strip(): c for c in rows[0]}
    name_col = cols.get(str(body.get("name_column") or "").lower()) or next(
        (cols[c] for c in _NAME_COLS if c in cols), None
    )
    date_col = cols.get(str(body.get("date_column") or "").lower()) or next(
        (cols[c] for c in _DATE_COLS if c in cols), None
    )
    if not name_col or not date_col:
        raise ValidationError(f"could not find the name / date columns — columns are: {', '.join(rows[0])}")
    sha = hashlib.sha256(text.encode()).hexdigest()[:12]
    day = today.isoformat()
    ok: list[dict[str, str]] = []
    skipped: list[str] = []
    for r in rows:
        nm, d = str(r.get(name_col) or "").strip(), _date(r.get(date_col))
        if not nm or not d or d > day:
            skipped.append(nm or "?")
            continue
        ok.append({"company": nm, "event_date": d})
    known = entities(inputs, today)
    matched = [x for x in ok if _key(x["company"]) in known]
    appends: list[tuple[str, str]] = []
    if confirm:
        for x in ok:
            row = {
                "id": _id("bm", system, x["company"], now=now, new_hex=new_hex),
                "recorded_at": ts(now),
                "recorded_by": f"import:{system}:{sha}",
                "company": x["company"][:160],
                "entity_key": _key(x["company"]),
                "candidate_id": "",
                "kind": "external_db_listing",
                "event_date": x["event_date"],
                "evidence_url": f"import://{system.lower()}/{sha}",
                "benchmark_system": system[:60],
                "note": f"imported from a {system} export ({date_col})",
                "supersedes": None,
            }
            appends.append((OUTCOMES, _line(row)))
    summary = {
        "system": system,
        "rows": len(rows),
        "usable": len(ok),
        "skipped": len(skipped),
        "matched_to_pz": len(matched),
        "name_column": name_col,
        "date_column": date_col,
        "imported": confirm,
        "file_sha": sha,
    }
    return Written(summary, appends)


# ---------------------------------------------------------------------------------------------- the packet mark
def generated_at(text: str) -> str:
    """The ``Generated`` time a packet's text prints (its second line, the old naive Berlin ``%Y-%m-%dT%H:%M:%S``);
    ``""`` when absent. The 027a packet answer has no separate field (adding one would change the old answer), so the
    page sends back this value of the packet it displayed."""
    m = GENERATED.search(text or "")
    return m.group(1) if m else ""


def packet_mark(inputs: ValidationInputs, body: dict[str, Any], *, today: date, now: datetime) -> Written:
    """The old ``scout_packet(cycle, mark=True)`` (``POST /api/validation_scout_packet``, "Copy & log handover"), with
    decision (f): ``body = {cycle, generated, sha}``. The packet is rendered over the current inputs at ``generated``
    (its day is the render's ``today``, as the GET that showed it); a different sha raises ``StalePacket``; else the
    old mark row is appended with that sha and ``at`` = ``now``. ``today`` (the request day) is not read: the packet
    is rendered on the day it was generated. A ``generated`` that does not parse is a ``ValidationError``."""
    cycle = str(body.get("cycle") or "")
    try:
        at = datetime.strptime(str(body.get("generated") or ""), TS_FORMAT)
    except ValueError:
        raise ValidationError("generated (the packet's Generated time) required — prepare the packet again") from None
    shown = scout_packet(inputs, cycle, at.date(), at)
    if shown["sha"] != str(body.get("sha") or ""):
        raise StalePacket
    row = {
        "at": ts(now),
        "cycle": cycle or "all",
        "companies": shown["companies"],
        "sha": shown["sha"],
        "handed_over": True,
    }
    return Written(shown, [(SCOUT_LOG, json.dumps(row, sort_keys=True))])
