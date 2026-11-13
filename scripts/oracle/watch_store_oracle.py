"""ORACLE: the OLD WATCH store (review 037a): ``watch.view()``, ``set_target`` and ``acknowledge``, with a FIXED clock.
Never imported by the new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/watch_store_oracle.py IN.json OUT.json

IN = {extra_watch: [old-format candidate records], steps: [{clock, op: "view" | "target" | "ack", body}]}.
``PZ_DATA`` is a scratch folder holding the world's files (``inbox.json``, ``triage_proposals.json``,
``watch/targets.json``, ``watch/triggers.jsonl``, ...).

Per step, at the step's clock: the old ``watch.set_target(body)`` or ``acknowledge(body)`` (a ``WatchError`` is
recorded as ``{error}``; ``view``: no write), then the record of: the answer, the whole ``watch/triggers.jsonl`` text,
the ``watch/targets.json`` document, the old ``_events()`` and ``triggers()``, the old ``view()``, and (declared a)
``view_a``: the old ``view()`` with the old watched set extended by ``extra_watch`` (the candidates the merged Deal
Flow holds on WATCH that the old inbox did not: Scout planner leads), appended after the inbox's records, so the
expected new view comes from the old code too.

The clock: ``datetime.now()`` / ``date.today()`` of every loaded ``projectzero`` module. Writes: ``storage.save_json``
/ ``write_text`` / ``append_line`` outside the scratch data folder are refused and recorded as ``blocked``. Refused: a
``PZ_DATA`` inside ``project-zero-data``, and any ``SUPABASE_DB_URL``.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

NOW: list[datetime] = []
BLOCKED: list[str] = []


class FixedDate(date):
    @classmethod
    def today(cls) -> FixedDate:  # type: ignore[override]
        n = NOW[-1]
        return cls(n.year, n.month, n.day)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> FixedDateTime:  # type: ignore[override]
        n = NOW[-1]
        return cls(n.year, n.month, n.day, n.hour, n.minute, n.second)


def _freeze() -> list[str]:
    frozen = []
    for name, module in sorted(sys.modules.items()):
        if not name.startswith("projectzero") or module is None:
            continue
        if getattr(module, "date", None) is date:
            module.date = FixedDate  # type: ignore[attr-defined]
            frozen.append(f"{name}.date")
        if getattr(module, "datetime", None) is datetime:
            module.datetime = FixedDateTime  # type: ignore[attr-defined]
            frozen.append(f"{name}.datetime")
    return frozen


def _block(root: Path) -> None:
    from projectzero import storage

    def inside(name: str, fn: Any) -> Any:
        def guarded(target: Any, *a: Any, **k: Any) -> Any:
            p = Path(str(target))
            full = (p if p.is_absolute() else storage.data_dir() / p).resolve()
            if root not in full.parents:
                BLOCKED.append(f"{name}:{full}")
                raise RuntimeError(f"the watch oracle blocks {name} outside the scratch folder: {full}")
            return fn(target, *a, **k)

        return guarded

    storage.save_json = inside("save_json", storage.save_json)  # type: ignore[assignment]
    storage.write_text = inside("write_text", storage.write_text)  # type: ignore[assignment]
    storage.append_line = inside("append_line", storage.append_line)  # type: ignore[assignment]


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and "project-zero-data" not in Path(data_dir).resolve().parts, "PZ_DATA must be a scratch folder"
    assert not os.environ.get("SUPABASE_DB_URL"), "the oracle never sees the database"
    os.environ.setdefault("PZ_TESTING", "1")
    root = Path(data_dir).resolve()
    inp = json.loads(src.read_bytes().decode("utf-8"))
    extra: list[dict[str, Any]] = inp.get("extra_watch") or []
    NOW.append(datetime.fromisoformat(inp["steps"][0]["clock"]))
    from projectzero.services import watch

    from projectzero import storage

    storage.configure(root)
    frozen = _freeze()
    _block(root)
    original_load = storage.load_json

    def view_a() -> dict[str, Any]:
        def load(name: Any, default: Any = None, **kw: Any) -> Any:
            d = original_load(name, default, **kw)
            if str(name) == "inbox.json" and isinstance(d, dict):
                d = {**d, "candidates": [*(d.get("candidates") or []), *copy.deepcopy(extra)]}
            return d

        storage.load_json = load  # type: ignore[assignment]
        try:
            return watch.view()
        finally:
            storage.load_json = original_load  # type: ignore[assignment]

    steps = []
    for step in inp["steps"]:
        NOW.append(datetime.fromisoformat(step["clock"]))
        fn = {"target": watch.set_target, "ack": watch.acknowledge}.get(step["op"])
        try:
            answer: dict[str, Any] = {"answer": None if fn is None else fn(copy.deepcopy(step["body"]))}
        except watch.WatchError as e:
            answer = {"error": str(e)}
        steps.append({
            "clock": step["clock"],
            **json.loads(json.dumps(answer, ensure_ascii=False)),
            "log": storage.read_text(watch.TRIGGERS),
            "targets": storage.load_json(watch.TARGETS, None, tolerant=True),
            "events": watch._events(),
            "triggers": watch.triggers(),
            "view": watch.view(),
            "view_a": view_a(),
        })  # fmt: skip
    old_root = Path(watch.__file__).resolve().parents[4]
    revision = subprocess.run(["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()  # fmt: skip
    dirty = subprocess.run(["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
                           capture_output=True, text=True, check=True).stdout.strip()  # fmt: skip
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "mode": "watch_store", "frozen": frozen}
    out = {"meta": meta, "steps": steps, "blocked": list(BLOCKED)}
    dst.write_bytes(json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
