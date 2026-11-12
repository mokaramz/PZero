"""ORACLE: the OLD Map routes (review 025), with a FIXED clock. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/map_oracle.py IN.json OUT.json

IN = {clock, inject?: {declared_sources, coverage_all}, extra_cities: [name], queries: [q], plan_date, plans: [body]}
over a scratch PZ_DATA (a COPY: the old ``GET /api/map`` rewrites ``real_data.json``, and the old Deal Flow / Founder
Radar reads write their bootstrap documents when missing). Through the old route functions of ``api/routers/home.py``:

* ``intel``: ``GET /api/geo_intel``;
* ``ecosystem``: ``GET /api/geo_ecosystem?city=`` for every city of the intel answer, then ``extra_cities``;
* ``search``: ``GET /api/geo_search?q=`` for every query;
* ``sourcing_day``: ``POST /api/sourcing_day`` with ``{city, date: plan_date}`` for every city of the intel answer,
  then each body of ``plans`` (the refusals and extra days), as ``[{body, answer}]``;
* ``map``: ``GET /api/map`` LAST (it writes), with ``map_wrote`` (whether ``real_data.json`` changed) and
  ``new_signals``: the old ``ecosys.home()`` count (its two lines, ``domain/ecosys.py`` :683-684, over the same inbox).

Each answer is {code, body} (an ``ApiError`` as the old error contract: {code, body: {ok: false, error}}) or
{raises: name}. ``inject`` replaces ``coverage.declared_sources`` and ``health.coverage_summary`` (as the old
``tests/test_geo_intel.py`` did). The clock is frozen everywhere the old code read it: ``date.today()`` /
``datetime.now()`` in ``geo_intel``, ``coverage``, ``ecosys``, ``events`` (incl. ``berlin_today``), ``people``,
``taste`` and ``scout_intake``; ``geo_intel.time`` is a stub whose ``time()`` is constant (``build_s`` = 0.0) and whose
``strftime(fmt)`` formats the fixed clock (``built_at`` = the clock, ``%Y-%m-%dT%H:%M:%S``).
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any


def _freeze(iso: str) -> None:
    from projectzero.domain import coverage, ecosys, events, people, taste
    from projectzero.domain import scout_intake as si
    from projectzero.services import geo_intel as gi

    fixed = datetime.fromisoformat(iso)

    class FixedDate(date):
        @classmethod
        def today(cls) -> FixedDate:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> FixedDateTime:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day, fixed.hour, fixed.minute, fixed.second)

    class FixedTime:
        @staticmethod
        def time() -> float:
            return 1_000_000.0

        @staticmethod
        def strftime(fmt: str) -> str:
            return fixed.strftime(fmt)

    for module in (gi, coverage, ecosys, events, people, taste, si):
        if hasattr(module, "date"):
            module.date = FixedDate  # type: ignore[attr-defined]
        if hasattr(module, "datetime"):
            module.datetime = FixedDateTime  # type: ignore[attr-defined]
    gi.time = FixedTime  # type: ignore[attr-defined]


def _answer(fn: Any) -> dict[str, Any]:
    from projectzero.api.errors import ApiError

    try:
        r = fn()
    except ApiError as exc:
        return {"code": exc.status_code, "body": {"ok": False, "error": exc.message, **exc.payload}}
    except Exception as exc:  # the old route would have answered 500
        return {"raises": type(exc).__name__}
    return {"code": 200, "body": json.loads(json.dumps(r, ensure_ascii=False, default=str))}


def _inject(spec: dict[str, Any]) -> None:
    from projectzero.domain import coverage
    from projectzero.services import health

    declared, cov = spec["declared_sources"], spec["coverage_all"]
    coverage.declared_sources = lambda: json.loads(json.dumps(declared))  # type: ignore[attr-defined]
    health.coverage_summary = lambda: {"available": True, "all": json.loads(json.dumps(cov))}  # type: ignore[attr-defined]


def _new_signals() -> int:
    from projectzero import compat, storage

    ib = storage.load_json("inbox.json", {"candidates": []})
    new_sig = [c for c in compat.records(ib.get("candidates"), "Deal Flow", ("id",)) if c.get("decision") == "new"]
    return len(new_sig)


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch folder"
    assert not os.environ.get("SUPABASE_DB_URL"), "the oracle never sees the database"
    os.environ.setdefault("PZ_TESTING", "1")
    os.environ["PZ_CASE_PREP"] = "0"
    inp = json.loads(src.read_text(encoding="utf-8"))
    _freeze(inp["clock"])
    if inp.get("inject"):
        _inject(inp["inject"])
    from projectzero.domain import taste  # the OLD package

    storage = importlib.import_module("projectzero.storage")
    r = importlib.import_module("projectzero.api.routers.home")

    intel = _answer(r.geo_intel)
    cities = [e["city"] for e in (intel.get("body") or {}).get("ecosystems", [])]
    out: dict[str, Any] = {
        "intel": intel,
        "ecosystem": {c: _answer(lambda c=c: r.geo_ecosystem(c)) for c in [*cities, *inp.get("extra_cities", [])]},
        "search": {q: _answer(lambda q=q: r.geo_search(q)) for q in inp.get("queries", [])},
        "sourcing_day": [],
    }
    bodies = [{"city": c, "date": inp["plan_date"]} for c in cities] + list(inp.get("plans", []))
    for body in bodies:
        out["sourcing_day"].append({"body": body, "answer": _answer(lambda body=body: r.sourcing_day(body))})
    out["new_signals"] = _new_signals()
    rd = Path(storage.path("real_data.json"))
    before = rd.read_bytes() if rd.exists() else None
    out["map"] = _answer(r.map_view)
    out["map_wrote"] = (rd.read_bytes() if rd.exists() else None) != before
    old_root = Path(taste.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "clock": inp["clock"], "mode": "map"}
    dst.write_text(json.dumps({"meta": meta, **out}, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
