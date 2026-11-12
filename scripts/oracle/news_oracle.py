"""ORACLE: the OLD News & Learning read side (review 028a), with a FIXED clock and NO write. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/news_oracle.py IN.json OUT.json

IN = {clock, cases_dir, routes: [route]} over a scratch PZ_DATA. ``cases_dir`` replaces the old ``SEED_CASES`` (the
curated case folder; a path that does not exist is the old missing folder). Each route is the old function the old
router called:

* ``view``           -> ``news.view()``                (``GET /api/news``);
* ``weekly``         -> ``news.weekly_review()``       (``GET /api/news_weekly``, ``record=False``);
* ``sources:<w>``    -> ``news_sources.view(<w>)``     (``GET /api/news_sources?window=<w>``);
* ``refresh_status`` -> ``news.refresh_status()``      (``GET /api/news_refresh_status``, no job in this process).

The old GET could SEED the curated cases (``seed_cases`` -> ``_save(d)``, and ``view`` immediately ``load()``-ed the
document again): the WHOLE events-document save is intercepted IN MEMORY (``install_news``): ``storage.save_json`` of
``news/events.json`` keeps the JSON text the old ``save_json`` would have written, and ``storage.load_json`` of it reads
that text back, so the old read sees its own seeding exactly as the file would have; nothing reaches the disk. Each
route starts from the FRESH fixture (the in-memory document is cleared before every route, so one GET never seeds
another route's baseline); ``saved`` is the document the route's seeding wrote (or ``null``). Every other write is
BLOCKED (``storage.append_line`` / ``save_json`` / ``write_text`` raise) and the data folder is checked unchanged
(``changed``). Decision (e): ``health.source_health`` (System health, not ported) answers no rows, so the old Swiss
ticker technical row takes its own ``UNKNOWN`` fallback. Each answer is ``{code: 200, body}`` or ``{raises: name}``.
The clock is frozen everywhere the old code read it (``date.today()`` / ``datetime.now()`` / ``ledger.now_ts()``).
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

EVENTS = "news/events.json"


class BlockedWrite(RuntimeError):
    pass


def _freeze(iso: str) -> None:
    from projectzero.domain import taste
    from projectzero.inference import ledger
    from projectzero.services import compressor, health, news, news_sources, pipeline, source_network, validation

    fixed = datetime.fromisoformat(iso)

    class FixedDate(date):
        @classmethod
        def today(cls) -> FixedDate:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> FixedDateTime:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day, fixed.hour, fixed.minute, fixed.second)

    for module in (validation, taste, compressor, news, news_sources, health, pipeline, source_network, ledger):
        if hasattr(module, "date"):
            module.date = FixedDate  # type: ignore[attr-defined]
        if hasattr(module, "datetime"):
            module.datetime = FixedDateTime  # type: ignore[attr-defined]
    ledger.now_ts = lambda: fixed.strftime(ledger.TS_FORMAT)  # type: ignore[attr-defined]


def _block() -> None:
    storage = importlib.import_module("projectzero.storage")

    def blocked(name: Any, *_a: Any, **_k: Any) -> None:
        raise BlockedWrite(f"write {name}")

    storage.append_line = blocked
    storage.save_json = blocked
    storage.write_text = blocked


def install_news(memory: dict[str, str], cases_dir: str | None) -> None:
    """The events-document save in MEMORY (read back by ``load_json``), on top of the installed write guard; the
    curated case folder redirected to ``cases_dir`` (``None``: the old folder is left as is)."""
    storage = importlib.import_module("projectzero.storage")
    from projectzero.services import news

    save_json, load_json = storage.save_json, storage.load_json

    def is_events(name: Any) -> bool:
        return str(name).replace("\\", "/") == EVENTS

    def save(name: Any, data: Any, *a: Any, indent: int | None = 1, **k: Any) -> None:
        if is_events(name):  # exactly the text the old ``save_json`` wrote
            memory[EVENTS] = json.dumps(data, ensure_ascii=False, indent=indent)
            return
        save_json(name, data, *a, indent=indent, **k)

    def load(name: Any, default: Any = None, *, tolerant: bool = False) -> Any:
        if is_events(name) and EVENTS in memory:
            return json.loads(memory[EVENTS])
        return load_json(name, copy.deepcopy(default), tolerant=tolerant)

    storage.save_json = save
    storage.load_json = load
    if cases_dir is not None:
        news.SEED_CASES = Path(cases_dir)  # type: ignore[attr-defined]


def no_health() -> None:
    """Decision (e): System health is not ported; the old Swiss technical row falls back to ``UNKNOWN``."""
    from projectzero.services import health

    health.source_health = lambda *_a, **_k: {"sources": []}  # type: ignore[attr-defined]


def _answer(fn: Any) -> dict[str, Any]:
    try:
        r = fn()
    except Exception as exc:  # the old route would have answered 500
        return {"raises": type(exc).__name__}
    return {"code": 200, "body": json.loads(json.dumps(r, ensure_ascii=False, default=str))}


def _hashes(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def meta(mode: str, clock: str) -> dict[str, Any]:
    from projectzero.domain import taste  # the OLD package

    old_root = Path(taste.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    return {"old_revision": revision, "old_dirty": bool(dirty), "clock": clock, "mode": mode}


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch folder"
    assert not os.environ.get("SUPABASE_DB_URL"), "the oracle never sees the database"
    os.environ.setdefault("PZ_TESTING", "1")
    os.environ["PZ_CASE_PREP"] = "0"
    inp = json.loads(src.read_text(encoding="utf-8"))
    before = _hashes(Path(data_dir))
    _freeze(inp["clock"])
    _block()
    memory: dict[str, str] = {}
    install_news(memory, inp["cases_dir"])
    no_health()
    from projectzero.services import news, news_sources  # the OLD package

    calls: dict[str, Any] = {"view": news.view, "weekly": news.weekly_review, "refresh_status": news.refresh_status}
    routes: dict[str, Any] = {}
    for route in inp["routes"]:
        memory.clear()  # a FRESH fixture per route: no GET seeds another route's baseline
        if route.startswith("sources:"):
            window = route.split(":", 1)[1]
            ans = _answer(lambda w=window: news_sources.view(w))
        else:
            ans = _answer(calls[route])
        routes[route] = {**ans, "saved": json.loads(memory[EVENTS]) if EVENTS in memory else None}
    after = _hashes(Path(data_dir))
    out = {
        "meta": meta("news", inp["clock"]),
        "routes": routes,
        "changed": sorted(k for k in {**before, **after} if before.get(k) != after.get(k)),
    }
    dst.write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
