"""ORACLE: the OLD Validation read side (review 027a), with a FIXED clock and NO write. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/validation_oracle.py IN.json OUT.json

IN = {clock, extra_cycles: [cycle]} over a scratch PZ_DATA. Through the old ``services/validation.py`` functions:

* ``view``: ``view(today)`` (the ``GET /api/validation`` body), FIRST;
* ``appended``: the lines the old ``_snapshot`` appended during that view. The append goes to an IN-MEMORY log that
  the old view's own subsequent read sees (``storage.read_text`` of the snapshot log returns the file plus the
  in-memory lines, exactly as the file would have grown); its ``at`` is the frozen clock (``ledger.now_ts``);
* ``packets``: ``scout_packet(cycle)`` (the ``GET /api/validation_scout_packet`` body) for ``""``, every cycle of the
  view's ``scout.cycles``, then ``extra_cycles``;
* ``build``: ``build(today)`` as ``{entities, issues}`` (the entity model News and the write side reuse);
* ``changed``: the data-folder files whose bytes changed (must be empty).

Every other write is BLOCKED (``storage.append_line`` / ``save_json`` / ``write_text`` raise). The deferred views are
made unavailable so the old code takes its own fallback (declared differences b-d, normalised by the parity):
``news.view`` and ``news.learnings`` (the News panel, the packet's NEWS LEARNING), ``native_planner.bridge_metrics``
(the native-bridge panel), ``source_network.scout_lines`` / ``news_sources.scout_lines`` (the packet's SOURCE NETWORK
and NEWS SOURCE LEARNING) and ``source_network._already_monitored`` (the cards' source learning). ``news.observations``
is NOT stubbed: it is ported. Each answer is ``{code: 200, body}`` or ``{raises: name}``. The clock is frozen
everywhere the old code read it (``date.today()`` / ``datetime.now()`` / ``ledger.now_ts()``).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

SNAPSHOTS = "validation/snapshots.jsonl"


class BlockedWrite(RuntimeError):
    pass


class Deferred(RuntimeError):
    pass


def _freeze(iso: str) -> None:
    from projectzero.domain import taste
    from projectzero.inference import ledger
    from projectzero.services import compressor, news, pipeline, source_network, validation

    fixed = datetime.fromisoformat(iso)

    class FixedDate(date):
        @classmethod
        def today(cls) -> FixedDate:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> FixedDateTime:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day, fixed.hour, fixed.minute, fixed.second)

    for module in (validation, taste, compressor, news, pipeline, source_network, ledger):
        if hasattr(module, "date"):
            module.date = FixedDate  # type: ignore[attr-defined]
        if hasattr(module, "datetime"):
            module.datetime = FixedDateTime  # type: ignore[attr-defined]
    ledger.now_ts = lambda: fixed.strftime(ledger.TS_FORMAT)  # type: ignore[attr-defined]


def _guard(memory: list[str]) -> None:
    """The snapshot append goes to ``memory`` (read back by the snapshot log's ``read_text``); every other write
    raises."""
    storage = importlib.import_module("projectzero.storage")
    read_text = storage.read_text

    def append_line(name: Any, line: str) -> None:
        if str(name).replace("\\", "/") == SNAPSHOTS:
            memory.append(line.replace("\n", " ") + "\n")  # exactly what the file would have received
            return
        raise BlockedWrite(f"append_line {name}")

    def read(name: Any, default: str = "") -> str:
        text = read_text(name, default)
        if str(name).replace("\\", "/") == SNAPSHOTS:
            return text + "".join(memory)
        return text

    def blocked(name: Any, *_a: Any, **_k: Any) -> None:
        raise BlockedWrite(f"write {name}")

    storage.append_line = append_line
    storage.read_text = read
    storage.save_json = blocked
    storage.write_text = blocked


def _defer() -> None:
    from projectzero.services import native_planner, news, news_sources, source_network

    def unavailable(*_a: Any, **_k: Any) -> Any:
        raise Deferred("deferred view")

    news.view = unavailable  # type: ignore[attr-defined]
    news.learnings = unavailable  # type: ignore[attr-defined]
    native_planner.bridge_metrics = unavailable  # type: ignore[attr-defined]
    source_network.scout_lines = unavailable  # type: ignore[attr-defined]
    source_network._already_monitored = unavailable  # type: ignore[attr-defined]
    news_sources.scout_lines = unavailable  # type: ignore[attr-defined]


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
    memory: list[str] = []
    _guard(memory)
    _defer()
    from projectzero.domain import taste  # the OLD package
    from projectzero.services import validation

    today = datetime.fromisoformat(inp["clock"]).date()
    out: dict[str, Any] = {"view": _answer(lambda: validation.view(today))}
    out["appended"] = list(memory)
    cycles = ["", *((out["view"].get("body") or {}).get("scout") or {}).get("cycles", []), *inp["extra_cycles"]]
    out["packets"] = {c: _answer(lambda c=c: validation.scout_packet(c)) for c in dict.fromkeys(cycles)}

    def build() -> dict[str, Any]:
        ents, issues = validation.build(today)
        return {"entities": ents, "issues": issues}

    out["build"] = _answer(build)
    after = _hashes(Path(data_dir))
    out["changed"] = sorted(k for k in {**before, **after} if before.get(k) != after.get(k))
    old_root = Path(taste.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "clock": inp["clock"], "mode": "validation"}
    dst.write_text(json.dumps({"meta": meta, **out}, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
