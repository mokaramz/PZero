"""ORACLE: the OLD Validation writes (review 027b), with a FIXED clock and the id seam. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/validation_writes_oracle.py IN.json OUT.json

IN = {clock, steps: [{op, body, id_from?, seam}]} over a scratch PZ_DATA. Each step calls the old function the old
route called, in order, over the logs as the previous steps left them:

* ``outcome``   -> ``record_outcome(body)``  answered ``{ok: true, entry}`` (``POST /api/validation_outcome``);
* ``audit``     -> ``record_audit(body)``    likewise;
* ``retract``   -> ``retract(body)``         likewise (``id_from: n``: ``body.id`` is step n's ``entry.id``);
* ``benchmark`` -> ``import_benchmark(body)`` answered bare;
* ``mark``      -> ``scout_packet(str(body.get("cycle") or ""), mark=True)`` answered bare.

A ``ValidationError`` is the old 400 ``{code: 400, error}``; any other exception the old 500 ``{raises: name}``. Each
step records ``appended``: the ``[log, text]`` pairs its ``storage.append_line`` calls wrote, ``text`` being exactly
what the old function wrote to the file (``line.replace("\\n", " ") + "\\n"``, before any platform newline translation).
The appends go to IN-MEMORY logs that every later old read sees (``storage.read_text`` of a log is the file plus its
in-memory lines, exactly as the file would have grown); the data folder is checked unchanged (``changed``). After the
steps, ``view``: the old ``view(today)`` (its own ``_snapshot`` append also in memory, recorded as
``view_appended``).

The clock is frozen everywhere the old code read it (``date.today()`` / ``datetime.now()`` / ``ledger.now_ts()``), and
the id seam: the old ``_id`` hashed ``str(datetime.now().timestamp())``; the frozen ``datetime.now()`` answers the
step's ``seam`` values in order (the new code's ``new_hex()``). The deferred views are made unavailable as in the 027a
oracle (``validation_oracle._defer``), so the old packet takes its own fallback lines.
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
from typing import Any, ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validation_oracle import _defer  # the 027a oracle's stubs, shared

LOGS = {
    "validation/outcomes.jsonl": "outcomes",
    "validation/audits.jsonl": "audits",
    "validation/snapshots.jsonl": "snapshots",
    "validation/scout_feedback.jsonl": "scout_feedback",
}


class BlockedWrite(RuntimeError):
    pass


class Seam:
    values: ClassVar[list[str]] = []

    @classmethod
    def next(cls) -> str:
        if not cls.values:
            raise RuntimeError("the id seam ran out of values")
        return cls.values.pop(0)


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

        def timestamp(self) -> Any:  # type: ignore[override]
            return Seam.next()  # the old ``_id``'s ``str(datetime.now().timestamp())``: the new ``new_hex()``

    for module in (validation, taste, compressor, news, pipeline, source_network, ledger):
        if hasattr(module, "date"):
            module.date = FixedDate  # type: ignore[attr-defined]
        if hasattr(module, "datetime"):
            module.datetime = FixedDateTime  # type: ignore[attr-defined]
    ledger.now_ts = lambda: fixed.strftime(ledger.TS_FORMAT)  # type: ignore[attr-defined]


def _guard(memory: dict[str, list[str]], step_log: list[list[str]]) -> None:
    """The four Validation logs grow in ``memory`` (read back by ``read_text``); every other write raises."""
    storage = importlib.import_module("projectzero.storage")
    read_text = storage.read_text

    def append_line(name: Any, line: str) -> None:
        log = LOGS.get(str(name).replace("\\", "/"))
        if log is None:
            raise BlockedWrite(f"append_line {name}")
        text = line.replace("\n", " ") + "\n"  # exactly what the file would have received
        memory[log].append(text)
        step_log.append([log, text])

    def read(name: Any, default: str = "") -> str:
        text = read_text(name, default)
        log = LOGS.get(str(name).replace("\\", "/"))
        return text + "".join(memory[log]) if log else text

    def blocked(name: Any, *_a: Any, **_k: Any) -> None:
        raise BlockedWrite(f"write {name}")

    storage.append_line = append_line
    storage.read_text = read
    storage.save_json = blocked
    storage.write_text = blocked


def _hashes(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _js(r: Any) -> Any:
    return json.loads(json.dumps(r, ensure_ascii=False, default=str))


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
    memory: dict[str, list[str]] = {log: [] for log in LOGS.values()}
    step_log: list[list[str]] = []
    _guard(memory, step_log)
    _defer()
    from projectzero.domain import taste  # the OLD package
    from projectzero.services import validation

    calls = {
        "outcome": lambda b: {"ok": True, "entry": validation.record_outcome(b)},
        "audit": lambda b: {"ok": True, "entry": validation.record_audit(b)},
        "retract": lambda b: {"ok": True, "entry": validation.retract(b)},
        "benchmark": validation.import_benchmark,
        "mark": lambda b: validation.scout_packet(str(b.get("cycle") or ""), mark=True),
    }
    steps: list[dict[str, Any]] = []
    for step in inp["steps"]:
        body = dict(step["body"])
        if step.get("id_from") is not None:
            body["id"] = steps[step["id_from"]]["answer"]["body"]["entry"]["id"]
        Seam.values = list(step["seam"])
        step_log.clear()
        try:
            answer: dict[str, Any] = {"code": 200, "body": _js(calls[step["op"]](body))}
        except validation.ValidationError as exc:  # the old route's ApiError: 400 {ok: false, error}
            answer = {"code": 400, "error": str(exc)}
        except Exception as exc:  # the old route would have answered 500
            answer = {"raises": type(exc).__name__}
        steps.append({"answer": answer, "appended": [list(x) for x in step_log]})
    today = datetime.fromisoformat(inp["clock"]).date()
    step_log.clear()
    try:
        view: dict[str, Any] = {"code": 200, "body": _js(validation.view(today))}
    except Exception as exc:
        view = {"raises": type(exc).__name__}
    view_appended = [x[1] for x in step_log]
    after = _hashes(Path(data_dir))
    changed = sorted(k for k in {**before, **after} if before.get(k) != after.get(k))
    old_root = Path(taste.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "clock": inp["clock"], "mode": "validation-writes"}
    out = {"meta": meta, "steps": steps, "view": view, "view_appended": view_appended, "changed": changed}
    dst.write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
