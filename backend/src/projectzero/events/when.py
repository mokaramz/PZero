"""Event dates: the old ``domain/events.py`` rules (revision 6c739b9), ported VERBATIM with the clock as a parameter.

``parse_when`` (:442-493), ``extract_date`` (:1261-1290), ``_aware`` (:557-563) and ``event_span`` (:566-578) behave
exactly like the old code, raising where it raised; ``tests/ops/test_events_when_golden.py`` holds them to goldens the
old interpreter generated (``python -m projectzero.ops.parity_events goldens``). The only change is the clock:
``extract_date`` read ``date.today()`` (the machine's local date) to give a year to "Sept 20"; here ``today`` is passed.

``stated`` and ``span_of`` are new: how a legacy value becomes columns (review 014). They never raise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import timezone as _tz
from typing import Any, Literal
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")  # the old module fell back to a built-in EU rule only without a tz database

# ------------------------------------------------------------------ WHEN: canonical date normalisation (verbatim)
_ISO_DT = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})(?::\d{2})?(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")
_ISO_D = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_DMY = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{2,4})(?:\s+(\d{1,2}):(\d{2}))?$")

# insertion order matters: the month alternation below is built from it ("jan" is tried before "januar")
_MONTHS = {
    m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])
}
_MONTHS.update(
    {
        "januar": 1,
        "februar": 2,
        "märz": 3,
        "maerz": 3,
        "april": 4,
        "mai": 5,
        "juni": 6,
        "juli": 7,
        "august": 8,
        "september": 9,
        "oktober": 10,
        "november": 11,
        "dezember": 12,
        "january": 1,
        "february": 2,
        "march": 3,
        "june": 6,
        "july": 7,
        "october": 10,
        "december": 12,
    }
)


def extract_date(text: Any, *, today: date) -> str:
    """Best-effort date from free text -> ISO string or ''. Prefers day.month.year, then 'Month DD[, YYYY]', then
    'DD Month'. A month without a year is this year if the month has not passed, else next year (``today``)."""
    t = " " + (text or "").lower() + " "
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", t)
    if m:
        dd, mm, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        yy = yy + 2000 if yy < 100 else yy
        try:
            return date(yy, mm, dd).isoformat()
        except ValueError:
            pass
    m = re.search(r"(" + "|".join(_MONTHS) + r")[a-zäöüé]*\.?\s+(\d{1,2})(?!\d)(?:\s*[,.]?\s*(20\d\d))?", t)
    if not m:
        m2 = re.search(r"(\d{1,2})\.?\s+(" + "|".join(_MONTHS) + r")[a-zäöüé]*\.?(?:\s*(20\d\d))?", t)
        if m2:
            mon, dd, ys = _MONTHS[m2.group(2)], int(m2.group(1)), m2.group(3)
        else:
            return ""
    else:
        mon, dd, ys = _MONTHS[m.group(1)], int(m.group(2)), m.group(3)
    year = int(ys) if ys else (today.year if mon >= today.month else today.year + 1)
    try:
        return date(year, mon, dd).isoformat()
    except ValueError:
        return ""


def parse_when(raw: Any, *, today: date) -> tuple[date | None, str, str]:
    """-> (date|None, 'HH:MM'|'', tz_note). Date-only strings are calendar dates and are NOT converted.
    'YYYY-MM-DDTHH:MM' without offset is treated as Berlin wall-clock time. With Z/offset it is converted
    to Europe/Berlin (a Saturday 23:30 UTC event lands on Sunday 01:30 Berlin, as it should)."""
    t = (raw or "").strip()
    if not t:
        return None, "", ""
    m = _ISO_DT.match(t)
    if m:
        d0, hh, mm, off = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
        try:
            base = date.fromisoformat(d0)
        except ValueError:
            return None, "", ""
        if off:
            if off == "Z":
                tzinfo: Any = UTC
            else:
                sign = 1 if off[0] == "+" else -1
                o = off[1:].replace(":", "")
                tzinfo = _tz(sign * timedelta(hours=int(o[:2]), minutes=int(o[2:])))
            dt = datetime(base.year, base.month, base.day, hh, mm, tzinfo=tzinfo).astimezone(BERLIN)
            return dt.date(), f"{dt.hour:02d}:{dt.minute:02d}", "converted to Europe/Berlin"
        return base, f"{hh:02d}:{mm:02d}", "Europe/Berlin"
    m = _ISO_D.match(t)
    if m:
        try:
            return date.fromisoformat(m.group(1)), "", ""
        except ValueError:
            return None, "", ""
    m = _DMY.match(t)
    if m:
        dd, mo, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        yy = yy + 2000 if yy < 100 else yy
        try:
            d0 = date(yy, mo, dd)
        except ValueError:
            return None, "", ""
        return (
            d0,
            (f"{int(m.group(4)):02d}:{int(m.group(5)):02d}" if m.group(4) else ""),
            ("Europe/Berlin" if m.group(4) else ""),
        )
    iso = extract_date(t, today=today)  # free text such as 'Sept 20' / '20 September 2026'
    if iso:
        try:
            return date.fromisoformat(iso), "", ""
        except ValueError:
            pass
    return None, "", ""


def _aware(d0: date, hhmm: str, end: bool = False) -> datetime:
    """Europe/Berlin-aware datetime for a calendar date + optional 'HH:MM'. Date-only ends cover the whole day."""
    if hhmm:
        hh, mm = [int(x) for x in hhmm.split(":")]
        return datetime(d0.year, d0.month, d0.day, hh, mm, tzinfo=BERLIN)
    return datetime(d0.year, d0.month, d0.day, tzinfo=BERLIN) + (timedelta(days=1) if end else timedelta(0))


def _span(sd: date, st: str, ed: date | None, et: str) -> tuple[datetime, datetime]:
    """The old ``event_span`` after its two ``parse_when`` calls. The end is EXCLUSIVE."""
    if ed is None or ed < sd:
        ed, et = sd, (et if ed == sd else "")
    start_dt = _aware(sd, st)
    end_dt = _aware(ed, et, end=True) if not et else _aware(ed, et)
    if end_dt <= start_dt:  # e.g. same-day event with only a start time: assume it ends that day
        end_dt = _aware(sd, "", end=True)
    return start_dt, end_dt


def event_span(e: dict[str, Any], *, today: date) -> tuple[datetime | None, datetime | None]:
    """-> (start_dt, end_dt) timezone-aware, or (None, None). A date-only event spans the whole calendar day(s)."""
    sd, st, _ = parse_when(e.get("start"), today=today)
    if sd is None:
        return None, None
    ed, et, _ = parse_when(e.get("end"), today=today)
    return _span(sd, st, ed, et)


# ------------------------------------------------------------------ review 014: a legacy value as columns
Kind = Literal["absent", "date_only", "timed", "unparseable"]
_HHMM = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")


@dataclass(frozen=True)
class Stated:
    """One stated date. ``time`` is ``None`` when no time was stated; ``why`` says why a value is unparseable."""

    kind: Kind
    date: date | None = None
    time: str | None = None
    why: str | None = None
    free_text: bool = False  # read by the free-text fallback (a missing year comes from ``today``)


def stated(raw: Any, *, today: date) -> Stated:
    """``raw`` as the old ``parse_when`` reads it, without ever raising.

    * ``None`` or blank text: ``absent`` (nothing stated);
    * a date: ``date_only``; a date with a valid ``HH:MM``: ``timed``;
    * anything else is ``unparseable``: not text, no date found, an out-of-range time such as ``25:00`` (the old
      ``event_span`` raised on it), or a value the old ``parse_when`` raised on (e.g. an offset of ``+99:00``).
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return Stated("absent")
    if not isinstance(raw, str):
        return Stated("unparseable", why="not text")
    try:
        d0, hhmm, _ = parse_when(raw, today=today)
    except (ValueError, OverflowError):
        return Stated("unparseable", why="the old parse_when raised")
    if d0 is None:
        return Stated("unparseable", why="no date")
    if hhmm and not _HHMM.fullmatch(hhmm):
        return Stated("unparseable", why="invalid time")
    text = raw.strip()
    free = not (_ISO_DT.match(text) or _ISO_D.match(text) or _DMY.match(text))
    return Stated("timed" if hhmm else "date_only", d0, hhmm or None, free_text=bool(free))


def span_of(start: Stated, end: Stated) -> tuple[datetime | None, datetime | None]:
    """``starts_at`` / ``ends_at``: the old ``event_span`` over the stated values. No start, no span; an absent or
    unparseable end is the start's span (the end of the start day); ``ends_at`` is exclusive."""
    if start.date is None:
        return None, None
    return _span(start.date, start.time or "", end.date, end.time or "")
