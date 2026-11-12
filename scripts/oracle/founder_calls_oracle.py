"""ORACLE: the OLD Founder Calls routes (review 023), FIXED clock, deterministic ids. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/founder_calls_oracle.py IN.json OUT.json

IN = {clock, steps: [{op, body?, id?, at?}]} over a scratch PZ_DATA (a COPY: the writes rewrite founder_calls.json).
``at`` moves the fixed clock from that step on (ISO datetime, Berlin wall clock). Ops, through the old route functions
of ``api/routers/calls.py``:

* ``calls``  GET /api/calls;  ``call`` / ``memo``  GET /api/call?id= / /api/call_memo?id=;  ``briefing``  POST body;
* ``read_all``  GET /api/calls, then every call view and memo (each call id of the stored file, plus an unknown id)
  and the briefing of every founder id (plus an unknown id), ``confirm: true``;
* ``save`` / ``followup`` / ``link``  the POST routes; each is followed by the whole GET /api/calls body (``view``)
  and the stored file (``doc``: the parsed body and its key ORDER, which a sort_keys golden would lose: the top-level
  keys, the ids of the three objects, and the field order of every record).

Each answer is {code, body}; a raised exception is {raises: name}. The old ``_id`` uses ``uuid4``: it is replaced by a
counter (the n-th id is ``prefix + f"{n:012x}"``) so the new side can reproduce it. ``case_prep.request`` after a save
is disabled (``PZ_CASE_PREP=0``) and replaced by a no-op, so it never runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

NOW: list[datetime] = []
COUNTER = [0]


def _freeze() -> None:
    from projectzero.domain import founder_calls, people
    from projectzero.services import case_prep

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

    class _Uuid:
        def __init__(self, n: int) -> None:
            self.hex = f"{n:012x}" + "0" * 20

    class _UuidModule:
        @staticmethod
        def uuid4() -> _Uuid:
            COUNTER[0] += 1
            return _Uuid(COUNTER[0])

    founder_calls.date = FixedDate  # type: ignore[attr-defined]
    founder_calls.datetime = FixedDateTime  # type: ignore[attr-defined]
    founder_calls.uuid = _UuidModule  # type: ignore[attr-defined]
    people.date = FixedDate  # type: ignore[attr-defined]
    case_prep.request = lambda *a, **k: {"queued": False, "disabled": True}  # never prepares a case


def _answer(fn: Any) -> dict[str, Any]:
    from fastapi.responses import JSONResponse

    try:
        r = fn()
    except Exception as exc:  # the old route would have answered 500
        return {"raises": type(exc).__name__}
    if isinstance(r, JSONResponse):
        return {"code": r.status_code, "body": json.loads(r.body)}
    return {"code": 200, "body": json.loads(json.dumps(r, ensure_ascii=False, default=str))}


def _get(fn: Any, call_id: Any) -> dict[str, Any]:
    from starlette.requests import Request

    req = Request({"type": "http", "query_string": urlencode({"id": call_id}).encode(), "headers": []})
    return _answer(lambda: fn(req))


def _doc() -> dict[str, Any]:
    from projectzero import storage

    p = Path(storage.path("founder_calls.json"))
    if not p.exists():
        return {"body": None, "order": None}
    body = json.loads(p.read_text(encoding="utf-8"))
    order: dict[str, Any] = {"top": list(body)}
    for k in ("companies", "founders", "calls"):
        obj = body.get(k)
        if isinstance(obj, dict):
            order[k] = list(obj)
            order[k + "_fields"] = [[i, list(r)] for i, r in obj.items() if isinstance(r, dict)]
    return {"body": body, "order": order}


def _stored_ids() -> tuple[list[str], list[str]]:
    from projectzero.domain import founder_calls

    d = founder_calls.load()
    return list(d["calls"]), list(d["founders"])


def replay(inp: dict[str, Any]) -> list[dict[str, Any]]:
    from projectzero import storage
    from projectzero.api.routers import calls as r

    out: list[dict[str, Any]] = []
    for step in inp["steps"]:
        if step.get("at"):
            NOW.append(datetime.fromisoformat(step["at"]))
        op = step["op"]
        row: dict[str, Any] = {}
        if op == "calls":
            row["answer"] = _answer(r.calls)
        elif op == "call":
            row["answer"] = _get(r.call, step["id"])
        elif op == "memo":
            row["answer"] = _get(r.call_memo, step["id"])
        elif op == "briefing":
            row["answer"] = _answer(lambda step=step: r.call_briefing(step["body"]))
        elif op == "read_all":
            call_ids, founder_ids = _stored_ids()
            row["view"] = _answer(r.calls)
            row["call"] = {i: _get(r.call, i) for i in [*call_ids, "fc-call-unknown"]}
            row["memo"] = {i: _get(r.call_memo, i) for i in [*call_ids, "fc-call-unknown"]}
            row["briefing"] = {
                i: _answer(lambda i=i: r.call_briefing({"founder_id": i, "confirm": True}))
                for i in [*founder_ids, "fc-f-unknown"]
            }
        else:
            fn = {"save": r.call_save, "followup": r.call_followup, "link": r.call_link}[op]
            with storage.state_lock:
                row["answer"] = _answer(lambda fn=fn, step=step: fn(step["body"]))
            row["view"] = _answer(r.calls)
            row["doc"] = _doc()
        out.append(row)
    return out


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch folder"
    os.environ.setdefault("PZ_TESTING", "1")
    os.environ["PZ_CASE_PREP"] = "0"
    inp = json.loads(src.read_text(encoding="utf-8"))
    NOW.append(datetime.fromisoformat(inp["clock"]))
    _freeze()
    from projectzero.domain import taste  # the OLD package

    steps = replay(inp)
    old_root = Path(taste.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "clock": inp["clock"], "mode": "founder_calls",
            "ids_made": COUNTER[0]}  # fmt: skip
    dst.write_text(json.dumps({"meta": meta, "steps": steps}, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
