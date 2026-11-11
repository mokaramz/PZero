"""ORACLE: the OLD event date rules (review 014), with a FIXED clock. Never imported by the new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/events_when_oracle.py IN.json OUT.json

IN.json = {"clocks": [iso date], "values": [any JSON value], "spans": [{"start": ..., "end": ...}]}
OUT.json = {"meta": {...}, "clocks": {clock: {"parse_when": [...], "extract_date": [...], "event_span": [...]}}}
Each result is {"ok": value} or {"raises": ExceptionType}: ``parse_when`` -> [date iso | null, time, tz note],
``extract_date`` -> the ISO string, ``event_span`` -> [start iso | null, end iso | null].
PZ_DATA must point at an empty scratch folder: the old modules read settings on import and must never see real data.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any


def _fixed(iso: str) -> type[date]:
    fixed = date.fromisoformat(iso)

    class FixedDate(date):
        @classmethod
        def today(cls) -> FixedDate:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day)

    return FixedDate


def _try(fn: Any) -> Any:
    try:
        return {"ok": fn()}
    except Exception as exc:  # the goldens record WHICH inputs raise, not only what the others return
        return {"raises": type(exc).__name__}


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and "project-zero-data" not in data_dir, "PZ_DATA must be a scratch folder"
    os.environ.setdefault("PZ_TESTING", "1")

    from projectzero.domain import events  # the OLD package (sys.path set by the caller)

    old_root = Path(events.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    inp = json.loads(src.read_text(encoding="utf-8"))

    def when(v: Any) -> list[Any]:
        d0, t, tz = events.parse_when(v)
        return [d0.isoformat() if d0 else None, t, tz]

    def span(e: dict[str, Any]) -> list[Any]:
        s, en = events.event_span(e)
        return [s.isoformat() if s else None, en.isoformat() if en else None]

    out: dict[str, Any] = {
        "meta": {"old_revision": revision, "old_dirty": bool(dirty), "berlin": repr(events.BERLIN)},
        "clocks": {},
    }
    for clock in inp["clocks"]:
        events.date = _fixed(clock)  # type: ignore[attr-defined]  # extract_date's date.today()
        out["clocks"][clock] = {
            "parse_when": [_try(lambda v=v: when(v)) for v in inp["values"]],
            "extract_date": [_try(lambda v=v: events.extract_date(v)) for v in inp["values"]],
            "event_span": [_try(lambda e=e: span(e)) for e in inp["spans"]],
        }
    dst.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
