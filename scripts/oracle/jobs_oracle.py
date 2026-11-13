"""ORACLE: the OLD background-jobs runner (review 032c), ``services/scheduler.py`` ``run_due`` / ``plan`` /
``classify`` / ``recover_on_start`` / ``dry_run`` / ``failing_jobs`` and the old CLI ``--background [--dry-run]``,
over FAKE jobs (the old tests' pattern) in a scratch data folder per case, with a FIXED clock. Never imported by new
code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/jobs_oracle.py IN.json OUT.json

IN = {cases: [{name, clock, jobs: [{id, label, interval_h, notes}], steps: [...]}], classify: [[note, ok]]}; the data
folder of case ``name`` is ``PZ_DATA/<name>`` (its files written by the parity script). A fake job returns its
``notes`` in turn (the last one repeats); a note ``"!raise:<text>"`` raises ``RuntimeError(<text>)``. A record whose
``pid`` is ``"DEAD"`` gets the pid of a process that has exited.

Steps: ``run_due {source, only?}``, ``plan``, ``dry_run``, ``recover_on_start``, ``failing_jobs``, ``hold_lock
{source, since}`` (another LIVE runner holds ``run.lock``: this process's own pid), ``release_lock``, ``cli {argv}``
(the old ``projectzero.__main__.main``; ``--background`` against this folder named as the production folder),
``advance {clock}``. After every step the oracle records the step's answer and the three state files
(``jobs.json``, the ``runs.jsonl`` lines, ``runner.json``) and, for a CLI step, the lines it appended to
``schedule/background.log``.

Frozen: ``datetime.now`` / ``date.today`` in every loaded old ``projectzero`` module, and the scheduler's
``time.time`` (every duration is 0.0). Stubbed: ``scheduler.background_backup`` (decision e: no backup; it answers
"not made"). Writes: ``storage.save_json`` / ``write_text`` / ``append_line`` are refused outside ``schedule/`` and
recorded as ``blocked``. Refused: a ``PZ_DATA`` inside ``project-zero-data``, and any ``SUPABASE_DB_URL``.
"""

from __future__ import annotations

import contextlib
import io
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
FROZEN_TIME = 1000.0


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


def _block() -> None:
    from projectzero import storage

    def only_schedule(name: str, fn: Any) -> Any:
        def guarded(target: Any, *a: Any, **k: Any) -> Any:
            p = Path(str(target))
            rel = p.relative_to(storage.data_dir()).as_posix() if p.is_absolute() else p.as_posix()
            if not rel.startswith("schedule/"):
                BLOCKED.append(f"{name}:{rel}")
                raise RuntimeError(f"the jobs oracle blocks {name} outside schedule/: {rel}")
            return fn(target, *a, **k)

        return guarded

    storage.save_json = only_schedule("save_json", storage.save_json)  # type: ignore[assignment]
    storage.write_text = only_schedule("write_text", storage.write_text)  # type: ignore[assignment]
    storage.append_line = only_schedule("append_line", storage.append_line)  # type: ignore[assignment]


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait(30)
    return p.pid


def _fake_jobs(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def make(spec: dict[str, Any]) -> Any:
        notes = list(spec["notes"])
        calls = {"n": 0}

        def run() -> str:
            note = notes[min(calls["n"], len(notes) - 1)]
            calls["n"] += 1
            if note.startswith("!raise:"):
                raise RuntimeError(note[len("!raise:") :])
            return str(note)

        return run

    return [{"id": s["id"], "label": s["label"], "interval_h": s["interval_h"], "run": make(s), "last": None}
            for s in specs]  # fmt: skip


def _state(folder: Path) -> dict[str, Any]:
    def load(rel: str, default: Any) -> Any:
        p = folder / rel
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

    runs = folder / "schedule" / "runs.jsonl"
    lines = [json.loads(x) for x in runs.read_text(encoding="utf-8").splitlines() if x.strip()] if runs.exists() else []
    runner = folder / "schedule" / "runner.json"
    return {"jobs": load("schedule/jobs.json", {}), "runs": lines, "runner": load("schedule/runner.json", {}),
            "runner_text": json.dumps(json.loads(runner.read_text(encoding="utf-8")), ensure_ascii=False)
            if runner.exists() else "{}"}  # fmt: skip


def _files(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) + str(p.stat().st_mtime_ns) for p in folder.rglob("*") if p.is_file())


def _log_lines(folder: Path) -> list[str]:
    p = folder / "schedule" / "background.log"
    return p.read_text(encoding="utf-8").splitlines() if p.exists() else []


def run_case(case: dict[str, Any], root: Path) -> dict[str, Any]:
    from projectzero.services import scheduler
    from projectzero.settings import get_settings

    from projectzero import __main__ as cli
    from projectzero import storage

    folder = root / case["name"]
    jobs_file = folder / "schedule" / "jobs.json"
    if jobs_file.exists():  # a record of a process that has exited
        st = json.loads(jobs_file.read_text(encoding="utf-8"))
        for rec in st.values():
            if isinstance(rec, dict) and rec.get("pid") == "DEAD":
                rec["pid"] = _dead_pid()
        jobs_file.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    storage.configure(folder)
    os.environ["PZ_DATA"] = str(folder)
    os.environ["PZ_PRODUCTION_DATA"] = str(folder)
    get_settings.cache_clear()
    NOW.append(datetime.fromisoformat(case["clock"]))
    _freeze()
    scheduler.JOBS[:] = _fake_jobs(case["jobs"])
    BLOCKED.clear()
    steps = []
    for step in case["steps"]:
        op = step["op"]
        out: Any = None
        log_before = _log_lines(folder)
        before = _files(folder)
        if op == "run_due":
            out = scheduler.run_due(only=step.get("only"), source=step["source"])
        elif op == "plan":
            out = scheduler.plan()
        elif op == "dry_run":
            out = scheduler.dry_run()
            out = {**out, "wrote": before != _files(folder)}
        elif op == "recover_on_start":
            out = scheduler.recover_on_start()
        elif op == "failing_jobs":
            out = scheduler.failing_jobs()
        elif op == "hold_lock":
            lock = folder / scheduler.LOCK_FILE
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.write_text(json.dumps({"pid": os.getpid(), "token": "other", "source": step["source"],
                                        "started": step["since"]}), encoding="utf-8")  # fmt: skip
        elif op == "release_lock":
            (folder / scheduler.LOCK_FILE).unlink()
        elif op == "advance":
            NOW.append(datetime.fromisoformat(step["clock"]))
        elif op == "cli":
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = cli.main(list(step["argv"]))
            lines = buf.getvalue().splitlines()
            for where in (str(storage.data_dir()), str(folder.resolve()), str(folder)):  # no local path is recorded
                lines = [x.replace(where, "<scratch folder>") for x in lines]
            out = {"code": code, "stdout": lines, "log": _log_lines(folder)[len(log_before) :]}
        else:
            raise ValueError(f"unknown step {op}")
        steps.append({"op": op, "out": out, **_state(folder)})
    return {"name": case["name"], "steps": steps, "blocked": list(BLOCKED)}


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and "project-zero-data" not in Path(data_dir).resolve().parts, "PZ_DATA must be a scratch folder"
    assert not os.environ.get("SUPABASE_DB_URL"), "the oracle never sees the database"
    os.environ.setdefault("PZ_TESTING", "1")
    os.environ["PZ_CATCHUP"] = "1"  # the scheduler itself is enabled (config.json may switch it off per case)
    inp = json.loads(src.read_bytes().decode("utf-8"))
    NOW.append(datetime.fromisoformat(inp["cases"][0]["clock"]))
    from projectzero.inference import ledger  # noqa: F401
    from projectzero.services import scheduler

    from projectzero import __main__ as cli  # noqa: F401
    from projectzero import production, settings, storage  # noqa: F401

    frozen = _freeze()
    _block()
    scheduler.time = types.SimpleNamespace(time=lambda: FROZEN_TIME, sleep=lambda s: None)  # type: ignore[assignment]
    scheduler.background_backup = lambda now=None: {"made": False, "reason": "stub (decision e)"}  # type: ignore[assignment]
    old_root = Path(scheduler.__file__).resolve().parents[4]
    revision = subprocess.run(["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=False).stdout.strip()  # fmt: skip
    dirty = subprocess.run(["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
                           capture_output=True, text=True, check=False).stdout.strip()  # fmt: skip
    classify = [[note, ok, scheduler.classify(note, ok)] for note, ok in inp["classify"]]
    cases = [run_case(c, Path(data_dir)) for c in inp["cases"]]
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "mode": "jobs", "frozen": frozen,
            "outcomes": dict(scheduler.OUTCOMES)}  # fmt: skip
    dst.write_bytes(json.dumps({"meta": meta, "classify": classify, "cases": cases}, ensure_ascii=False,
                               default=str).encode("utf-8"))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
