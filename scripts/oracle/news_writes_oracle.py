"""ORACLE: the OLD News writes (review 028b), with a FIXED clock, the id seam and EVERY write in memory. Never imported
by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/news_writes_oracle.py IN.json OUT.json

IN = {clock, cases_dir, sequences: [{name, steps: [{op, body, seam}]}]} over a scratch PZ_DATA (``cases_dir``: the
old ``SEED_CASES``, as in the 028a oracle). Each sequence starts from the FRESH data folder (every in-memory store is
cleared). Each step, in order:

1. ``seed``: the old GET-time seeding exactly as the old ``news.view()`` ran it (its guard, then ``seed_cases()``): the
   store's ``ensure_seeded`` at the start of every News write transaction (028b revision 2), recorded as ``{added,
   changes: [[event_id, record]], rest}`` (the events whose stored record changed, in document order, and the
   document's other top-level keys) or ``null`` when nothing was saved;
2. the old function the old route called: ``op`` ``outcome`` -> ``news.decide_outcome(body)``, ``audit`` ->
   ``news.audit_miss(body)``, ``backcast`` -> ``news.add_backcast_signal(body)``. A ``ValueError`` is the old 400
   ``{code: 400, error}`` (the route's ``_guard``); any other exception the old 500 ``{raises: name}``. ``appended``:
   the ``[log, text]`` pairs its ``storage.append_line`` calls wrote, in order (``actions`` for
   ``news/actions.jsonl``, the 027b names for the Validation logs; ``text`` exactly what the file received:
   ``line.replace("\\n", " ") + "\\n"``); ``saved``: what its ``_save`` wrote, as ``{changes, rest}`` (or ``null``);
3. ``news_view`` / ``validation_view``: the next old ``news.view()`` and ``validation.view(today)``. A view never
   persists anything here (its seeding is a no-op after step 1; the Validation ``_snapshot`` append is discarded, the
   new views are pure).

The events-document save is the 028a ``install_news`` (the JSON text the old ``save_json`` wrote, read back by
``load_json``); the logs grow in memory and every later old read sees them (``storage.read_text`` = the file plus its
in-memory lines); every other write raises; the data folder is checked unchanged (``changed``). The clock is frozen
everywhere the old code read it and the old ``validation._id``'s ``str(datetime.now().timestamp())`` answers the
step's ``seam`` values (the new ``new_hex()``), as in the 027b oracle. System health answers no rows and the deferred
views are unavailable, as in the 028a / 027a oracles.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parent))

from news_oracle import EVENTS, install_news, meta, no_health  # the 028a oracle, shared
from validation_oracle import _defer  # the 027a oracle's stubs, shared

LOGS = {
    "news/actions.jsonl": "actions",
    "validation/outcomes.jsonl": "outcomes",
    "validation/audits.jsonl": "audits",
    "validation/snapshots.jsonl": "snapshots",
    "validation/scout_feedback.jsonl": "scout_feedback",
}


class BlockedWrite(RuntimeError):
    pass


class Seam:
    values: ClassVar[list[str] | None] = None

    @classmethod
    def next(cls) -> str:
        if not cls.values:
            raise RuntimeError("the id seam ran out of values")
        return cls.values.pop(0)


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

        def timestamp(self) -> Any:  # type: ignore[override]
            if Seam.values is None:  # outside a write: no id is made
                raise RuntimeError("a timestamp outside a write")
            return Seam.next()  # the old ``_id``'s ``str(datetime.now().timestamp())``: the new ``new_hex()``

    for module in (validation, taste, compressor, news, news_sources, health, pipeline, source_network, ledger):
        if hasattr(module, "date"):
            module.date = FixedDate  # type: ignore[attr-defined]
        if hasattr(module, "datetime"):
            module.datetime = FixedDateTime  # type: ignore[attr-defined]
    ledger.now_ts = lambda: fixed.strftime(ledger.TS_FORMAT)  # type: ignore[attr-defined]


def _guard(memory: dict[str, list[str]], step_log: list[list[str]]) -> None:
    """The logs grow in ``memory`` (read back by ``read_text``); every other write raises. Installed BEFORE
    ``install_news``, which keeps the events-document save in memory on top of it."""
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


def _text(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def _doc() -> Any:
    from projectzero.services import news

    return news.load()


def _saved(before: Any, after: Any) -> dict[str, Any]:
    """The events whose stored record changed (document order) and the other top-level keys of what was saved."""
    old = before.get("events") or {}
    changes = [[eid, rec] for eid, rec in after["events"].items() if eid not in old or _text(old[eid]) != _text(rec)]
    return {"changes": changes, "rest": {k: v for k, v in after.items() if k != "events"}}


def _view(fn: Any, memory: dict[str, list[str]]) -> dict[str, Any]:
    keep = {log: list(rows) for log, rows in memory.items()}
    try:
        r: dict[str, Any] = {"code": 200, "body": _js(fn())}
    except Exception as exc:  # the old route would have answered 500
        r = {"raises": type(exc).__name__}
    for log, rows in keep.items():  # a view never persists here (the Validation snapshot append is discarded)
        memory[log][:] = rows
    return r


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch folder"
    assert not os.environ.get("SUPABASE_DB_URL"), "the oracle never sees the database"
    os.environ.setdefault("PZ_TESTING", "1")
    os.environ["PZ_CASE_PREP"] = "0"
    inp = json.loads(src.read_text(encoding="utf-8"))
    before_files = _hashes(Path(data_dir))
    _freeze(inp["clock"])
    memory: dict[str, list[str]] = {log: [] for log in LOGS.values()}
    events_memory: dict[str, str] = {}
    step_log: list[list[str]] = []
    _guard(memory, step_log)
    install_news(events_memory, inp["cases_dir"])
    no_health()
    _defer()
    from projectzero.services import news, validation  # the OLD package

    storage = importlib.import_module("projectzero.storage")

    today = datetime.fromisoformat(inp["clock"]).date()
    calls = {"outcome": news.decide_outcome, "audit": news.audit_miss, "backcast": news.add_backcast_signal}
    sequences: dict[str, Any] = {}
    for seq in inp["sequences"]:
        for rows in memory.values():
            rows.clear()
        events_memory.clear()  # a FRESH data folder per sequence
        steps: list[dict[str, Any]] = []
        for step in seq["steps"]:
            # 1. the store's ensure_seeded: the old view's guard, then seed_cases()
            seed: Any = None
            before_text = events_memory.get(EVENTS)
            before = _doc()
            try:
                if news.SEED_CASES.exists() and len(news.load()["seeded"]) < len(list(news.SEED_CASES.glob("*.json"))):
                    with storage.state_lock:
                        added = news.seed_cases()
                    if events_memory.get(EVENTS) != before_text:
                        seed = {"added": added, **_saved(before, _doc())}
            except Exception as exc:
                seed = {"raises": type(exc).__name__}
            # 2. the write
            step_log.clear()
            before_text = events_memory.get(EVENTS)
            before = _doc()
            Seam.values = list(step["seam"])
            try:
                answer: dict[str, Any] = {"code": 200, "body": _js(calls[step["op"]](dict(step["body"])))}
            except ValueError as exc:  # the old route's _guard: ApiError, 400 {ok: false, error}
                answer = {"code": 400, "error": str(exc)}
            except Exception as exc:  # the old route would have answered 500
                answer = {"raises": type(exc).__name__}
            Seam.values = None
            saved = _saved(before, _doc()) if events_memory.get(EVENTS) != before_text else None
            appended = [list(x) for x in step_log]
            # 3. the next views
            news_view = _view(news.view, memory)
            validation_view = _view(lambda: validation.view(today), memory)
            steps.append({"seed": seed, "answer": answer, "appended": appended, "saved": saved,
                          "news_view": news_view, "validation_view": validation_view})  # fmt: skip
        sequences[seq["name"]] = steps
    after_files = _hashes(Path(data_dir))
    changed = sorted(k for k in {**before_files, **after_files} if before_files.get(k) != after_files.get(k))
    out = {"meta": meta("news-writes", inp["clock"]), "sequences": sequences, "changed": changed}
    dst.write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
