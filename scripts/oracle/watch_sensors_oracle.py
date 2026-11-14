"""ORACLE: the OLD WATCH sensors (review 037b): ``watch.run_checks(only)``, ``set_target`` and the news bridge
(``news._watch_bridge``), with a FIXED clock. Never imported by the new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/watch_sensors_oracle.py IN.json OUT.json

IN = {steps: [{clock, op: "check" | "target" | "files" | "bridge", ...}]}. ``PZ_DATA`` is a scratch folder holding the
world's files (``inbox.json``, ``triage_proposals.json``, ``watch/targets.json``, ``watch/triggers.jsonl``,
``.watch/wt-*.json`` ...).

* ``check`` (``only``, ``pages``): ``connectors._get`` answers each URL from the step's recorded bytes (``pages[url]``:
  ``{"body": text}`` or ``{"raw_b64": bytes}``, decoded as the old ``fetch_text`` decoded them, or ``{"error": msg}``,
  raised as ``OSError(msg)``); an URL not listed raises ``KeyError``. The answer is the old route's
  ``{fired, pages, failures}``.
* ``target`` (``body``): the old ``set_target(body)``.
* ``files`` (``files``): write the given world files (a str as text, anything else as JSON) before the step's record.
* ``bridge`` (``events``): ``news/events.json`` holds ``{"events": events}``, then the old ``_watch_bridge()``.

Per step the record of: the answer, the whole ``watch/triggers.jsonl`` text, the ``watch/targets.json`` document, the
``.watch/wt-*.json`` snapshots (name -> lines), the ``case_prep.on_watch_trigger`` calls (stubbed and recorded:
decision f), the URLs fetched, and the old ``view()``.

The clock: ``datetime.now()`` / ``date.today()`` of every loaded ``projectzero`` module. Writes: ``storage.save_json``
/ ``write_text`` / ``append_line`` outside the scratch data folder are refused and recorded as ``blocked``. Refused: a
``PZ_DATA`` inside ``project-zero-data``, and any ``SUPABASE_DB_URL``.
"""

from __future__ import annotations

import base64
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


def _snapshots(root: Path) -> dict[str, Any]:
    d = root / ".watch"
    if not d.exists():
        return {}
    return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("wt-*.json"))}


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and "project-zero-data" not in Path(data_dir).resolve().parts, "PZ_DATA must be a scratch folder"
    assert not os.environ.get("SUPABASE_DB_URL"), "the oracle never sees the database"
    os.environ.setdefault("PZ_TESTING", "1")
    root = Path(data_dir).resolve()
    inp = json.loads(src.read_bytes().decode("utf-8"))
    NOW.append(datetime.fromisoformat(inp["steps"][0]["clock"]))
    from projectzero.domain import connectors
    from projectzero.services import case_prep, news, watch

    from projectzero import storage

    storage.configure(root)
    frozen = _freeze()
    _block(root)
    calls: list[list[str]] = []
    case_prep.on_watch_trigger = lambda name, label: calls.append([name, label])  # type: ignore[assignment]
    served: dict[str, Any] = {}
    asked: list[str] = []

    def fake_get(url: str) -> str:
        asked.append(url)
        spec = served[url]  # an URL the step does not serve: KeyError (a failed check)
        if "error" in spec:
            raise OSError(spec["error"])
        if "raw_b64" in spec:
            return base64.b64decode(spec["raw_b64"]).decode("utf-8", errors="replace")
        return str(spec["body"]).encode("utf-8").decode("utf-8", errors="replace")

    connectors._get = fake_get  # type: ignore[assignment]
    steps = []
    for step in inp["steps"]:
        NOW.append(datetime.fromisoformat(step["clock"]))
        calls.clear()
        asked.clear()
        op = step["op"]
        answer: Any = None
        if op == "check":
            served.clear()
            served.update(step.get("pages") or {})
            r = watch.run_checks(only=step.get("only") or None)
            answer = {"fired": r["fired"], "pages": r["pages"], "failures": r["failures"]}
        elif op == "target":
            try:
                answer = watch.set_target(copy.deepcopy(step["body"]))
            except watch.WatchError as e:
                answer = {"error": str(e)}
        elif op == "files":
            for rel, content in step["files"].items():
                if isinstance(content, str):
                    storage.write_text(rel, content)
                else:
                    storage.save_json(rel, content)
        elif op == "bridge":
            storage.save_json("news/events.json", {"events": step["events"]})
            answer = {"watch_triggers": news._watch_bridge()}
        else:
            raise SystemExit(f"unknown op {op}")
        steps.append({
            "clock": step["clock"],
            "op": op,
            "answer": json.loads(json.dumps(answer, ensure_ascii=False)),
            "log": storage.read_text(watch.TRIGGERS),
            "targets": storage.load_json(watch.TARGETS, None, tolerant=True),
            "snapshots": _snapshots(root),
            "case_refresh": copy.deepcopy(calls),
            "fetched": list(asked),
            "view": watch.view(),
        })  # fmt: skip
    old_root = Path(watch.__file__).resolve().parents[4]
    revision = subprocess.run(["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()  # fmt: skip
    dirty = subprocess.run(["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
                           capture_output=True, text=True, check=True).stdout.strip()  # fmt: skip
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "mode": "watch_sensors", "frozen": frozen}
    out = {"meta": meta, "steps": steps, "blocked": list(BLOCKED)}
    dst.write_bytes(json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
