"""ORACLE: the OLD Events read paths (review 015), with a FIXED clock. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/events_read_oracle.py reads IN.json OUT.json

IN = {clocks: [Berlin wall-clock iso], sets: [{name, files: {relpath: json}}] | null, wsig_days: [int],
      weekends: {clock: [[start, end]]}, suggest: [{field: value}]}
  -> per set and clock (each as {ok: value} or {raises: ExceptionType}):
       events   the old GET /api/events body (api/routers/events.list_events)
       health   GET /api/event_health
       wsig     {days: ecosys.where_should_i_go(days)} for each of wsig_days
       weekend  {"start|end": ecosys.sourcing_weekend(start, end)} for the clock's windows
     plus suggest: events.suggest(body) for each body (no clock).
  ``sets: null`` reads the data folder as it is (the real snapshot copy); otherwise each set's files are written first.

    <old python> scripts/oracle/events_read_oracle.py writes IN.json OUT.json

IN = {clock, steps: [{op: save | verify | lead | debrief | scout, body}]}
  -> per step: the HTTP code and body the old route returned (event_save / event_verify / event_lead / event_debrief
     / scout_event), then the stored events.json events + leads, the Scout 00 event reports and the people.

The clock is frozen everywhere the old code read it: ``events.berlin_today`` (``datetime.now(BERLIN)``) and the
machine's ``date.today()`` in ``events``, ``ecosys`` and ``people``. PZ_DATA must be a scratch folder.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any


def _clock(iso: str) -> tuple[type[date], type[datetime]]:
    fixed = datetime.fromisoformat(iso)

    class FixedDate(date):
        @classmethod
        def today(cls) -> FixedDate:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> FixedDateTime:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day, fixed.hour, fixed.minute, fixed.second)

    return FixedDate, FixedDateTime


def _freeze(iso: str) -> None:
    from projectzero.api.routers import events as events_router
    from projectzero.domain import ecosys, events, people, scout_intake

    fd, fdt = _clock(iso)
    for module in (events, ecosys, people):
        module.date = fd  # type: ignore[attr-defined]
    for module in (events, events_router, scout_intake):
        module.datetime = fdt  # type: ignore[attr-defined]


def _try(fn: Any) -> Any:
    try:
        return {"ok": fn()}
    except Exception as exc:  # the goldens record WHICH cases raise, not only what the others return
        return {"raises": type(exc).__name__}


def _write(files: dict[str, Any]) -> None:
    root = Path(os.environ["PZ_DATA"])
    for existing in ("events.json", "event_sources.json", "event_health.json", "scout_intake.json", "people.json"):
        (root / existing).unlink(missing_ok=True)
    for rel, doc in files.items():
        (root / rel).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def reads(inp: dict[str, Any]) -> dict[str, Any]:
    from projectzero.api.routers import events as events_router
    from projectzero.domain import ecosys, events

    out: dict[str, Any] = {"sets": {}}
    sets = inp.get("sets")
    for s in sets if sets is not None else [{"name": "data", "files": None}]:
        if s["files"] is not None:
            _write(s["files"])
        per: dict[str, Any] = {}
        for clock in inp["clocks"]:
            _freeze(clock)
            windows = inp.get("weekends", {}).get(clock, [])
            per[clock] = {
                "events": _try(events_router.list_events),
                "health": _try(events_router.event_health),
                "wsig": {str(d): _try(lambda d=d: ecosys.where_should_i_go(d)) for d in inp.get("wsig_days", [])},
                "weekend": {f"{a}|{b}": _try(lambda a=a, b=b: ecosys.sourcing_weekend(a, b)) for a, b in windows},
            }
        out["sets"][s["name"]] = per
    out["suggest"] = [_try(lambda b=b: events.suggest(b)) for b in inp.get("suggest", [])]
    return out


def writes(inp: dict[str, Any]) -> dict[str, Any]:
    import copy

    from projectzero.api.errors import ApiError
    from projectzero.api.routers import events as events_router
    from projectzero.api.routers import scout as scout_router
    from projectzero.domain import events, people, scout_intake

    _freeze(inp["clock"])
    routes = {
        "save": events_router.event_save,
        "verify": events_router.event_verify,
        "lead": events_router.event_lead,
        "debrief": events_router.event_debrief,
        "scout": scout_router.scout_event,
    }
    out = []
    for step in inp["steps"]:
        body = copy.deepcopy(step["body"])
        try:
            code, payload = 200, routes[step["op"]](body)
        except ApiError as exc:
            code, payload = exc.status_code, {"ok": False, "error": exc.message, **exc.payload}
        except Exception as exc:
            code, payload = 500, {"ok": False, "error": f"internal error ({type(exc).__name__})"}
        d = events.load()
        out.append({
            "code": code,
            "body": payload,
            "events": d.get("events", []),
            "leads": d.get("leads", []),
            "scout_events": scout_intake.load().get("events", []),
            "people": people.load().get("people", []),
        })
    return {"steps": out}


def main() -> int:
    mode, src, dst = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch folder"
    os.environ.setdefault("PZ_TESTING", "1")
    inp = json.loads(src.read_text(encoding="utf-8"))
    from projectzero.domain import events  # the OLD package

    old_root = Path(events.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    result = {"reads": reads, "writes": writes}[mode](inp)
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "mode": mode}
    dst.write_text(json.dumps({"meta": meta, **result}, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
