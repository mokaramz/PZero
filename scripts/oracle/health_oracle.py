"""ORACLE: the OLD System health reads (review 032a), ``services/health.system()`` and
``services/health_overview.overview()``, over invented worlds with a FIXED clock and every write blocked. Never
imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/health_oracle.py IN.json OUT.json

IN = {worlds: [{name, clock, paid, key}]}; the data folder of world ``name`` is ``PZ_DATA/<name>`` (written by the
parity script). Per world, in order: ``storage`` is pointed at its folder, the clock is frozen at ``clock`` (naive
Berlin wall time) in every loaded old ``projectzero`` module whose ``date`` / ``datetime`` is the standard class
(``health``, ``health_overview``, ``scheduler``, ``inference.ledger``, ``validation``, ...), the environment is the
world's (decision f: ``paid`` false is the old ``PZ_AI_PAID=off``; ``key`` sets ``DEEPINFRA_API_KEY`` to a
placeholder, presence only), the coverage cache and the ledger cache are emptied, then ``system()`` and
``overview()`` are each called once.

Stubbed to FIXED values (their keys are then normalised by the declared items of ``ops/parity_health``):

* the retired Scout services (decision c): ``search_bridge.status`` and ``scout00_transport.status`` answer no
  notice; the four retired jobs are removed from ``scheduler.JOBS`` (their rows, ``native_bridge``'s calendar rule
  included, are never planned);
* the absent subsystems (decision d): ``selfcheck.view`` (no degraded part), ``build_info.view``,
  ``source_network.health`` (no technical failure), ``backup.list_backups`` / ``backup_dir`` and
  ``integrity.check``;
* ``scheduler.pid_alive`` answers ``False`` (decision e: no runner is alive).

The coverage cache thread is disabled (``health.threading.Thread`` raises if started; each world's first call
computes the coverage synchronously). Writes: ``storage.save_json`` / ``write_text`` / ``append_line`` raise and are
recorded as ``blocked``, except the Founder Radar configuration defaults the old coverage read SAVED when they were
missing (``radar_regions.json`` / ``radar_sources.json``): those saves are dropped and recorded as ``held`` (the
old read then returns the same defaults, as the new read does in memory). The folder is checked unchanged
(``changed``).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import types
from datetime import date, datetime
from pathlib import Path
from typing import Any

NOW: list[datetime] = []
BLOCKED: list[str] = []
HELD: list[str] = []
HOLD = ("radar_regions.json", "radar_sources.json")  # the Founder Radar defaults the old coverage read saved
RETIRED_JOBS = ("scout00_inbox", "native_scout", "native_planner", "native_bridge")
KEY_VARS = ("DEEPINFRA_API_KEY", "XAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
PLACEHOLDER = "invented-placeholder"  # presence only: no old read sends it anywhere


class FixedDate(date):
    @classmethod
    def today(cls) -> FixedDate:  # type: ignore[override]
        n = NOW[-1]
        return cls(n.year, n.month, n.day)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> FixedDateTime:  # type: ignore[override]
        n = NOW[-1]  # naive Berlin wall time, whatever zone is asked
        return cls(n.year, n.month, n.day, n.hour, n.minute, n.second)


def _imports() -> None:
    """Everything the two reads reach, imported before the clock is frozen."""
    from projectzero.domain import connectors, coverage, event_sources  # noqa: F401
    from projectzero.domain.founder_radar import sources, store  # noqa: F401
    from projectzero.inference import budget, ledger  # noqa: F401
    from projectzero.inference import config as icfg  # noqa: F401
    from projectzero.services import (  # noqa: F401
        auto_triage,
        backup,
        health,
        health_overview,
        integrity,
        news,
        news_sources,
        scheduler,
        scout00_transport,
        search_bridge,
        selfcheck,
        shadow_triage,
        source_network,
        triage_review,
        validation,
        watch,
    )

    from projectzero import build_info, compat, storage  # noqa: F401


def _freeze() -> list[str]:
    """Every loaded old module that imported the ``date`` / ``datetime`` classes reads the frozen clock."""
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
            base = Path(str(target)).name
            if name == "save_json" and base in HOLD:
                HELD.append(f"{name}:{base}")
                return None
            BLOCKED.append(f"{name}:{base}")
            raise RuntimeError(f"the System health oracle blocks {name}")

        return refuse

    storage.save_json = blocked("save_json")  # type: ignore[assignment]
    storage.write_text = blocked("write_text")  # type: ignore[assignment]
    storage.append_line = blocked("append_line")  # type: ignore[assignment]


def _stub() -> None:
    from projectzero.services import (
        backup,
        health,
        integrity,
        scheduler,
        scout00_transport,
        search_bridge,
        selfcheck,
        source_network,
    )

    from projectzero import build_info

    quiet = {"notice": "", "level": "", "do": ""}
    search_bridge.status = lambda *a, **k: {**quiet, "stub": "search_bridge"}  # type: ignore[assignment]
    scout00_transport.status = lambda *a, **k: {**quiet, "stub": "scout00_transport"}  # type: ignore[assignment]
    selfcheck.view = lambda *a, **k: {"degraded": [], "stub": "selfcheck"}  # type: ignore[assignment]
    build_info.view = lambda *a, **k: {"stub": "build_info"}  # type: ignore[assignment]
    source_network.health = lambda *a, **k: {"stub": "source_network"}  # type: ignore[assignment]
    backup.list_backups = lambda *a, **k: []  # type: ignore[assignment]
    backup.backup_dir = lambda *a, **k: Path("stub-backups")  # type: ignore[assignment]
    integrity.check = lambda *a, **k: {"status": "stub", "issues": [], "files_checked": 0, "checked_at": None}  # type: ignore[assignment]
    scheduler.pid_alive = lambda pid: False  # type: ignore[assignment]
    scheduler.JOBS[:] = [j for j in scheduler.JOBS if j["id"] not in RETIRED_JOBS]

    def no_thread(*a: Any, **k: Any) -> Any:
        raise RuntimeError("the System health oracle disables the coverage cache thread")

    health.threading = types.SimpleNamespace(Thread=no_thread)  # type: ignore[assignment]


def _digest(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}  # fmt: skip


def _env(world: dict[str, Any]) -> None:
    for var in (*KEY_VARS, "PZ_AI_PAID", "PZ_SCOUT00_PAID"):
        os.environ.pop(var, None)
    if not world["paid"]:
        os.environ["PZ_AI_PAID"] = "off"  # the old switch was on unless set off (decision f)
    if world["key"]:
        os.environ["DEEPINFRA_API_KEY"] = PLACEHOLDER


def _call(fn: Any) -> dict[str, Any]:
    try:
        return {"ok": fn()}
    except Exception as exc:  # the old route would have answered 500
        return {"raises": f"{type(exc).__name__}: {exc}"}


def run_world(world: dict[str, Any], root: Path) -> dict[str, Any]:
    from projectzero.services import health, health_overview

    from projectzero import compat, storage

    folder = root / world["name"]
    storage.configure(folder)
    NOW.append(datetime.fromisoformat(world["clock"]))
    _freeze()  # a module first imported by an earlier world's call reads the frozen clock too
    _env(world)
    BLOCKED.clear()
    HELD.clear()
    compat.SKIPPED.clear()
    health._COV_CACHE.update(sig=None, value=None, at=0.0, refreshing=False)
    health_overview._cache.clear()
    before = _digest(folder)
    system = _call(health.system)
    overview = _call(health_overview.overview)
    after = _digest(folder)
    changed = sorted(k for k in {**before, **after} if before.get(k) != after.get(k))
    return {"name": world["name"], "system": system, "overview": overview, "blocked": list(BLOCKED),
            "held": sorted(set(HELD)), "changed": changed, "skipped": compat.skipped()}  # fmt: skip


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch folder"
    assert "project-zero-data" not in Path(data_dir).resolve().parts, "PZ_DATA must be a scratch folder"
    assert not os.environ.get("SUPABASE_DB_URL"), "the oracle never sees the database"
    os.environ.setdefault("PZ_TESTING", "1")
    inp = json.loads(src.read_bytes().decode("utf-8"))
    NOW.append(datetime.fromisoformat(inp["worlds"][0]["clock"]))
    _imports()
    frozen = _freeze()
    _block()
    _stub()
    from projectzero.services import health  # the OLD package

    old_root = Path(health.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    worlds = [run_world(w, Path(data_dir)) for w in inp["worlds"]]
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "mode": "health", "frozen": frozen}
    dst.write_bytes(json.dumps({"meta": meta, "worlds": worlds}, ensure_ascii=False, default=str).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
