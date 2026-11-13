"""ORACLE: the OLD Today view (review 030a), ``services/today.view(date)``, over invented worlds with a FIXED clock and
every write blocked. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/today_oracle.py IN.json OUT.json

IN = {worlds: [{name, clock}]}; the data folder of world ``name`` is ``PZ_DATA/<name>`` (written by the parity
script). Per world, in order: ``storage`` is pointed at its folder, the clock is frozen at ``clock`` (naive Berlin
wall time) everywhere the old view read it (``date.today()`` / ``datetime.now()`` in ``taste``, ``imq``, ``people``,
``events`` (incl. ``berlin_today``), ``founder_calls``, ``case_prep``, ``pipeline``, ``compressor``), and
``today.view(<clock's date>)`` is called, then once more with ``MAX_ACTIONS`` lifted (``uncut``: every ranked action,
so the branches below the cut of 7 are compared too). The IMQ save and the blocked writes are recorded over both.

Stubbed, as the new side decides (review 030a):

* (c) the retired Scout sections: ``_native_actions`` / ``_scout00_actions`` answer ``[]`` (their ``considered`` keys
  are 0; the parity drops them, declared);
* (d) ``scheduler.failing_jobs`` raises (the old fallback: the ``jobs`` row is omitted) and ``source_network.load``
  answers no candidate (the old fallback: ``src = 0``);
* (e) ``_ready_proposals`` answers ``[]`` (no Claim Index: always the "Verify" variant).

Writes: the pipeline's IMQ save (``pipeline.save_signals_doc``) is captured IN MEMORY and read back by the old
``load_signals_doc`` (the old reads that follow saw it), recorded as ``saved``; every other write
(``storage.save_json`` / ``write_text`` / ``append_line``) raises and is recorded as ``blocked``; the folder is
checked unchanged (``changed``). Case preparation is switched off (``PZ_CASE_PREP=0``): no case is ever queued.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

NOW: list[datetime] = []


def _freeze() -> None:
    from projectzero.domain import events, founder_calls, imq, people, taste
    from projectzero.services import case_prep, compressor, pipeline

    class FixedDate(date):
        @classmethod
        def today(cls) -> FixedDate:  # type: ignore[override]
            n = NOW[-1]
            return cls(n.year, n.month, n.day)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> FixedDateTime:  # type: ignore[override]
            n = NOW[-1]  # naive Berlin wall time, whatever zone is asked (events.berlin_today asks for Berlin)
            return cls(n.year, n.month, n.day, n.hour, n.minute, n.second)

    for module in (taste, imq, people, events, founder_calls, case_prep, compressor):
        module.date = FixedDate  # type: ignore[attr-defined]
    for module in (imq, events, founder_calls, case_prep, pipeline, compressor):
        module.datetime = FixedDateTime  # type: ignore[attr-defined]


SAVED: dict[str, Any] = {}
BLOCKED: list[str] = []


def _stub() -> None:
    from projectzero.services import pipeline, scheduler, source_network, today

    from projectzero import storage

    today._native_actions = lambda: []  # type: ignore[attr-defined]  # decision (c)
    today._scout00_actions = lambda: []  # type: ignore[attr-defined]  # decision (c)
    today._ready_proposals = lambda entry: []  # type: ignore[attr-defined]  # decision (e)

    def failing_jobs() -> Any:  # decision (d): the old fallback when the scheduler state was unavailable
        raise RuntimeError("no scheduler in the new system")

    scheduler.failing_jobs = failing_jobs  # type: ignore[attr-defined]
    source_network.load = lambda: {"candidates": []}  # type: ignore[attr-defined]  # decision (d): src = 0
    real_load = pipeline.load_signals_doc

    def load_signals_doc() -> Any:
        return copy.deepcopy(SAVED["doc"]) if "doc" in SAVED else real_load()

    def save_signals_doc(d: Any) -> None:  # the IMQ save, in memory (as the old code would have written it)
        stripped = {**{k: v for k, v in d.items() if k not in ("week", "signals")}, "week": d.get("week", ""),
                    "signals": [{k: v for k, v in e.items() if k not in pipeline.COMPUTED_FIELDS}
                                if isinstance(e, dict) else e for e in d.get("signals", [])]}  # fmt: skip
        SAVED["doc"] = json.loads(json.dumps(stripped, ensure_ascii=False))
        SAVED.setdefault("count", 0)
        SAVED["count"] += 1

    pipeline.load_signals_doc = load_signals_doc  # type: ignore[assignment]
    pipeline.save_signals_doc = save_signals_doc  # type: ignore[assignment]

    def blocked(name: str) -> Any:
        def refuse(target: Any, *a: Any, **k: Any) -> None:
            BLOCKED.append(f"{name}:{Path(str(target)).name}")
            raise RuntimeError(f"the Today oracle blocks {name}")

        return refuse

    storage.save_json = blocked("save_json")  # type: ignore[assignment]
    storage.write_text = blocked("write_text")  # type: ignore[assignment]
    storage.append_line = blocked("append_line")  # type: ignore[assignment]


def _digest(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}  # fmt: skip


UNCUT = 10**6


def _view(today: Any) -> dict[str, Any]:
    try:
        return {"ok": today.view(NOW[-1].date())}
    except Exception as exc:  # the old route would have answered 500
        return {"raises": type(exc).__name__}


def run_world(world: dict[str, Any], root: Path) -> dict[str, Any]:
    from projectzero.services import case_prep, today

    from projectzero import compat, storage

    folder = root / world["name"]
    storage.configure(folder)
    NOW.append(datetime.fromisoformat(world["clock"]))
    SAVED.clear()
    BLOCKED.clear()
    compat.SKIPPED.clear()
    case_prep._queue.clear()
    before = _digest(folder)
    out = _view(today)
    shown = today.MAX_ACTIONS
    today.MAX_ACTIONS = UNCUT  # the same view with every ranked action shown (the cut is compared by ``out``)
    try:
        uncut = _view(today)
    finally:
        today.MAX_ACTIONS = shown
    after = _digest(folder)
    changed = sorted(k for k in {**before, **after} if before.get(k) != after.get(k))
    return {"name": world["name"], **out, "uncut": uncut, "saved": SAVED.get("doc"), "saves": SAVED.get("count", 0),
            "blocked": list(BLOCKED), "changed": changed, "skipped": compat.skipped()}  # fmt: skip


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch folder"
    assert not os.environ.get("SUPABASE_DB_URL"), "the oracle never sees the database"
    os.environ.setdefault("PZ_TESTING", "1")
    os.environ["PZ_CASE_PREP"] = "0"
    inp = json.loads(src.read_bytes().decode("utf-8"))
    NOW.append(datetime.fromisoformat(inp["worlds"][0]["clock"]))
    _freeze()
    _stub()
    from projectzero.domain import taste  # the OLD package

    old_root = Path(taste.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    worlds = [run_world(w, Path(data_dir)) for w in inp["worlds"]]
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "mode": "today"}
    dst.write_bytes(json.dumps({"meta": meta, "worlds": worlds}, ensure_ascii=False, default=str).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
