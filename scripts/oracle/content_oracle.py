"""ORACLE: the OLD Public work routes (review 020), with a FIXED clock. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/content_oracle.py IN.json OUT.json

IN = {clock, steps: [{op: save|delete, body, at?}]} over a scratch PZ_DATA (a COPY; the routes write content.json).
``at`` moves the fixed clock for that step (ISO datetime). Per step: the HTTP code and body the old route returned
(a raised exception is recorded as {raises: name}), then the whole GET /api/content body.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

NOW: list[datetime] = []


def _freeze() -> None:
    from projectzero.api.routers import network

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> FixedDateTime:  # type: ignore[override]
            n = NOW[-1]
            return cls(n.year, n.month, n.day, n.hour, n.minute, n.second)

    network.datetime = FixedDateTime  # type: ignore[attr-defined]


def replay(inp: dict[str, Any]) -> dict[str, Any]:
    from projectzero import storage
    from projectzero.api.routers import network

    out = []
    for step in inp["steps"]:
        NOW.append(datetime.fromisoformat(step.get("at") or inp["clock"]))
        body = step["body"]
        try:
            with storage.state_lock:
                fn = network.content_save if step["op"] == "save" else network.content_delete
                res: dict[str, Any] = {"code": 200, "body": fn.__wrapped__(body) if hasattr(fn, "__wrapped__") else fn(body)}
        except Exception as exc:  # the old route would have answered 500
            res = {"raises": type(exc).__name__}
        res["view"] = network.content()
        out.append(res)
    return {"steps": out}


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch folder"
    os.environ.setdefault("PZ_TESTING", "1")
    inp = json.loads(src.read_text(encoding="utf-8"))
    NOW.append(datetime.fromisoformat(inp["clock"]))
    _freeze()
    from projectzero.domain import taste  # the OLD package

    old_root = Path(taste.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "clock": inp["clock"], "mode": "content"}
    dst.write_text(json.dumps({"meta": meta, **replay(inp)}, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
