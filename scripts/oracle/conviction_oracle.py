"""ORACLE: the OLD Conviction code (review 011), with a FIXED clock. Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/conviction_oracle.py MODE IN.json OUT.json

MODE
  rules     IN = {clock, score: [entry], evaluate: [{entry, people, research, contradictions}], persist: [...same...],
                  days: [iso]}        -> taste.score / imq.evaluate / imq.persist / taste.days_since + the old _meta()
  pipeline  IN = {clock}              -> the old pipeline() with imq.persist DISABLED (it would write), _meta(),
                                          and case_prep.view(slug) for every slug (+ one unknown)
  writes    IN = {clock, steps: [{op: save|status, body}], probe_ids: [inbox id]}
                                       -> per step: the HTTP code and body the old route returned, then the stored
                                          real_data.json signals, the inbox decisions of probe_ids and feedback.json
                                          decisions, after the UI's refetch (pipeline(), persist enabled)

``pipeline`` and ``writes`` need PZ_DATA = a scratch COPY of the old data folder (both write into it). ``rules`` needs
an empty scratch PZ_DATA. Case preparation is switched off (PZ_CASE_PREP=0): ``case_prep.request`` returns at once.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any


def _clock(iso: str) -> tuple[type[date], type[datetime]]:
    fixed = datetime.fromisoformat(iso)

    class FixedDate(date):
        @classmethod
        def today(cls) -> FixedDate:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> FixedDateTime:  # type: ignore[override]
            return cls(fixed.year, fixed.month, fixed.day, fixed.hour, fixed.minute, fixed.second)

    return FixedDate, FixedDateTime


def _freeze(iso: str) -> None:
    from projectzero.domain import imq, taste
    from projectzero.services import case_prep, pipeline

    fd, fdt = _clock(iso)
    taste.date = fd  # type: ignore[attr-defined]
    imq.date = fd  # type: ignore[attr-defined]
    imq.datetime = fdt  # type: ignore[attr-defined]
    case_prep.date = fd  # type: ignore[attr-defined]
    case_prep.datetime = fdt  # type: ignore[attr-defined]
    pipeline.datetime = fdt  # type: ignore[attr-defined]


def _try(fn: Any) -> Any:
    try:
        return {"ok": fn()}
    except Exception as exc:  # the goldens record WHICH cases raise, not only what the others return
        return {"raises": type(exc).__name__}


def rules(inp: dict[str, Any]) -> dict[str, Any]:
    from projectzero.api.routers import system
    from projectzero.domain import imq, taste

    out: dict[str, Any] = {"score": [], "evaluate": [], "persist": [], "days": []}
    for e in inp["score"]:
        out["score"].append(_try(lambda e=e: taste.score(copy.deepcopy(e))))
    for c in inp["evaluate"]:
        out["evaluate"].append(_try(lambda c=c: imq.evaluate(copy.deepcopy(c["entry"]), c["people"], c["research"],
                                                             c["contradictions"])))  # fmt: skip
    for c in inp["persist"]:
        entry = copy.deepcopy(c["entry"])
        ev = imq.evaluate(entry, c["people"], c["research"], c["contradictions"])
        changed = imq.persist(entry, ev)
        out["persist"].append({"changed": changed, "imq": entry.get("imq"), "state": ev["state"]})
    for iso in inp["days"]:
        out["days"].append(taste.days_since(iso))
    out["api_meta"] = system._meta()
    return out


def pipeline_mode(_inp: dict[str, Any]) -> dict[str, Any]:
    from projectzero.api.routers import system
    from projectzero.domain import imq
    from projectzero.services import pipeline

    from projectzero.services import case_prep

    imq.persist = lambda entry, ev: False  # reads never write (decision a): compare against the snapshot as stored
    view = pipeline.pipeline()
    slugs = [e["slug"] for e in view["signals"]] + ["no-such-company"]
    return {"view": view, "api_meta": system._meta(), "cases": {s: case_prep.view(s) for s in slugs}}


def writes(inp: dict[str, Any]) -> dict[str, Any]:
    from projectzero import storage
    from projectzero.services import pipeline

    out = []
    for step in inp["steps"]:
        body = copy.deepcopy(step["body"])
        with storage.state_lock:
            if step["op"] == "save":
                code, payload = pipeline.save_entry(body)
            else:
                r = pipeline.set_status(body)
                if r.get("not_found"):
                    code, payload = 404, {"error": "unknown company — nothing was changed"}
                elif r.get("ok") is False:
                    code, payload = 400, {"error": r["error"]}
                else:
                    code, payload = 200, r
        pipeline.pipeline()  # the page's refetch after the write (the old read persisted the IMQ snapshot)
        stored = storage.load_json("real_data.json", {})
        inbox = {c.get("id"): c for c in storage.load_json("inbox.json", {}).get("candidates", []) if isinstance(c, dict)}
        fb = storage.load_json("feedback.json", {}) or {}
        out.append({
            "code": code,
            "body": payload,
            "signals": stored.get("signals", []),
            "decisions": {i: (inbox.get(i) or {}).get("decision") for i in inp["probe_ids"]},
            "ledger": {k: {f: v for f, v in d.items() if f != "ts"} for k, d in (fb.get("decisions") or {}).items()},
        })  # fmt: skip
    final = pipeline.pipeline()
    return {"steps": out, "view": final}


def main() -> int:
    mode, src, dst = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and Path(data_dir).name != "project-zero-data", "PZ_DATA must be a scratch folder"
    os.environ.setdefault("PZ_TESTING", "1")
    os.environ["PZ_CASE_PREP"] = "0"
    inp = json.loads(src.read_text(encoding="utf-8"))
    _freeze(inp["clock"])
    from projectzero.domain import taste  # the OLD package

    old_root = Path(taste.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    result = {"rules": rules, "pipeline": pipeline_mode, "writes": writes}[mode](inp)
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "clock": inp["clock"], "mode": mode}
    dst.write_text(json.dumps({"meta": meta, **result}, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
