"""ORACLE: the OLD Active Evaluator routes (review 024), FIXED clock, deterministic ids. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/evaluator_oracle.py IN.json OUT.json

IN = {clock, steps: [{op, body?, id?, at?}]} over a scratch PZ_DATA (a COPY: the writes rewrite evaluations.json,
founder_calls.json and real_data.json). ``at`` moves the fixed clock from that step on (ISO datetime, Berlin wall
clock). Ops, through the old route functions of ``api/routers/evaluator.py``:

* ``evaluations``  GET /api/evaluations;  ``evaluation``  GET /api/evaluation?id=;
* ``read_all``  GET /api/evaluations, then GET /api/evaluation for every session id of the stored file (+ an unknown);
* ``imq_trigger``  POST /api/imq_trigger;  any other op ``act``: POST /api/eval_<act> (``start``, ``deck``, ``next``,
  ``skip``, ``answer``, ``evidence``, ``resolve``, ``end``, or an unknown action). Each write is followed by the whole
  GET /api/evaluations body (``view``), the stored evaluations.json (``store``: body + the session key ORDER), the
  stored founder_calls.json (``calls``: body + key order) and the stored real_data.json ``signals``.

Placeholders in a body / id (whole strings, resolved against the stored evaluations.json before the step): ``@S<k>``
the id of the k-th session started by the script; ``@Q<k>:<i>`` the id of question ``i`` (Python index) of that
session; ``@QO<k>`` the first question without an answer that is not skipped; ``@C<k>:<text>`` the first ledger claim
whose text contains ``text``; ``@X<k>:<i>`` the i-th CONTRADICTION claim. Unresolvable: ``"@missing"``.

Each answer is {code, body}; a raised exception is {raises: name}. ``uuid4`` is a counter in every old module that
uses it (``evaluator``, ``founder_calls``): the n-th ``uuid4().hex`` is ``f"{n:06x}" + "0" * 26``, so the new side
can reproduce every id. ``date.today()`` / ``datetime.now()`` are frozen in the evaluator, Founder Calls, IMQ,
Founder Radar evidence, Taste Map and people modules. ``case_prep`` is disabled (``PZ_CASE_PREP=0``).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

NOW: list[datetime] = []
COUNTER = [0]
STARTED: list[str] = []


def _freeze() -> None:
    from projectzero.domain import evaluator, founder_calls, imq, people, taste
    from projectzero.domain.founder_radar import evidence

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
            self.hex = f"{n:06x}" + "0" * 26

    class _UuidModule:
        @staticmethod
        def uuid4() -> _Uuid:
            COUNTER[0] += 1
            return _Uuid(COUNTER[0])

    for mod in (evaluator, founder_calls, imq, evidence, taste, people):
        if hasattr(mod, "date"):
            mod.date = FixedDate  # type: ignore[attr-defined]
        if hasattr(mod, "datetime"):
            mod.datetime = FixedDateTime  # type: ignore[attr-defined]
    evaluator.uuid = _UuidModule  # type: ignore[attr-defined]
    founder_calls.uuid = _UuidModule  # type: ignore[attr-defined]


def _answer(fn: Any) -> dict[str, Any]:
    from fastapi.responses import JSONResponse

    try:
        r = fn()
    except Exception as exc:  # the old route would have answered 500
        return {"raises": type(exc).__name__}
    if isinstance(r, JSONResponse):
        return {"code": r.status_code, "body": json.loads(r.body)}
    return {"code": 200, "body": json.loads(json.dumps(r, ensure_ascii=False, default=str))}


def _get(fn: Any, sid: Any) -> dict[str, Any]:
    from starlette.requests import Request

    req = Request({"type": "http", "query_string": urlencode({"id": sid}).encode(), "headers": []})
    return _answer(lambda: fn(req))


def _file(name: str) -> Any:
    from projectzero import storage

    p = Path(storage.path(name))
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _store() -> dict[str, Any]:
    body = _file("evaluations.json")
    sessions = body.get("sessions") if isinstance(body, dict) else None
    return {"body": body, "order": list(sessions) if isinstance(sessions, dict) else None}


def _calls() -> dict[str, Any]:
    body = _file("founder_calls.json")
    if not isinstance(body, dict):
        return {"body": body, "order": None}
    order: dict[str, Any] = {"top": list(body)}
    for k in ("companies", "founders", "calls"):
        obj = body.get(k)
        if isinstance(obj, dict):
            order[k] = list(obj)
            order[k + "_fields"] = [[i, list(r)] for i, r in obj.items() if isinstance(r, dict)]
    return {"body": body, "order": order}


def _signals() -> Any:
    body = _file("real_data.json")
    return body.get("signals") if isinstance(body, dict) else None


def resolve(value: Any, sessions: dict[str, Any], started: list[str]) -> Any:
    """The placeholders (see the header); the new side resolves them with the same rules."""
    if isinstance(value, dict):
        return {k: resolve(v, sessions, started) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, sessions, started) for v in value]
    if not isinstance(value, str) or not value.startswith("@"):
        return value
    m = re.fullmatch(r"@(S|QO|Q|C|X)(\d+)(?::(.*))?", value, re.S)
    if not m or int(m.group(2)) >= len(started):
        return "@missing"
    sid = started[int(m.group(2))]
    s = sessions.get(sid) or {}
    kind, arg = m.group(1), m.group(3)
    try:
        if kind == "S":
            return sid
        if kind == "Q":
            return s["questions"][int(arg or "0")]["id"]
        if kind == "QO":
            return next(q["id"] for q in s["questions"] if q.get("answer") is None and not q.get("skipped"))
        if kind == "C":
            return next(c["id"] for c in s["ledger"] if (arg or "") in c["text"])
        return [c for c in s["ledger"] if c["state"] == "CONTRADICTION"][int(arg or "0")]["id"]
    except (IndexError, KeyError, StopIteration, ValueError, TypeError):
        return "@missing"


def replay(inp: dict[str, Any]) -> list[dict[str, Any]]:
    from projectzero import storage
    from projectzero.api.routers import evaluator as r

    out: list[dict[str, Any]] = []
    for step in inp["steps"]:
        if step.get("at"):
            NOW.append(datetime.fromisoformat(step["at"]))
        op = step["op"]
        stored = _file("evaluations.json")
        sessions = (stored or {}).get("sessions") or {} if isinstance(stored, dict) else {}
        body = resolve(step.get("body") or {}, sessions, STARTED)
        row: dict[str, Any] = {}
        if op == "evaluations":
            row["answer"] = _answer(r.evaluations)
        elif op == "evaluation":
            row["answer"] = _get(r.evaluation, resolve(step.get("id"), sessions, STARTED))
        elif op == "read_all":
            row["view"] = _answer(r.evaluations)
            row["session"] = {i: _get(r.evaluation, i) for i in [*sessions, "ev-unknown"]}
        else:
            with storage.state_lock:
                if op == "imq_trigger":
                    row["answer"] = _answer(lambda body=body: r.imq_trigger(body))
                else:
                    row["answer"] = _answer(lambda op=op, body=body: r.eval_action(op, body))
            if op == "start" and row["answer"].get("code") == 200:
                STARTED.append(row["answer"]["body"]["id"])
            row["view"] = _answer(r.evaluations)
            row["store"] = _store()
            row["calls"] = _calls()
            row["signals"] = _signals()
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
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "clock": inp["clock"], "mode": "evaluator",
            "ids_made": COUNTER[0]}  # fmt: skip
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps({"meta": meta, "steps": steps}, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
