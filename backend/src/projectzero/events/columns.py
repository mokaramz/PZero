"""The ONE mapping of an event / event lead record onto its typed columns and flattened ``attrs`` (review 014).

The importer (``ops.legacy.map_records.events``) uses it now; the Events writes will use it when the context is ported,
so an imported row and a row the app wrote mirror their record by the same rules (as ``network.people.columns_of``).

* Text columns: a blank value is ``NULL``. ``city`` / ``country`` / ``url`` also read the placeholders ``unknown``,
  ``n/a`` and ``none`` as ``NULL``; any other text is kept (stripped), unknown ``status`` values included.
* Dates: ``when.stated`` / ``when.span_of`` (the old ``parse_when`` / ``event_span``), then ``checked_span``: the old
  code compared Berlin wall-clock times, so a span it accepted can run backwards in UTC (a start inside the
  spring-forward gap), and a start on 9999-12-31 has no exclusive end. Both are a ``span_problem`` (no span); the
  importer refuses them as blockers that name the event (review 014, Codex H-097). ``when`` itself stays the oracle.
* ``lat`` / ``lng``: ``coordinate`` (finite, in range, never a bool; a numeric string is read).
* A promoted value that does not reach its column (not text, an unparseable date, a rejected coordinate) stays in
  ``attrs`` under its own key; blanks and placeholders don't. ``record`` is reserved for application writes and is never
  taken from an imported record (it stays in ``legacy``).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from projectzero.events.when import Stated, free_text_form, span_of, stated

RESERVED_ATTRS = ("id", "record")
EVENT_PROMOTED = ("id", "name", "start", "end", "city", "country", "url", "status", "lat", "lng")
LEAD_PROMOTED = (
    "id", "title", "source", "url", "city", "type", "date", "confidence", "detected_on", "decision", "note",
)  # fmt: skip
LEAD_DECISIONS = ("new", "dismissed", "converted")  # the old Events page: dismiss, convert to an event
_PLACEHOLDERS = frozenset({"unknown", "n/a", "none", ""})
_BLANK = frozenset({""})
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_ISO_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def text(value: Any, placeholders: frozenset[str] = _BLANK) -> str | None:
    """Stripped text, or ``None`` for a non-string, a blank or a placeholder (compared case-insensitively)."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return None if stripped.casefold() in placeholders else stripped


def coordinate(value: Any, limit: float) -> float | None:
    """A latitude (``limit`` 90) or longitude (180): a finite number within ``±limit`` or a plain decimal string of one.
    Bools, NaN / infinity, out-of-range numbers and anything else are ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str) and _NUMBER.fullmatch(value.strip()):
        number = float(value.strip())
    else:
        return None
    return number if math.isfinite(number) and -limit <= number <= limit else None


def _present(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


@dataclass
class Mapped:
    """Columns (including ``attrs``) plus what the importer reports about them."""

    columns: dict[str, Any]
    notes: dict[str, Any] = field(default_factory=dict)


SPAN_PROBLEMS = {
    "overflow": "the exclusive end falls after 9999-12-31",
    "not_forward": "the derived span does not run forward in UTC (a time inside a daylight-saving change)",
}


def checked_span(start: Stated, end: Stated) -> tuple[datetime | None, datetime | None, str | None]:
    """``span_of`` plus the checks the old code never made: ``(starts_at, ends_at, None)``, or ``(None, None, problem)``
    with a key of ``SPAN_PROBLEMS``. The comparison is in UTC (two Berlin datetimes compare by wall clock in Python)."""
    try:
        starts_at, ends_at = span_of(start, end)
        if starts_at is None or ends_at is None:
            return None, None, None
        forward = ends_at.astimezone(UTC) > starts_at.astimezone(UTC)
    except OverflowError:
        return None, None, "overflow"
    return (starts_at, ends_at, None) if forward else (None, None, "not_forward")


def stored_stated(raw: Any, stored_date: date | None, stored_time: str | None) -> Stated:
    """A side as it was STORED (its date and time columns), for a value an edit did not change: the stored result
    governs, so an unrelated edit never re-resolves a free-text date with the write clock (review 016, Codex H-107)."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return Stated("absent")
    if stored_date is None:
        return Stated("unparseable", why="stored as no date", free_text=free_text_form(raw))
    return Stated("timed" if stored_time else "date_only", stored_date, stored_time, free_text=free_text_form(raw))


def event_columns(eid: str, record: dict[str, Any], *, today: date, kept: Mapping[str, Stated] | None = None) -> Mapped:
    """Typed columns + ``attrs`` of an event row for ``record`` (``today`` dates a free-text date without a year).
    ``kept``: the sides ("start" / "end") an edit left unchanged, as stored (``stored_stated``); only the other sides
    are resolved with ``today``, and the span is derived from the effective values of both.
    ``notes["span_problem"]`` set means the row must not be written (its span check would fail)."""
    keep = kept or {}
    start = keep.get("start") or stated(record.get("start"), today=today)
    end = keep.get("end") or stated(record.get("end"), today=today)
    starts_at, ends_at, span_problem = checked_span(start, end)
    name = text(record.get("name"))
    columns: dict[str, Any] = {
        "name": name or eid,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "start_date": start.date,
        "start_time": start.time,
        "end_date": end.date,
        "end_time": end.time,
        "city": text(record.get("city"), _PLACEHOLDERS),
        "country": text(record.get("country"), _PLACEHOLDERS),
        "url": text(record.get("url"), _PLACEHOLDERS),
        "status": text(record.get("status")),
        "lat": coordinate(record.get("lat"), 90),
        "lng": coordinate(record.get("lng"), 180),
    }
    missed = {  # promoted keys whose value did not reach the column: they stay in attrs
        "name": _present(record.get("name")) and not isinstance(record.get("name"), str),
        "start": start.kind == "unparseable",
        "end": end.kind == "unparseable",
        **{k: record.get(k) is not None and not isinstance(record.get(k), str) for k in ("city", "country", "url")},
        "status": record.get("status") is not None and not isinstance(record.get("status"), str),
        "lat": _present(record.get("lat")) and columns["lat"] is None,
        "lng": _present(record.get("lng")) and columns["lng"] is None,
    }
    columns["attrs"] = {
        k: v for k, v in record.items() if k not in RESERVED_ATTRS and (k not in EVENT_PROMOTED or missed.get(k, False))
    }
    notes = {
        "start": start,
        "end": end,
        "span_problem": span_problem,
        "name_from_id": name is None,
        "end_before_start": start.date is not None and end.date is not None and end.date < start.date,
        "lat": _coordinate_note(record.get("lat"), columns["lat"]),
        "lng": _coordinate_note(record.get("lng"), columns["lng"]),
    }
    return Mapped(columns, notes)


def _coordinate_note(raw: Any, kept: float | None) -> str:
    if kept is not None:
        return "kept_from_text" if isinstance(raw, str) else "kept"
    return "dropped" if _present(raw) else "absent"


def lead_columns(record: dict[str, Any], *, today: date) -> Mapped:
    """Typed columns + ``attrs`` of an event lead row. ``decision`` is copied as stated; the importer refuses a value
    outside ``LEAD_DECISIONS`` (the table's check would)."""
    when: Stated = stated(record.get("date"), today=today)
    detected = record.get("detected_on")
    detected_on = (
        date.fromisoformat(detected.strip())
        if isinstance(detected, str) and _ISO_DAY.fullmatch(detected.strip()) and _valid_day(detected.strip())
        else None
    )
    raw_date = record.get("date")
    columns: dict[str, Any] = {
        "title": text(record.get("title")),
        "source": text(record.get("source")),
        "url": text(record.get("url"), _PLACEHOLDERS),
        "city": text(record.get("city"), _PLACEHOLDERS),
        "type": text(record.get("type")),
        "lead_date": when.date,
        "date_raw": text(raw_date),
        "confidence": text(record.get("confidence")),
        "detected_on": detected_on,
        "decision": record.get("decision"),
        "note": text(record.get("note")),
    }
    missed = {
        **{
            k: record.get(k) is not None and not isinstance(record.get(k), str)
            for k in ("title", "source", "url", "city", "type", "confidence", "note", "date")
        },
        "detected_on": _present(detected) and detected_on is None,
    }
    columns["attrs"] = {
        k: v for k, v in record.items() if k not in RESERVED_ATTRS and (k not in LEAD_PROMOTED or missed.get(k, False))
    }
    return Mapped(columns, {"date": when, "detected_on_valid": detected_on is not None})


def _valid_day(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True
