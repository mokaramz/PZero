"""ORACLE: the OLD Ecosystems reads and the adopt write (review 022), with a FIXED clock. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/ecosystems_oracle.py IN.json OUT.json

IN = {clock, extra_cities: [name], steps: [{id, confirm}]} over a scratch PZ_DATA (a COPY: the old reads write the
Founder Radar bootstrap documents when they are missing, and adopt writes three files).
OUT = {registry: ecosys.city_registry(), eco: {city: ecosys.city_page(city)} for every curated and detected city of
the registry plus ``extra_cities``, coverage: coverage.report(), sources: connectors.load_registry(), steps: [{body:
the adopt answer (as the old route called it), coverage, sources: the same after it}]}. Each value is {ok: value} or
{raises: ExceptionType}.

The clock is frozen everywhere the old code read it: ``date.today()`` / ``datetime.now()`` in ``coverage``,
``ecosys``, ``events`` (incl. ``berlin_today``) and ``people``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any


def _freeze(iso: str) -> None:
    from projectzero.domain import coverage, ecosys, events, people

    fixed = datetime.fromisoformat(iso)

    class FixedDate(date):
        @classmethod
        def today(cls) -> FixedDate:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> FixedDateTime:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day, fixed.hour, fixed.minute, fixed.second)

    for module in (coverage, ecosys, events, people):
        module.date = FixedDate  # type: ignore[attr-defined]
    for module in (coverage, events):
        module.datetime = FixedDateTime  # type: ignore[attr-defined]


def _try(fn: Any) -> Any:
    try:
        return {"ok": json.loads(json.dumps(fn(), ensure_ascii=False, default=str))}
    except Exception as exc:  # the goldens record WHICH cases raise, not only what the others return
        return {"raises": type(exc).__name__}


def _views() -> dict[str, Any]:
    from projectzero import storage
    from projectzero.domain import connectors, coverage

    with storage.state_lock:
        return {"coverage": _try(coverage.report), "sources": _try(connectors.load_registry)}


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch folder"
    os.environ.setdefault("PZ_TESTING", "1")
    inp = json.loads(src.read_text(encoding="utf-8"))
    _freeze(inp["clock"])
    from projectzero import storage
    from projectzero.domain import coverage, ecosys, taste  # the OLD package

    registry = _try(ecosys.city_registry)
    names = [c["name"] for c in (registry.get("ok") or {}).get("cities", [])] + list(inp.get("extra_cities", []))
    out: dict[str, Any] = {
        "registry": registry,
        "eco": {name: _try(lambda name=name: ecosys.city_page(name)) for name in names},
        **_views(),
        "steps": [],
    }
    for body in inp.get("steps", []):
        with storage.state_lock:  # the old route: @locked, coverage.adopt_candidate(body.get("id"), bool(confirm))
            answer = _try(lambda body=body: coverage.adopt_candidate(body.get("id"), bool(body.get("confirm"))))
        out["steps"].append({"body": answer, **_views()})
    old_root = Path(taste.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "clock": inp["clock"], "mode": "ecosystems"}
    dst.write_text(json.dumps({"meta": meta, **out}, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
