"""ORACLE: replays a decision script on the OLD ``feedback.record_decision`` (review 008). Never imported by new code.

    <old>/backend/.venv/Scripts/python.exe scripts/oracle/feedback_write_oracle.py IN.json OUT.json

IN.json  = {"base": ledger | null, "steps": [{"candidate": {...}, "decision": "kept"}...], "probes": [{...}...]}
OUT.json = {"meta": {...}, "steps": [{"entry": ..., "decision_keys": [...], "decisions": {...}, "table": {...},
                                      "probes": {id: for_candidate}}]}

The ledger goes through the OLD production file path: ``base`` is written as <PZ_DATA>/feedback.json, every step calls
the real ``record_decision`` (strict load, mutate, save), then ``table()`` / ``for_candidate`` read it back.
PZ_DATA must point at an empty scratch folder.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data_dir = os.environ.get("PZ_DATA", "")
    assert data_dir and "project-zero-data" not in data_dir, "PZ_DATA must be a scratch folder"
    os.environ.setdefault("PZ_TESTING", "1")

    from projectzero.domain import feedback  # the OLD package

    old_root = Path(feedback.__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "-C", str(old_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old_root), "status", "--porcelain", "--", "backend/src/projectzero"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()

    inp = json.loads(src.read_text(encoding="utf-8"))
    ledger_file = Path(data_dir) / "feedback.json"
    if inp["base"] is not None:
        ledger_file.write_text(json.dumps(inp["base"]), encoding="utf-8")
    feedback._CACHE["sig"] = None
    out = []
    for step in inp["steps"]:
        entry = feedback.record_decision(step["candidate"], step["decision"])
        d = feedback.load()
        feedback._CACHE["sig"] = None
        table = feedback.table()
        out.append({
            "entry": None if entry is None else {k: v for k, v in entry.items() if k != "ts"},
            "decision_keys": list(d["decisions"]),
            "decisions": {k: {f: v for f, v in e.items() if f != "ts"} for k, e in d["decisions"].items()},
            "table": table,
            "probes": {p["id"]: feedback.for_candidate(p, table) for p in inp["probes"]},
        })
    meta = {"old_revision": revision, "old_dirty": bool(dirty), "steps": len(out)}
    dst.write_text(json.dumps({"meta": meta, "steps": out}, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
