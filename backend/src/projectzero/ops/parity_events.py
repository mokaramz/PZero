"""Event date parity: ``events.when`` against the OLD ``domain/events.py`` date rules (review 014).

    python -m projectzero.ops.parity_events goldens   # (re)generate golden_v1/oracle_events_when.json
    python -m projectzero.ops.parity_events real      # every event start / end and lead date of the real events.json

The oracle (``scripts/oracle/events_when_oracle.py``) runs the old ``parse_when``, ``extract_date`` and ``event_span``
in the old interpreter with a scratch ``PZ_DATA`` and a fixed ``date.today()``. ``real`` reads the legacy folder through
the read-only snapshot, uses the import clock (today in Berlin) and prints only counts and positions.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from projectzero.events.when import BERLIN, event_span, extract_date, parse_when, span_of, stated
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO

ORACLE = Path(__file__).resolve().parents[4] / "scripts" / "oracle" / "events_when_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_events_when.json"
# a mid-year clock and a late one: a month without a year rolls to next year once it has passed
CLOCKS = ["2026-03-15", "2026-11-11"]


def corpus() -> list[Any]:
    """Synthetic date values that walk every branch of the old ``parse_when`` / ``extract_date``."""
    return [
        # ISO dates
        "2026-09-20", " 2026-09-20 ", "2026-02-29", "2028-02-29", "2026-13-01", "2026-09-31", "0001-01-01",
        "9999-12-31", "2026-09-20 sometime", "2026-09-20/2026-09-22", "20260920", "2026-9-20",
        # ISO datetimes, naive (Berlin wall clock)
        "2026-09-20T18:30", "2026-09-20 18:30", "2026-09-20T18:30:45", "2026-09-20T18:30:45.123456",
        "2026-09-20T00:00", "2026-09-20T23:59", "2026-09-20T24:00", "2026-09-20T25:61", "2026-03-29T02:30",
        "2026-10-25T02:30", "2026-09-20T18", "2026-09-20T18:30:4", "2026-09-31T10:00", "2026-09-20t18:30",
        # with an offset (converted to Berlin)
        "2026-09-20T18:30Z", "2026-09-19T23:30Z", "2026-09-20T18:30+02:00", "2026-09-20T18:30+0200",
        "2026-09-20T18:30-05:00", "2026-09-20T18:30:45+01:00", "2026-01-15T23:30Z", "2026-03-29T00:30Z",
        "2026-03-29T01:30Z", "2026-10-25T00:30Z", "2026-10-25T01:30Z", "2026-09-20T18:30+14:00",
        "2026-09-20T18:30+99:00", "2026-09-20T25:00Z", "0001-01-01T00:30+01:00", "9999-12-31T23:30-01:00",
        "2026-09-20T18:30z", "2026-09-20T18:30 +02:00",
        # DD.MM.YYYY
        "20.09.2026", "20.9.2026", "1.2.26", "20.09.26 18:30", "20.09.2026 9:05", "31.02.2026", "20.09.2026 25:00",
        "20.09.2026, 18:30", "20.09.2026T18:30",
        # free text
        "Sept 20", "Sep 20, 2026", "September 20 2026", "20 September 2026", "20. September 2026", "20 Sept",
        "Mar 3", "Feb 30", "Oct 31", "Dec 1", "Jan 5", "january 5 2027", "15. März 2027", "15. Maerz", "3 Mai",
        "1. Oktober", "Dezember 24", "Juni 7, 2026", "on 12.10.2026 in Berlin", "Doors open Nov 4, 2026 18:00",
        "Q3 2026", "next week", "TBA", "UNKNOWN", "Mayday 5", "may 2026", "20 september 1999", "2026 Sept 20",
        "\uff11\uff12.\uff11\uff10.\uff12\uff10\uff12\uff16", "\uff12\uff10\uff12\uff16-09-20", "Sept \uff120",
        # (above: full-width digits) garbage and blanks
        "", "   ", "garbage", "-", "None", "\n2026-09-20\n",
        # non-text values (the old code raises or reads them as blank)
        None, 0, 20260920, 3.5, True, False, [], ["2026-09-20"], {}, {"start": "2026-09-20"},
    ]  # fmt: skip


def spans() -> list[dict[str, Any]]:
    """Synthetic start / end pairs for ``event_span``: date-only, timed, missing, reversed and same-day ends."""
    pairs = [
        ("2026-09-20", None), ("2026-09-20", ""), ("2026-09-20", "2026-09-20"), ("2026-09-20", "2026-09-22"),
        ("2026-09-20", "2026-09-18"), ("2026-09-20T18:30", None), ("2026-09-20T18:30", "2026-09-20T21:00"),
        ("2026-09-20T18:30", "2026-09-20T17:00"), ("2026-09-20T18:30", "2026-09-20T18:30"),
        ("2026-09-20T18:30", "2026-09-20"), ("2026-09-20", "2026-09-20T12:00"), ("2026-09-20", "2026-09-21T00:00"),
        ("2026-09-20T18:30", "2026-09-22T02:00"), ("2026-09-20T18:30Z", "2026-09-20T22:30Z"),
        ("2026-09-19T23:30Z", None), ("2026-03-29", "2026-03-29"), ("2026-10-25T01:00", "2026-10-25T04:00"),
        ("2026-03-29T02:30", None), ("20.09.2026 18:30", "21.09.2026"), ("Sept 20", "Sept 22"),
        ("garbage", "2026-09-22"), (None, "2026-09-22"), ("", ""), ("2026-09-20", "garbage"),
        ("2026-09-20T24:00", None), ("2026-09-20", "2026-09-20T24:00"), ("2026-09-20", "2026-09-20T18:30+99:00"),
        ("2026-09-20T23:59", "2026-09-20T23:59"), ("2026-09-20", 7), (7, None),
    ]  # fmt: skip
    out: list[dict[str, Any]] = []
    for start, end in pairs:
        e: dict[str, Any] = {"start": start}
        if end is not None:
            e["end"] = end
        out.append(e)
    return out


def _try(fn: Any) -> Any:
    try:
        return {"ok": fn()}
    except Exception as exc:
        return {"raises": type(exc).__name__}


def new_results(values: list[Any], pairs: list[dict[str, Any]], clock: str) -> dict[str, list[Any]]:
    today = date.fromisoformat(clock)

    def when(v: Any) -> list[Any]:
        d0, t, tz = parse_when(v, today=today)
        return [d0.isoformat() if d0 else None, t, tz]

    def span(e: dict[str, Any]) -> list[Any]:
        s, en = event_span(e, today=today)
        return [s.isoformat() if s else None, en.isoformat() if en else None]

    return {
        "parse_when": [_try(lambda v=v: when(v)) for v in values],
        "extract_date": [_try(lambda v=v: extract_date(v, today=today)) for v in values],
        "event_span": [_try(lambda e=e: span(e)) for e in pairs],
    }


def run_oracle(values: list[Any], pairs: list[dict[str, Any]], clocks: list[str]) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-events-oracle-") as tmp:
        tmpdir = Path(tmp)
        (tmpdir / "data").mkdir()
        src, dst = tmpdir / "in.json", tmpdir / "out.json"
        src.write_text(json.dumps({"clocks": clocks, "values": values, "spans": pairs}, ensure_ascii=False), "utf-8")
        env = {**os.environ, "PZ_DATA": str(tmpdir / "data"), "PYTHONPATH": str(OLD_REPO / "backend" / "src")}
        env.pop("SUPABASE_DB_URL", None)
        run = subprocess.run([str(python), str(ORACLE), str(src), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_text(encoding="utf-8"))
        return out


def differences(expected: dict[str, Any], values: list[Any], pairs: list[dict[str, Any]]) -> dict[str, list[str]]:
    """``{clock: ["parse_when[i]", ...]}`` for every result the new code gets differently."""
    out: dict[str, list[str]] = {}
    for clock, old in expected.items():
        new = new_results(values, pairs, clock)
        out[clock] = [
            f"{fn}[{i}]" for fn in ("parse_when", "extract_date", "event_span") for i, (a, b) in
            enumerate(zip(old[fn], new[fn], strict=True)) if a != b
        ]  # fmt: skip
    return out


def importer_differences(old_spans: list[Any], pairs: list[dict[str, Any]], clock: str) -> list[int]:
    """Positions where the importer's ``starts_at`` / ``ends_at`` (``span_of`` over ``stated``) differ from the old
    ``event_span``. Where the old code raised, the importer must still produce a span or none, never raise."""
    today = date.fromisoformat(clock)
    out: list[int] = []
    for i, (old, e) in enumerate(zip(old_spans, pairs, strict=True)):
        s, en = span_of(stated(e.get("start"), today=today), stated(e.get("end"), today=today))
        mine = [s.isoformat() if s else None, en.isoformat() if en else None]
        if "ok" in old and old["ok"] != mine:
            out.append(i)
    return out


def write_goldens() -> int:
    values, pairs = corpus(), spans()
    oracle = run_oracle(values, pairs, CLOCKS)
    GOLDEN.write_text(
        json.dumps(
            {"provenance": oracle["meta"], "values": values, "spans": pairs, "clocks": oracle["clocks"]},
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    bad = differences(oracle["clocks"], values, pairs)
    total = sum(len(v) for v in bad.values())
    print(f"events-when goldens: {len(values)} values, {len(pairs)} spans, clocks {CLOCKS}; differences {total}")
    return 1 if total else 0


def real() -> int:
    from projectzero.core.config import load_dotenv
    from projectzero.ops.legacy.convert import records
    from projectzero.ops.legacy.source import LegacySnapshot

    load_dotenv()
    snapshot = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    data = snapshot.json("events.json", {}) or {}
    evs, leads = records(data.get("events")), records(data.get("leads"))
    values = [e.get(k) for e in evs for k in ("start", "end")] + [lead.get("date") for lead in leads]
    pairs: list[dict[str, Any]] = [{k: e[k] for k in ("start", "end") if k in e} for e in evs]
    clock = datetime.now(BERLIN).date().isoformat()  # the import clock
    oracle = run_oracle(values, pairs, [clock])
    bad = differences(oracle["clocks"], values, pairs)[clock]
    columns = importer_differences(oracle["clocks"][clock]["event_span"], pairs, clock)
    print(
        json.dumps(
            {
                "clock": clock,
                "values": len(values),
                "spans": len(pairs),
                "differences": len(bad),
                "where": bad[:20],
                "importer_span_differences": len(columns),
                "importer_where": columns[:20],
                "oracle": oracle["meta"],
            }
        )
    )
    return 1 if bad or columns else 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["goldens"]:
        return write_goldens()
    if argv[1:] == ["real"]:
        return real()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
