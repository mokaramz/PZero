"""ORACLE: the OLD triage decisions (review 035a), with a FIXED clock. Never imported by the new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/triage_decide_oracle.py IN.json OUT.json

IN = {aliases: {old id: survivor}, steps: [{clock, op: "decide" | "batch" | "view", body}]} (``view``: no write).
``PZ_DATA`` is a scratch folder
holding the world's files (``inbox.json``, ``triage_proposals.json``, ``triage_decisions.jsonl``, ...).

Per step, at the step's clock: the old ``triage_review.decide(body)`` or ``batch_reject(body)`` (a ``TriageError`` is
recorded as ``{error}``), then the record of: the answer, the whole ``triage_decisions.jsonl`` text, every inbox
candidate's ``{id, decision, notes}``, the old ``view()``, and (declared e) the old ``_latest_verdicts()`` and
``calibration()`` over the SAME log lines with each line's ``candidate_id`` mapped through ``aliases`` first, so the
expected "per survivor" values come from the old code too. The old RESEARCH side effect ``case_prep.request`` (a paid
case preparation, declared c) is replaced by a recorder and listed as ``case_prep``.

The clock: ``datetime.now()`` / ``date.today()`` of every loaded ``projectzero`` module. Writes: ``storage.save_json`` /
``write_text`` / ``append_line`` outside the scratch data folder are refused and recorded as ``blocked``. Refused: a
``PZ_DATA`` inside ``project-zero-data``, and any ``SUPABASE_DB_URL``.
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

NOW: list[datetime] = []
BLOCKED: list[str] = []
CASE_PREP: list[list[str]] = []


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
                raise RuntimeError(f"the triage oracle blocks {name} outside the scratch folder: {full}")
            return fn(target, *a, **k)

        return guarded

    storage.save_json = inside("save_json", storage.save_json)  # type: ignore[assignment]
    storage.write_text = inside("write_text", storage.write_text)  # type: ignore[assignment]
    storage.append_line = inside("append_line", storage.append_line)  # type: ignore[assignment]


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and "project-zero-data" not in Path(data_dir).resolve().parts, "PZ_DATA must be a scratch folder"
    assert not os.environ.get("SUPABASE_DB_URL"), "the oracle never sees the database"
    os.environ.setdefault("PZ_TESTING", "1")
    root = Path(data_dir).resolve()
    inp = json.loads(src.read_bytes().decode("utf-8"))
    aliases: dict[str, str] = inp.get("aliases") or {}
    NOW.append(datetime.fromisoformat(inp["steps"][0]["clock"]))
    from projectzero.services import case_prep, compressor, discovery, triage_review  # noqa: F401

    from projectzero import storage

    storage.configure(root)

    def record_case_prep(slug: str, reason: str, **_: Any) -> dict[str, Any]:
        CASE_PREP.append([slug, reason])
        return {"queued": False, "oracle": True}

    case_prep.request = record_case_prep  # type: ignore[assignment]
    frozen = _freeze()
    _block(root)
    original_decisions = triage_review.decisions

    def survivor_view() -> dict[str, Any]:
        mapped = [
            {**e, "candidate_id": aliases.get(e["candidate_id"], e["candidate_id"])}
            if isinstance(e.get("candidate_id"), str)
            else e
            for e in original_decisions()
        ]
        triage_review.decisions = lambda: copy.deepcopy(mapped)  # type: ignore[assignment]
        try:
            return {"latest": triage_review._latest_verdicts(), "calibration": triage_review.calibration()}
        finally:
            triage_review.decisions = original_decisions  # type: ignore[assignment]

    steps = []
    for step in inp["steps"]:
        NOW.append(datetime.fromisoformat(step["clock"]))
        CASE_PREP.clear()
        fn = triage_review.decide if step["op"] == "decide" else triage_review.batch_reject
        try:
            answer: dict[str, Any] = {"answer": None if step["op"] == "view" else fn(copy.deepcopy(step["body"]))}
        except triage_review.TriageError as e:
            answer = {"error": str(e)}
        inbox = discovery.load_inbox({"candidates": []})
        steps.append({
            "clock": step["clock"],
            **answer,
            "log": storage.read_text(triage_review.DECISION_LOG),
            "inbox": [{"id": c.get("id"), "decision": c.get("decision"), "notes": c.get("notes")}
                      for c in inbox.get("candidates", []) if isinstance(c, dict)],
            "view": triage_review.view(),
            "survivor": survivor_view(),
            "case_prep": list(CASE_PREP),
        })  # fmt: skip
    old_root = Path(triage_review.__file__).resolve().parents[4]
    revision = subprocess.run(["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()  # fmt: skip
    dirty = subprocess.run(["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
                           capture_output=True, text=True, check=True).stdout.strip()  # fmt: skip
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "mode": "triage_decide", "frozen": frozen}
    out = {"meta": meta, "steps": steps, "blocked": list(BLOCKED)}
    dst.write_bytes(json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
