"""ORACLE: the OLD Sources page reads and the toggle (review 021), with a FIXED clock. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/sources_oracle.py IN.json OUT.json

IN = {clock, steps: [{id, enabled?}]} over a scratch PZ_DATA (a COPY: the reads persist repairs, the toggle writes).
OUT = {view: the old GET /api/sources + {report, manual_sources, pages, feeds} as the page read them from
GET /api/inbox, steps: [{body: the toggle's answer, view: the same after it}]}. A raised exception is {raises: name}.
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
    from projectzero.domain import connectors
    from projectzero.services import discovery

    fixed = datetime.fromisoformat(iso)

    class FixedDate(date):
        @classmethod
        def today(cls) -> FixedDate:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> FixedDateTime:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day, fixed.hour, fixed.minute, fixed.second)

    connectors.date = FixedDate  # type: ignore[attr-defined]
    connectors.datetime = FixedDateTime  # type: ignore[attr-defined]
    discovery.datetime = FixedDateTime  # type: ignore[attr-defined]


def _view() -> Any:
    from projectzero import storage
    from projectzero.domain import connectors
    from projectzero.services import discovery

    try:
        with storage.state_lock:
            v = discovery.sources_view()
            ib = discovery.load_inbox({"candidates": [], "last_run": None, "report": []})
        return {**v, "report": ib.get("report", []), "manual_sources": connectors.MANUAL_SOURCES,
                "pages": connectors.PRE_COMPANY_PAGES, "feeds": connectors.FEEDS}  # fmt: skip
    except Exception as exc:
        return {"raises": type(exc).__name__}


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch folder"
    os.environ.setdefault("PZ_TESTING", "1")
    inp = json.loads(src.read_text(encoding="utf-8"))
    _freeze(inp["clock"])
    from projectzero import storage
    from projectzero.domain import taste  # the OLD package
    from projectzero.services import discovery

    out: dict[str, Any] = {"view": _view(), "steps": []}
    for body in inp.get("steps", []):
        with storage.state_lock:
            discovery.source_toggle(body.get("id"), body.get("enabled"))
        out["steps"].append({"body": {"ok": True}, "view": _view()})
    old_root = Path(taste.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "clock": inp["clock"], "mode": "sources"}
    dst.write_text(json.dumps({"meta": meta, **out}, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
