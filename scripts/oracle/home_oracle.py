"""ORACLE: the OLD Investment Desk (review 031a), ``domain/ecosys.home()``, over invented worlds with a FIXED clock and
every write blocked. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/home_oracle.py IN.json OUT.json

IN = {worlds: [{name, clock}]}; the data folder of world ``name`` is ``PZ_DATA/<name>`` (written by the parity
script). Per world, in order: ``storage`` is pointed at its folder, the clock is frozen at ``clock`` (naive Berlin
wall time) everywhere the old desk read it: every loaded old ``projectzero`` module whose ``date`` / ``datetime`` is
the standard class gets a frozen subclass (``ecosys``, ``people``, ``events`` incl. ``berlin_today``, ``taste``,
``case_prep``, ``founder_calls``, ...), then ``ecosys.home()`` is called once.

Writes: ``storage.save_json`` / ``write_text`` / ``append_line`` raise and are recorded as ``blocked``; the folder
is checked unchanged (``changed``). Case preparation is switched off (``PZ_CASE_PREP=0``, the job queue cleared): no
case is ever queued, as on the new side.
"""

from __future__ import annotations

import hashlib
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
        n = NOW[-1]  # naive Berlin wall time, whatever zone is asked (events.berlin_today asks for Berlin)
        return cls(n.year, n.month, n.day, n.hour, n.minute, n.second)


def _freeze() -> list[str]:
    """Every loaded old module that imported the ``date`` / ``datetime`` classes reads the frozen clock."""
    from projectzero.domain import ecosys, founder_calls, people, scout_intake, taste  # noqa: F401  (what home() reaches)
    from projectzero.services import case_prep, pipeline, watch  # noqa: F401  (incl. case_prep's lazy imports)

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


def _block() -> None:
    from projectzero import storage

    def blocked(name: str) -> Any:
        def refuse(target: Any, *a: Any, **k: Any) -> None:
            BLOCKED.append(f"{name}:{Path(str(target)).name}")
            raise RuntimeError(f"the Home oracle blocks {name}")

        return refuse

    storage.save_json = blocked("save_json")  # type: ignore[assignment]
    storage.write_text = blocked("write_text")  # type: ignore[assignment]
    storage.append_line = blocked("append_line")  # type: ignore[assignment]


def _digest(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}  # fmt: skip


def run_world(world: dict[str, Any], root: Path) -> dict[str, Any]:
    from projectzero.domain import ecosys
    from projectzero.services import case_prep

    from projectzero import compat, storage

    folder = root / world["name"]
    storage.configure(folder)
    NOW.append(datetime.fromisoformat(world["clock"]))
    _freeze()  # a module first imported by an earlier world's call reads the frozen clock too
    BLOCKED.clear()
    compat.SKIPPED.clear()
    case_prep._queue.clear()
    before = _digest(folder)
    try:
        out: dict[str, Any] = {"ok": ecosys.home()}
    except Exception as exc:  # the old route would have answered 500
        out = {"raises": type(exc).__name__}
    after = _digest(folder)
    changed = sorted(k for k in {**before, **after} if before.get(k) != after.get(k))
    return {"name": world["name"], **out, "blocked": list(BLOCKED), "changed": changed, "skipped": compat.skipped()}


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch folder"
    assert "project-zero-data" not in Path(data_dir).resolve().parts, "PZ_DATA must be a scratch folder"
    assert not os.environ.get("SUPABASE_DB_URL"), "the oracle never sees the database"
    os.environ.setdefault("PZ_TESTING", "1")
    os.environ["PZ_CASE_PREP"] = "0"
    inp = json.loads(src.read_bytes().decode("utf-8"))
    NOW.append(datetime.fromisoformat(inp["worlds"][0]["clock"]))
    frozen = _freeze()
    _block()
    from projectzero.domain import ecosys  # the OLD package

    old_root = Path(ecosys.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    worlds = [run_world(w, Path(data_dir)) for w in inp["worlds"]]
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "mode": "home", "frozen": frozen}
    dst.write_bytes(json.dumps({"meta": meta, "worlds": worlds}, ensure_ascii=False, default=str).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
